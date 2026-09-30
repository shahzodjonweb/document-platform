"""Give free periods under way the tripled AI credit allowance.

Every plan's AI credits were tripled (free 1,050 → 3,150, Plus 3,500 → 10,500,
Premium 10,000 → 30,000), at the owner's request.

Production also carried an administrator override holding free AI credits at
300 — below even the previous default — which kept both this and the previous
raise from reaching anyone. An override below the new figure is removed here,
and the removal is written to the audit log like any panel edit; one at or
above it is an operator's deliberate choice and stays. Other overrides are
untouched.

Then free periods still running are brought up to the allowance in force. It
only ever raises, and only free `included:` grants.
"""
from django.db import migrations
from django.utils import timezone

FREE_AI_CREDITS = 3150


def triple(apps, schema_editor):
    UsageGrant = apps.get_model('core', 'UsageGrant')
    IntegrationConfig = apps.get_model('operations', 'IntegrationConfig')
    AuditLog = apps.get_model('operations', 'AuditLog')
    row = IntegrationConfig.objects.filter(pk='plan_limits').first()
    configuration = dict((row.configuration if row else None) or {})
    free = dict(configuration.get('free') or {})
    held = free.get('ai_credits')
    if isinstance(held, int) and held < FREE_AI_CREDITS:
        free.pop('ai_credits')
        if free:
            configuration['free'] = free
        else:
            configuration.pop('free', None)
        row.configuration = configuration
        row.save(update_fields=['configuration'])
        AuditLog.objects.create(
            actor=None, action='plan.limits', target='free',
            reason='AI credits tripled for every plan at the owner\'s request; this override held '
                   'free AI credits below the new allowance, so it was removed at deploy.',
            before={'ai_credits': held}, after={'ai_credits': FREE_AI_CREDITS})
    allowance = free.get('ai_credits', FREE_AI_CREDITS)
    UsageGrant.objects.filter(source_id__startswith='included:', meter='ai_credits',
                              expires_at__gt=timezone.now(), quantity__lt=allowance).update(quantity=allowance)


class Migration(migrations.Migration):
    dependencies = [('core', '0012_raise_free_allowances'), ('operations', '0002_integrationconfig')]
    operations = [migrations.RunPython(triple, migrations.RunPython.noop)]
