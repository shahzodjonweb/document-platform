"""The AI categories' rollout switch: on or off, and which categories customers may pick.

One `IntegrationConfig` row `categories`, `{on, live}`, off and empty until the
owner changes it on `/ops/categories`. The catalogue reads it on every call
(`apps.studio.categories.on()` and `live()`), so a change takes effect at once,
without a deploy. Off means every flow is today's: no list in the bot, no
category sources.

It is not an editor flag on purpose: those are published to every customer
under `limits.editor`, and nothing here is the web's business yet. There is no
environment fallback either: a category reaches customers only when a person
ticks it here.
"""
from django.db import transaction

from .auth import audit
from .models import IntegrationConfig

KEY = 'categories'
TRUE, FALSE = ('true', '1', 'on'), ('false', '0', 'off', '')


class CategorySettingsError(ValueError):
    """A rejected edit, with a message meant for the operator."""


def get():
    """What is in force: `{'on': bool, 'live': [ids]}`; off and empty without a saved row.

    `live` is what was ticked, as saved. Whether an id is still a ready entry
    is the catalogue's question (`live()` asks it), so an entry a later deploy
    sends back to draft drops out of the bot without anyone editing this row.
    """
    row = IntegrationConfig.objects.filter(pk=KEY).only('configuration').first()
    configuration = row.configuration if row and isinstance(row.configuration, dict) else {}
    ticked = configuration.get('live')
    return {'on': configuration.get('on') is True,
            'live': sorted({item for item in ticked if isinstance(item, str)}) if isinstance(ticked, list) else []}


def validate(values):
    """Coerce an edit to known names only: `on` a boolean, `live` a list of ready category ids.

    An id the catalogue does not hold, or one not ready (a draft has not had
    its native read and samples; a retired one is only kept for old drafts),
    refuses the whole edit, so nothing half-applied is saved.
    """
    from apps.studio import categories
    cleaned = {}
    for name, raw in values.items():
        if name == 'on':
            text = str(raw).strip().lower()
            if text not in TRUE + FALSE:
                raise CategorySettingsError('on must be on or off.')
            cleaned['on'] = text in TRUE
        elif name == 'live':
            ids = [raw] if isinstance(raw, str) else list(raw or ())
            for item in ids:
                entry = categories.get(item)
                if entry is None:
                    raise CategorySettingsError(f'Unknown category: {item}.')
                if entry.status != 'ready':
                    raise CategorySettingsError(f'{item} is not ready, so it cannot be ticked.')
            cleaned['live'] = sorted(set(ids))
        else:
            raise CategorySettingsError(f'Unknown setting: {name}.')
    if not cleaned:
        raise CategorySettingsError('Nothing to change.')
    return cleaned


@transaction.atomic
def save(values, user):
    """Store an edit over what is in force and audit it. Returns (before, after), holding only what changed.

    The whole row is written, not only the edit, so it always says everything
    in force. An edit that changes nothing leaves no audit row.
    """
    cleaned = validate(values)
    current = get()
    changed = {name: value for name, value in cleaned.items() if current[name] != value}
    IntegrationConfig.objects.update_or_create(pk=KEY, defaults={'configuration': {**current, **cleaned}})
    before = {name: current[name] for name in changed}
    if changed:
        audit(user, 'categories.settings', KEY, reason='Changed the AI categories switch', before=before, after=changed)
    return before, changed
