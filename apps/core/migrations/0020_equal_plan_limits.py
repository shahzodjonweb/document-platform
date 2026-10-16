"""Every plan gets the same limits apart from the weekly ones, at the owner's request.

Free and Plus now carry Premium's figures for everything a plan limits except
its weekly AI documents, weekly file tasks, AI edits per file and price
(docs/product/plan_seed.json). The seed alone does not get there: an
administrator override of, say, Free's file size would keep the old cap after
the deploy, and an override of Premium's would leave Free and Plus behind it.

So Free's and Plus's stored overrides of the shared limits are replaced by
Premium's own, which makes all three plans come out the same whether or not
Premium was changed in the panel. Weekly limits, edits per file and prices are
each plan's own and are left exactly as they are, a plan taken off sale
included. A Free or Plus entry that is not a set of limits at all is replaced
the same way. Each change is written to the audit log like any panel edit, and
a second run finds nothing to do.
"""
from django.db import migrations

# What still differs by plan; every other limit is shared.
PER_PLAN = ('price_xtr', 'price_uzs', 'weekly_ai_documents', 'weekly_file_jobs', 'edits_per_file')
FOLLOWERS = ('free', 'plus')
MISSING = object()


def shared(values):
    return {key: value for key, value in values.items() if key not in PER_PLAN}


def equalize(apps, schema_editor):
    IntegrationConfig = apps.get_model('operations', 'IntegrationConfig')
    AuditLog = apps.get_model('operations', 'AuditLog')
    row = IntegrationConfig.objects.filter(pk='plan_limits').first()
    if not row or not isinstance(row.configuration, dict):
        return
    configuration = dict(row.configuration)
    premium = configuration.get('premium')
    # A broken Premium entry is ignored by the pricing code, which then uses
    # the seed; with nothing to copy, Free and Plus fall back to the seed too.
    target = shared(premium) if isinstance(premium, dict) else {}
    changed = False
    for plan in FOLLOWERS:
        values = configuration.get(plan, {})
        # An entry that is not a set of limits (None, a list, a string) is
        # ignored by pricing, so the plan ran on the seed; left in place it
        # would keep the plan off Premium's figures. It is replaced like an
        # empty one, or removed when there is nothing to copy.
        broken = not isinstance(values, dict)
        current = {} if broken else shared(values)
        keys = [key for key in dict.fromkeys([*current, *target])
                if current.get(key, MISSING) != target.get(key, MISSING)]
        if not keys and not broken:
            continue
        kept = {**({} if broken else {key: value for key, value in values.items() if key in PER_PLAN}), **target}
        if kept:
            configuration[plan] = kept
        else:
            configuration.pop(plan, None)
        changed = True
        # Before is what this plan had overridden; after is what it now shares
        # with Premium. A key missing from after is back on the seed, which is
        # Premium's figure now. A broken entry is recorded as it was stored.
        AuditLog.objects.create(
            actor=None, action='plan.limits', target=plan,
            reason='Every limit apart from the weekly ones, AI edits per file and the price is now the same on '
                   'every plan, at Premium\'s figures, at the owner\'s request; '
                   + ('this plan\'s stored limits could not be read (pricing used the defaults) and were replaced by '
                      'Premium\'s at deploy.' if broken else
                      'this plan\'s overrides of those limits were replaced by Premium\'s at deploy.'),
            before={'entry': values} if broken else {key: current[key] for key in keys if key in current},
            after={key: target[key] for key in keys if key in target})
    if changed:
        row.configuration = configuration
        row.save(update_fields=['configuration'])


class Migration(migrations.Migration):
    dependencies = [('core', '0019_weekly_limits'), ('operations', '0003_remove_staff_authenticator')]
    operations = [migrations.RunPython(equalize, migrations.RunPython.noop)]
