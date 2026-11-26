from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0022_post_button_action'),
    ]

    operations = [
        migrations.AddField(
            model_name='post',
            name='resent_from',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name='repeats', to='core.post'),
        ),
    ]
