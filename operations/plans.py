"""Plan limits an administrator can change without a deploy.

The seed in docs/product/plan_seed.json is the engineering default and stays
authoritative for anything not overridden. Overrides live in the database
because a file in the repository would be replaced by the next release, and
because every change has to be attributable in the audit trail.
"""
from django.conf import settings

from .models import IntegrationConfig

KEY = 'plan_limits'

# Every field an administrator may set, with the bounds that keep the platform
# working. A limit of zero would make a plan unusable rather than restricted,
# so the floors are one wherever the value is a per-job capability.
FIELDS = {
    'price_xtr': (0, 1_000_000),
    # So'm per 30 days for a card transfer; blank means not for sale.
    'price_uzs': (1_000, 100_000_000),
    # AI documents (PDF documents and decks) a week; blank is unlimited.
    'weekly_ai_documents': (1, 10_000),
    # File tasks a week, every tool sharing one count; blank is unlimited.
    'weekly_file_jobs': (1, 100_000),
    # Zero is meaningful here: a plan whose files cannot be edited by prompt.
    'edits_per_file': (0, 1_000),
    # The seed's name for it; `max_file_mb` here once made the file size a
    # field the panel showed but silently never saved.
    'max_file_mib': (1, 2_000),
    'max_pages_per_job': (1, 10_000),
    'concurrent_jobs': (1, 64),
    'max_ai_source_pages': (1, 2_000),
    'max_ai_source_files': (1, 100),
    # Zero is meaningful here: a plan whose decks get no photos.
    'max_deck_images': (0, 60),
    'max_ai_input_tokens': (1_000, 2_000_000),
    'max_generated_pdf_pages': (1, 500),
    'max_generated_slides': (1, 500),
    'saved_workflows': (0, 1_000),
    'saved_teacher_templates': (0, 1_000),
}


# Blank is a real value for these: no price means a plan is not for sale, and
# no limit means unlimited.
NULLABLE = {'price_xtr', 'price_uzs', 'weekly_ai_documents', 'weekly_file_jobs', 'edits_per_file'}
WEEKLY = ('weekly_ai_documents', 'weekly_file_jobs')
# What the free plan may never leave unlimited, and what no paid plan may set
# below the free plan's: each of them is AI or processing paid for per use.
# These are also the only limits that differ by plan, at the owner's decision;
# every other one is the same on every plan, so Free is held under a paid plan
# only here.
FLOOR = (*WEEKLY, 'edits_per_file')
# What each plan sets for itself: its prices and the limits above. Every other
# field is one value for all three plans, so a change made from any plan's
# form is written to every plan (save, reset); a field edited per plan would
# bring back the plan differences the owner removed.
PER_PLAN = ('price_xtr', 'price_uzs', *FLOOR)
SHARED = tuple(field for field in FIELDS if field not in PER_PLAN)


class PlanError(ValueError):
    """A rejected plan edit, with a message meant for the operator."""


def seed():
    import json
    return json.loads((settings.BASE_DIR / 'docs' / 'product' / 'plan_seed.json').read_text())


def overrides():
    row = IntegrationConfig.objects.filter(pk=KEY).first()
    return row.configuration if row else {}


def limits_for(plan_id, defaults):
    """Seed values for one plan with any administrator changes applied."""
    changed = overrides().get(plan_id)
    return {**defaults, **changed} if changed else dict(defaults)


