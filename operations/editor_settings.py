"""The new editors' switches and lane budgets, as an operator changes them without a deploy.

Read through `integrations.editor_config`: what is saved here wins, then the
environment, then off and the default budgets. Turning `editor_v2` off is the
runbook's way back to the old editor.
"""
from .integrations import EDITOR_BUDGETS, EDITOR_FLAGS, editor_config
from .models import IntegrationConfig

KEY = 'editor'
# Seconds of work per account per day, on Free; the multiplier is what a paid plan has over that.
BOUNDS = {**{name: (0, 86400) for name in EDITOR_BUDGETS}, 'paid_multiplier': (1, 20)}
TRUE, FALSE = ('true', '1', 'on'), ('false', '0', 'off', '')


class EditorSettingsError(ValueError):
    """A rejected edit, with a message meant for the operator."""


def validate(values):
    """Coerce an edit to known names only: booleans for the switches, bounded whole numbers for the budgets."""
    cleaned = {}
    for name, raw in values.items():
        text = str(raw).strip().lower()
        if name in EDITOR_FLAGS:
            if text not in TRUE + FALSE:
                raise EditorSettingsError(f'{name} must be on or off.')
            cleaned[name] = text in TRUE
        elif name in BOUNDS:
            low, high = BOUNDS[name]
            try:
                number = int(text)
            except ValueError:
                raise EditorSettingsError(f'{name} must be a whole number.') from None
            if not low <= number <= high:
                raise EditorSettingsError(f'{name} must be between {low:,} and {high:,}.')
            cleaned[name] = number
        else:
            raise EditorSettingsError(f'Unknown setting: {name}.')
    if not cleaned:
        raise EditorSettingsError('Nothing to change.')
    return cleaned


def save(values):
    """Store an edit over what is in force. Returns (before, after), holding only what changed."""
    cleaned = validate(values)
    current = editor_config()
    changed = {name: value for name, value in cleaned.items() if current[name] != value}
    # Everything in force is written, not only the edit: a row that held half
    # the settings would leave the rest following the environment unseen.
    IntegrationConfig.objects.update_or_create(pk=KEY, defaults={'configuration': {**current, **cleaned}})
    return {name: current[name] for name in changed}, changed
