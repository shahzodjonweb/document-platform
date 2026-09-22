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
    # Paid activation intentionally unavailable; a local admin cannot fabricate paid consideration.
    return SEED['plans'].get(account.plan, SEED['plans']['free'])

def cycle(account, at=None):
    at = at or timezone.now()
    seconds = SEED['period_seconds']
    index = max(0, int((at - account.created_at).total_seconds()) // seconds)
    start = account.created_at + timedelta(seconds=index * seconds)
    return start, start + timedelta(seconds=seconds)

def ensure_grants(account):
    start, end = cycle(account)
    for meter in METERS:
        UsageGrant.objects.get_or_create(source_id=f'included:{account.id}:{start.isoformat()}:{meter}', defaults={'account': account, 'meter': meter, 'quantity': plan_limits(account)[meter], 'valid_from': start, 'expires_at': end})
    return end

def active_grants(account):
    from django.db.models import Q
    now = timezone.now()
    return UsageGrant.objects.filter(account=account, valid_from__lte=now).filter(Q(expires_at__gt=now) | Q(expires_at__isnull=True))

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
    if not settings.ENABLE_BETA_TOOLS or feature_id not in enabled_capabilities():
        raise DomainError('feature_unavailable', 409)
    feature = FEATURES[feature_id]
    if feature['plans'][account.plan] in ('not_included', 'unavailable', 'none', 'excluded'):
        raise DomainError('feature_not_in_plan', 403)
    return feature
