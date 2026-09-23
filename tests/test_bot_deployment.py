from io import StringIO
from unittest.mock import AsyncMock, patch
from apps.core.management.commands.runbot import Command


def test_production_bot_waits_for_admin_configuration_without_network_calls():
    with patch('apps.commerce.providers.telegram_config',side_effect=[{}, {'token':'configured'}]), \
         patch('apps.core.management.commands.runbot.time.sleep') as sleep, \
         patch('apps.core.management.commands.runbot.run_polling',new_callable=AsyncMock) as polling:
        output=StringIO()
        Command(stdout=output).handle(wait_for_config=True)
        sleep.assert_called_once_with(10)
        polling.assert_awaited_once()
        assert 'Waiting for polling credentials' in output.getvalue()
        assert 'configured' not in output.getvalue()


def test_polling_waits_while_webhook_mode_is_configured():
    with patch('apps.commerce.providers.telegram_config',side_effect=[
        {'token':'configured','webhook_secret':'webhook'}, {'token':'configured'}]), \
         patch('apps.core.management.commands.runbot.time.sleep') as sleep, \
         patch('apps.core.management.commands.runbot.run_polling',new_callable=AsyncMock) as polling:
        Command(stdout=StringIO()).handle(wait_for_config=True)
        sleep.assert_called_once_with(10)
        polling.assert_awaited_once()