def validate(plan_id, values, defaults):
    """Coerce and bound an edit, refusing anything that would break a plan."""
    if plan_id not in defaults:
        raise PlanError('Unknown plan.')
    known = defaults[plan_id]
    cleaned = {}
    for field, raw in values.items():
        if field not in FIELDS or field not in known:
            continue
        text = str(raw).strip()
        if not text:
            if field not in NULLABLE:
                raise PlanError(f'{field} needs a value.')
            # The free plan must keep both weekly limits and its edits per file;
            # removing one would hand out unlimited documents, file tasks or AI
            # edits to anyone who signs up.
            if plan_id == 'free' and field in WEEKLY:
                raise PlanError('The free plan must keep both weekly limits.')
            if plan_id == 'free' and field == 'edits_per_file':
                raise PlanError('The free plan must keep a limit on AI edits per file.')
            cleaned[field] = None
            continue
        low, high = FIELDS[field]
        try:
            number = int(text)
        except (TypeError, ValueError):
            raise PlanError(f'{field} must be a whole number.') from None
        if not low <= number <= high:
            raise PlanError(f'{field} must be between {low:,} and {high:,}.')
        cleaned[field] = number
    if not cleaned:
        raise PlanError('Nothing to change.')
    if plan_id == 'free' and cleaned.get('price_uzs') is not None:
        raise PlanError('The free plan has no price.')
    # Free must stay the floor on what a payment buys: a free plan above a paid
    # one would let anyone take the paid allowance without paying for it, and a
    # paid plan below free gives paying customers less. Both sides are compared
    # as they stand, panel changes included; None is unlimited, which nothing
    # exceeds. Only values this edit actually changes are compared: the form
    # sends every field, and a plan left out of step earlier must not stop an
    # unrelated change. Page and photo ceilings were once held here too; now
    # every plan has the same ones, and holding Free under Plus there would only
    # refuse raising all three plans unless the paid ones went first.
    current = limits_for(plan_id, known)
    changed = {field: value for field, value in cleaned.items() if current.get(field) != value}
    if plan_id == 'free':
        paid_plans = [limits_for(paid, defaults[paid]) for paid in defaults if paid != 'free']
        for field in FLOOR:
            if changed.get(field) is not None and any(
                    paid.get(field) is not None and changed[field] > paid[field] for paid in paid_plans):
                raise PlanError(f'Free {field} cannot exceed a paid plan.')
    elif 'free' in defaults:
        free = limits_for('free', defaults['free'])
        for field in FLOOR:
            if changed.get(field) is not None and (free.get(field) is None or changed[field] < free[field]):
                raise PlanError(f'{plan_id.title()} {field} cannot be below the free plan.')
    return cleaned


def _stored(configuration, plan_id):
    """One plan's stored overrides; a malformed entry counts as none, as pricing reads it."""
    values = configuration.get(plan_id) if isinstance(configuration, dict) else None
    return values if isinstance(values, dict) else {}


def _commit(defaults, current, configuration):
    """Store `configuration` and say what it changed on each plan: {plan: (before, after)}.

    Only plans whose limits actually changed are listed, so each one gets one
    audit row and an unchanged form gets none.
    """
    if configuration != current:
        IntegrationConfig.objects.update_or_create(pk=KEY, defaults={'configuration': configuration})
    changes = {}
    for plan_id, seeded in defaults.items():
        before = {**seeded, **_stored(current, plan_id)}
        after = {**seeded, **_stored(configuration, plan_id)}
        old = {k: v for k, v in before.items() if after.get(k) != v}
        new = {k: v for k, v in after.items() if before.get(k) != v}
        if old or new:
            changes[plan_id] = (old, new)
    return changes


def _put(configuration, defaults, plan_id, values):
    """Keep only the overrides that differ from the plan's seed; none left removes the entry."""
    kept = {k: v for k, v in values.items() if defaults[plan_id].get(k) != v}
    if kept:
        configuration[plan_id] = kept
    else:
        configuration.pop(plan_id, None)


def save(plan_id, values):
    """Store an edit, keeping only the fields that differ from the seed.

    The edited plan's prices and weekly limits are its own; every other field
    is written to every plan, so the plans stay equal in everything else.
    Returns {plan: (before, after)} for each plan the edit changed.
    """
    defaults = seed()['plans']
    cleaned = validate(plan_id, values, defaults)
    current = overrides()
    configuration = dict(current) if isinstance(current, dict) else {}
    for plan in defaults:
        edit = {k: v for k, v in cleaned.items()
                if k in defaults[plan] and (k not in PER_PLAN or plan == plan_id)}
        if edit:
            _put(configuration, defaults, plan, {**_stored(current, plan), **edit})
    return _commit(defaults, current, configuration)


def reset(plan_id):
    """Put a plan back to its seed. Its shared limits are every plan's, so they go back on every plan.

    Returns {plan: (before, after)} for each plan that changed.
    """
    defaults = seed()['plans']
    current = overrides()
    configuration = dict(current) if isinstance(current, dict) else {}
    configuration.pop(plan_id, None)
    for plan in defaults:
        if plan != plan_id and plan in configuration:
            _put(configuration, defaults, plan, {k: v for k, v in _stored(current, plan).items() if k in PER_PLAN})
    return _commit(defaults, current, configuration)
