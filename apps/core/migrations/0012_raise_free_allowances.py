"""Bring free periods already under way up to the raised free plan.

The free plan's monthly allowances were raised (tasks 90 → 300, processed
pages 500 → 3,000, AI credits → 1,050). Allowances are granted once per
period, so without this a customer would see the new figures on the pricing
page but only receive them at their next renewal, up to 30 days later.

It only ever raises, only touches free `included:` grants, and only periods
still running. An administrator's override of a free limit still wins over
these figures, exactly as it does for new periods.
"""
from django.db import migrations
from django.utils import timezone

RAISED = {'file_tasks': 300, 'file_page_units': 3000, 'ai_credits': 1050}


def raise_allowances(apps, schema_editor):
    UsageGrant = apps.get_model('core', 'UsageGrant')
    IntegrationConfig = apps.get_model('operations', 'IntegrationConfig')
    row = IntegrationConfig.objects.filter(pk='plan_limits').first()
    override = ((row.configuration if row else None) or {}).get('free') or {}
    now = timezone.now()
    for meter, value in RAISED.items():
        value = override.get(meter, value)
        if isinstance(value, int):
            UsageGrant.objects.filter(source_id__startswith='included:', meter=meter,
                                      expires_at__gt=now, quantity__lt=value).update(quantity=value)


class Migration(migrations.Migration):
    dependencies = [('core', '0011_staff_plan_override'), ('operations', '0002_integrationconfig')]
    operations = [migrations.RunPython(raise_allowances, migrations.RunPython.noop)]
