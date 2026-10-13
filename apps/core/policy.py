import json
from django.conf import settings
from .errors import DomainError

ROOT = settings.BASE_DIR / 'docs' / 'product'
SEED = json.loads((ROOT / 'plan_seed.json').read_text())
FEATURES = {f['id']: f for f in json.loads((ROOT / 'feature_catalog.json').read_text())['features']}
POLICY_VERSION = 'weekly-v1'

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

def usage_snapshot(account):
    """This week's allowance and what is left of it (apps/core/allowance.py)."""
    from .allowance import usage_snapshot as snapshot
    return snapshot(account)

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
