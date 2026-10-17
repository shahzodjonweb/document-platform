# The plan's regular price when a card-transfer request was opened, so a
# request opened at a discount is known as one after the discount has moved
# on. Nullable: every request from before discounts was opened at the regular
# price, and nothing is backfilled.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('commerce', '0003_manual_payments'),
    ]

    operations = [
        migrations.AddField(
            model_name='manualpayment',
            name='regular_amount',
            field=models.PositiveIntegerField(null=True),
        ),
    ]
