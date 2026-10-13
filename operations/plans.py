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
FLOOR = (*WEEKLY, 'edits_per_file')


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
    # Free must stay the floor: a free plan above a paid one would let anyone
    # take the paid allowance without paying for it, and a paid plan below free
    # gives paying customers less. Both sides are compared as they stand, panel
    # changes included; None is unlimited, which nothing exceeds. Only values
    # this edit actually changes are compared: the form sends every field, and
    # a plan left out of step earlier must not stop an unrelated change.
    current = limits_for(plan_id, known)
    changed = {field: value for field, value in cleaned.items() if current.get(field) != value}
    if plan_id == 'free':
        paid_plans = [limits_for(paid, defaults[paid]) for paid in defaults if paid != 'free']
        for field in (*FLOOR, 'max_generated_pdf_pages', 'max_deck_images'):
            if changed.get(field) is not None and any(
                    paid.get(field) is not None and changed[field] > paid[field] for paid in paid_plans):
                raise PlanError(f'Free {field} cannot exceed a paid plan.')
    elif 'free' in defaults:
        free = limits_for('free', defaults['free'])
        for field in FLOOR:
            if changed.get(field) is not None and (free.get(field) is None or changed[field] < free[field]):
                raise PlanError(f'{plan_id.title()} {field} cannot be below the free plan.')
    return cleaned


def save(plan_id, values):
    """Store an edit, keeping only the fields that differ from the seed."""
    defaults = seed()['plans']
    cleaned = validate(plan_id, values, defaults)
    current = overrides()
    merged = {**current.get(plan_id, {}), **cleaned}
    before = limits_for(plan_id, defaults[plan_id])
    # A value put back to its seed default stops being an override.
    merged = {k: v for k, v in merged.items() if defaults[plan_id].get(k) != v}
    configuration = {**current, plan_id: merged} if merged else {k: v for k, v in current.items() if k != plan_id}
    IntegrationConfig.objects.update_or_create(pk=KEY, defaults={'configuration': configuration})
    after = limits_for(plan_id, defaults[plan_id])
    return {k: v for k, v in before.items() if after.get(k) != v}, {k: v for k, v in after.items() if before.get(k) != v}


def reset(plan_id):
    current = overrides()
    if plan_id in current:
        IntegrationConfig.objects.update_or_create(
            pk=KEY, defaults={'configuration': {k: v for k, v in current.items() if k != plan_id}})
