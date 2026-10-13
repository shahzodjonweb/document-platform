"""Weekly limits replace credits, at the owner's request.

Plans no longer carry credits, task or page allowances or daily caps; they
carry a weekly number of AI documents and file tasks and a number of AI edits
per file, and new prices (Plus 20 000 so'm, Premium 60 000 so'm a month).

Administrator overrides of the retired allowances mean nothing any more, and an
overridden price would keep the old one on sale, so both are removed from the
stored plan overrides. A blank price is not an old price: it is the owner
taking a plan off sale, and it stays. Each removal is written to the audit log
like any panel edit. Every other override (file size, pages, photos…) stays.

Grants, reservations and the ledger keep their history; nothing writes them now.
"""
from django.db import migrations

RETIRED = ('file_tasks', 'file_page_units', 'ai_credits', 'daily_file_tasks', 'daily_ai_documents', 'price_uzs')


def weekly(apps, schema_editor):
    IntegrationConfig = apps.get_model('operations', 'IntegrationConfig')
    AuditLog = apps.get_model('operations', 'AuditLog')
    row = IntegrationConfig.objects.filter(pk='plan_limits').first()
    if not row or not isinstance(row.configuration, dict):
        return
    configuration = dict(row.configuration)
    changed = False
    for plan, values in list(configuration.items()):
        if not isinstance(values, dict):
            continue
        # An explicit price_uzs of None means "not for sale"; removing it would
        # put a withdrawn plan back on sale at the seed's price.
        removed = {key: values[key] for key in RETIRED
                   if key in values and not (key == 'price_uzs' and values[key] is None)}
        if not removed:
            continue
        kept = {key: value for key, value in values.items() if key not in removed}
        if kept:
            configuration[plan] = kept
        else:
            configuration.pop(plan)
        changed = True
        AuditLog.objects.create(
            actor=None, action='plan.limits', target=plan,
            reason='Weekly limits replaced credits and the prices changed at the owner\'s request; '
                   'these overrides were removed at deploy.',
            before=removed, after={})
    if changed:
        row.configuration = configuration
        row.save(update_fields=['configuration'])


class Migration(migrations.Migration):
    dependencies = [('core', '0018_retire_scan_switch_keys'), ('operations', '0003_remove_staff_authenticator')]
    operations = [migrations.RunPython(weekly, migrations.RunPython.noop)]
