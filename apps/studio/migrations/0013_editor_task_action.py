import apps.studio.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """A picture task's action, for the day's caps; tasks and their provider records outlive a deleted draft, which would otherwise reset them."""

    dependencies = [
        ('studio', '0012_editor_one_draft_per_file'),
    ]

    operations = [
        migrations.AddField(
            model_name='editortask',
            name='action',
            field=models.CharField(blank=True, db_default='', default='', max_length=12),
        ),
        migrations.AlterField(
            model_name='editortask',
            name='draft',
            field=models.ForeignKey(null=True, on_delete=apps.studio.models.keep_picture_tasks, related_name='+', to='studio.generationdraft'),
        ),
        migrations.AlterField(
            model_name='providerusage',
            name='task',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='studio.editortask'),
        ),
    ]
