from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0007_authratelimit_account_auth_version_account_email_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='BotConversation',
            fields=[
                ('telegram_user_id', models.BigIntegerField(primary_key=True, serialize=False)),
                ('locale', models.CharField(blank=True, default='', max_length=2)),
                ('language_selected_at', models.DateTimeField(blank=True, null=True)),
                ('language_nonce', models.CharField(blank=True, default='', max_length=32)),
                ('language_expires_at', models.DateTimeField(blank=True, null=True)),
                ('pending', models.JSONField(default=dict)),
                ('state', models.CharField(blank=True, default='', max_length=32)),
                ('prompt', models.JSONField(default=dict)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
