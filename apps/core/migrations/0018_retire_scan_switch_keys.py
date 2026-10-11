"""Remove the retired images-to-PDF scan switches from data that can still run.

`pdf.images_to_pdf` had two switches, `auto_crop` and `enhance_text`, from
6 to 11 October 2026; the scanner now decides on its own. While they existed,
every images-to-PDF quote, job and bot draft was saved with both keys (the
normalizer filled in `True`), and the bot's settings screen had a button for
each. Afterwards the code dropped the keys wherever they turned up. This
removes them from what can still be used, so the code no longer has to:

- bot drafts lose the two keys and keep their other settings (the version is
  not bumped, so the screen on show keeps working);
- a bot button that only toggled a switch keeps its draft binding, with empty
  parameters and the marker `'retired': 'scan_switches'`; the bot answers it
  with a notice. Any other settings button only loses the two keys;
- quotes not yet confirmed and jobs not yet finished lose the two keys.

Finished jobs, and the quotes they were confirmed from, are the record of what
ran and keep what they were given. Nothing else held these keys: saved
workflows cannot contain images-to-PDF, batch items point at quotes, and
browsers' saved drafts are stripped by the web app itself.

It only removes keys, so a second run changes nothing, and there is nothing to
put back on the way down.
"""
from django.db import migrations, transaction
from django.db.models import Q

KEYS = ('auto_crop', 'enhance_text')
FEATURE = 'pdf.images_to_pdf'
FINISHED = ('succeeded', 'failed', 'canceled', 'no_op', 'expired')
RETIRED = 'scan_switches'
BATCH = 500


def carrying(path):
    return Q(**{f'{path}__has_key': KEYS[0]}) | Q(**{f'{path}__has_key': KEYS[1]})


def without_keys(parameters):
    return {key: value for key, value in parameters.items() if key not in KEYS}


def button_payload(payload):
    parameters = payload.get('parameters')
    if not isinstance(parameters, dict):
        return payload
    left = without_keys(parameters)
    if left or len(left) == len(parameters):
        return {**payload, 'parameters': left}
    # Only a switch was left to toggle. Empty parameters keep the button
    # harmless to the code still running while the deploy finishes.
    kept = {key: value for key, value in payload.items() if key != 'replace'}
    return {**kept, 'parameters': {}, 'retired': RETIRED}


def rewrite(queryset, field, change):
    """Apply `change` to `field` on every row of `queryset`, a batch at a time.

    The ids are read first: the rows stop matching once changed, and SQLite
    does not isolate a running read from writes to the same table. Each batch
    is locked from its read to its write (and, inside the atomic migration,
    until commit): the old code keeps serving during the deploy, and a draft
    it saves in between would otherwise be overwritten with stale values.
    """
    model = queryset.model
    ids = list(queryset.values_list('pk', flat=True).iterator(chunk_size=BATCH))
    for start in range(0, len(ids), BATCH):
        with transaction.atomic(using=queryset.db):
            batch = model.objects.select_for_update().filter(pk__in=ids[start:start + BATCH]).order_by('pk')
            rows = list(batch.only('pk', field))
            for row in rows:
                setattr(row, field, change(getattr(row, field)))
            model.objects.bulk_update(rows, [field])


def retire_scan_switches(apps, schema_editor):
    BotDraft = apps.get_model('core', 'BotDraft')
    BotCallback = apps.get_model('core', 'BotCallback')
    Quote = apps.get_model('core', 'Quote')
    Job = apps.get_model('core', 'Job')
    rewrite(BotDraft.objects.filter(carrying('parameters'), feature_id=FEATURE), 'parameters', without_keys)
    rewrite(BotCallback.objects.filter(carrying('payload__parameters'), action='settings'), 'payload', button_payload)
    rewrite(Quote.objects.filter(carrying('parameters'), feature_id=FEATURE, job__isnull=True), 'parameters', without_keys)
    rewrite(Job.objects.filter(carrying('parameters'), feature_id=FEATURE).exclude(status__in=FINISHED),
            'parameters', without_keys)


class Migration(migrations.Migration):
    dependencies = [('core', '0017_bot_review')]
    operations = [migrations.RunPython(retire_scan_switches, migrations.RunPython.noop)]
