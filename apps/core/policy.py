import json
from datetime import timedelta
from django.conf import settings
from django.utils import timezone
from django.db.models import Sum
from .models import UsageGrant, UsageLedger, Reservation
from .errors import DomainError

ROOT = settings.BASE_DIR / 'docs' / 'product'
SEED = json.loads((ROOT / 'plan_seed.json').read_text())
FEATURES = {f['id']: f for f in json.loads((ROOT / 'feature_catalog.json').read_text())['features']}
METERS = ('file_tasks', 'file_page_units', 'ai_credits')
POLICY_VERSION = 'draft-staging-v1'

def plan_limits(account):
    from apps.commerce.services import refresh_account_entitlement
    refresh_account_entitlement(account)
    return limits_for_plan(account.plan)

def limits_for_plan(plan):
    """Seed limits with any administrator changes applied on top.

    The seed is the engineering default; an operator can raise or lower a plan
    from the panel without a deploy, and the override lives in the database so
    the next release does not silently undo it.
    """
    defaults = SEED['plans'].get(plan, SEED['plans']['free'])
    try:
        from operations.plans import limits_for
    except Exception:
        return defaults
    try:
        return limits_for(plan, defaults)
    except Exception:
        # A panel or database problem must never take pricing offline.
        return defaults

def cycle(account, at=None):
    at = at or timezone.now()
    seconds = SEED['period_seconds']
    index = max(0, int((at - account.created_at).total_seconds()) // seconds)
    start = account.created_at + timedelta(seconds=index * seconds)
    return start, start + timedelta(seconds=seconds)

def ensure_grants(account):
    from apps.commerce.services import ensure_account_grants
    return ensure_account_grants(account)

def active_grants(account):
    from django.db.models import Q
    now = timezone.now()
    from apps.commerce.services import eligible_grants
    return eligible_grants(account, UsageGrant.objects.filter(account=account, valid_from__lte=now).filter(Q(expires_at__gt=now) | Q(expires_at__isnull=True)))

def usage_snapshot(account):
    resets_at = ensure_grants(account)
    meters = {}
    for meter in METERS:
        totals = active_grants(account).filter(meter=meter).aggregate(limit=Sum('quantity'), used=Sum('consumed'), reserved=Sum('reserved'))
        values = {k: int(v or 0) for k, v in totals.items()}
        values['remaining'] = values['limit'] - values['used'] - values['reserved']
        meters[meter] = values
    today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    used = UsageLedger.objects.filter(account=account, meter='file_tasks', kind='consume', grant__source='included', job__created_at__gte=today).aggregate(n=Sum('amount'))['n'] or 0
    reserved = Reservation.objects.filter(job__account=account, meter='file_tasks', grant__source='included', settled=False, job__created_at__gte=today).aggregate(n=Sum('amount'))['n'] or 0
    limit = plan_limits(account)['daily_file_tasks']
    return {'plan': account.plan, 'draft': True, 'meters': meters, 'daily': {'limit': limit, 'used': used, 'reserved': reserved, 'remaining': None if limit is None else max(0, limit-used-reserved), 'resets_at': today + timedelta(days=1)}, 'resets_at': resets_at}

def enabled_capabilities():
    from processors import capabilities
    raw = capabilities()
    caps = raw if isinstance(raw, dict) else {c['id']: c for c in raw}
    return {key: value for key, value in caps.items() if key in FEATURES and value.get('available', value.get('enabled', True))}

def catalog(account=None):
    if account:
        from apps.commerce.services import refresh_account_entitlement
        refresh_account_entitlement(account)
    caps = enabled_capabilities()
    results = []
    for fid, capability in caps.items():
        if not settings.ENABLE_BETA_TOOLS:
            continue
        f = FEATURES[fid]
        access = f['plans'][account.plan if account else 'free']
        results.append({**f, 'enabled': True, 'eligible': access not in ('not_included', 'unavailable', 'none', 'excluded'), 'parameters': capability.get('parameters', capability.get('parameter_schema', {})), 'capabilities': capability, 'environment': 'development'})
    return results

def require_feature(account, feature_id):
    from apps.commerce.services import refresh_account_entitlement
    refresh_account_entitlement(account)
    if not settings.ENABLE_BETA_TOOLS or feature_id not in enabled_capabilities():
        raise DomainError('feature_unavailable', 409)
    feature = FEATURES[feature_id]
    if feature['plans'][account.plan] in ('not_included', 'unavailable', 'none', 'excluded'):
        raise DomainError('feature_not_in_plan', 403)
    return feature
