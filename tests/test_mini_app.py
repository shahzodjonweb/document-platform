"""The web app opened inside Telegram (the Mini App): the owner's switch, the chat menu button, the bot's
Open app buttons, and the download link Telegram fetches a result with."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from django.core import signing
from django.utils import timezone

from apps.core.brand import PRODUCT_NAME
from apps.core.models import Artifact
from apps.core.services import execute_job, submit_job
from apps.core.views import LINK_SALT
from operations.integrations import mini_app_ready, menu_button, save_config, telegram_config
from tests.test_platform import account, login_client, quote, upload

pytestmark = pytest.mark.django_db

HTTPS = 'https://docmaster.example/uz/app'


def switch(on, url=HTTPS):
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': url, 'mini_app': 'true' if on else 'false'})


def test_the_switch_is_off_until_ticked_and_a_form_without_it_leaves_it_alone():
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': HTTPS})
    assert telegram_config()['mini_app'] is False and menu_button() == {'type': 'commands'}
    switch(True)
    assert telegram_config()['mini_app'] is True
    # A script or an older page that does not send the box keeps the owner's choice.
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': HTTPS})
    assert telegram_config()['mini_app'] is True
    switch(False)
    assert telegram_config()['mini_app'] is False


def test_the_menu_button_opens_the_app_only_at_an_https_address(settings):
    switch(True)
    assert menu_button() == {'type': 'web_app', 'text': PRODUCT_NAME, 'web_app': {'url': HTTPS}}
    settings.DEBUG = True
    switch(True, 'http://localhost:3000/en/app')
    # Telegram refuses a web_app button that is not https: the commands stay.
    assert not mini_app_ready() and menu_button() == {'type': 'commands'}


# Async code reads the database from another thread: SQLite needs real transactions.
@pytest.mark.django_db(transaction=True)
def test_the_bot_sets_the_menu_button_it_is_configured_with():
    from telegram.commands import install_commands
    switch(True)
    bot = Mock(set_my_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
    asyncio.run(install_commands(bot))
    button = bot.set_chat_menu_button.await_args.kwargs['menu_button']
    assert button.type == 'web_app' and button.text == PRODUCT_NAME and button.web_app.url == HTTPS
    switch(False)
    asyncio.run(install_commands(bot))
    assert bot.set_chat_menu_button.await_args.kwargs['menu_button'].type == 'commands'


def test_saving_the_card_tells_telegram_only_when_the_button_changes(settings, monkeypatch):
    from tests.test_operations import staff_client
    settings.DEBUG = True
    monkeypatch.delenv('INTEGRATION_ENCRYPTION_KEY', raising=False)
    calls = []
    monkeypatch.setattr('operations.integration_views.apply_menu_button', lambda: calls.append(menu_button()) or True)
    client, _ = staff_client()
    form = {'integration': 'telegram', 'action': 'save', 'token': '', 'username': 'fixture_bot', 'webapp_url': HTTPS,
            'reason': 'Open the app inside Telegram for customers'}
    assert client.post('/ops/integrations', {**form, 'mini_app': 'true'}).status_code == 302
    assert calls == [{'type': 'web_app', 'text': PRODUCT_NAME, 'web_app': {'url': HTTPS}}]
    assert client.post('/ops/integrations', {**form, 'mini_app': 'true'}).status_code == 302
    assert len(calls) == 1, 'saved again unchanged: Telegram is not asked'
    # The page sends the hidden false before the box, and only the false when it is cleared.
    assert client.post('/ops/integrations', {**form, 'mini_app': 'false'}).status_code == 302
    assert calls[-1] == {'type': 'commands'}
    # Telegram out of reach: the owner is told the bot will set it when it starts.
    monkeypatch.setattr('operations.integration_views.apply_menu_button', lambda: False)
    response = client.post('/ops/integrations', {**form, 'mini_app': 'true'})
    assert response.status_code == 302 and response['Location'].endswith('notice=menu_pending')
    assert 'Telegram could not be told' in client.get(response['Location']).content.decode()


# Async code reads the database from another thread: SQLite needs real transactions.
@pytest.mark.django_db(transaction=True)
def test_open_buttons_open_the_app_inside_telegram_only_when_switched_on_and_in_a_private_chat():
    from telegram.bot import open_button
    customer = SimpleNamespace(locale='ru')
    private, group = SimpleNamespace(chat_id=4242), SimpleNamespace(chat_id=-100500)
    switch(False)
    off = asyncio.run(open_button(private, customer))
    assert off.web_app is None and off.url == 'https://docmaster.example/ru/app' and off.text == '🌐 Открыть сайт'
    switch(True)
    on = asyncio.run(open_button(private, customer, 'tools', 'web_tools'))
    assert on.url is None and on.web_app.url == 'https://docmaster.example/ru/app/tools'
    assert on.text == '📱 Больше инструментов в приложении'
    # Telegram takes web_app buttons in private chats only.
    assert asyncio.run(open_button(group, customer)).url == 'https://docmaster.example/ru/app'


def result_of(owner):
    job, _ = submit_job(owner, quote(owner, upload(owner)).id, 'mini-app-link-key')
    execute_job(job.id)
    return Artifact.objects.get(job=job)


def test_a_download_link_serves_one_result_without_the_session_for_five_minutes():
    owner = account()
    artifact = result_of(owner)
    answer = login_client(owner).post(f'/api/v1/artifacts/{artifact.id}/link', {}, content_type='application/json')
    assert answer.status_code == 200
    link = answer.json()
    assert link['expires_in'] == 300 and link['name'] == artifact.file.name
    assert link['url'].startswith(f'/api/v1/artifacts/{artifact.id}/download?link=')
    from django.test import Client
    anonymous = Client()
    response = anonymous.get(link['url'])
    assert response.status_code == 200 and response['Content-Disposition'].startswith('attachment')
    # Telegram Web fetches it from its own page; a download with the session needs no such header.
    assert response['Access-Control-Allow-Origin'] == 'https://web.telegram.org'
    assert 'Access-Control-Allow-Origin' not in login_client(owner).get(link['url'].split('?')[0])
    # The link alone, for nothing else: another result, a changed token, no token.
    other = result_of(account(43))
    token = link['url'].split('link=')[1]
    assert anonymous.get(f'/api/v1/artifacts/{other.id}/download?link={token}').status_code == 401
    assert anonymous.get(link['url'] + 'x').status_code == 401
    assert anonymous.get(f'/api/v1/artifacts/{artifact.id}/download').status_code == 401


def test_a_download_link_stops_when_old_or_when_the_account_signs_out_everywhere(monkeypatch):
    owner = account()
    artifact = result_of(owner)
    url = login_client(owner).post(f'/api/v1/artifacts/{artifact.id}/link', {}, content_type='application/json').json()['url']
    from django.test import Client
    later = timezone.now().timestamp() + 301
    monkeypatch.setattr(signing.time, 'time', lambda: later)
    assert Client().get(url).status_code == 401
    monkeypatch.undo()
    owner.auth_version += 1
    owner.save(update_fields=['auth_version'])
    assert Client().get(url).status_code == 401


def test_no_link_for_someone_elses_result_or_a_file_that_is_gone():
    owner = account()
    artifact = result_of(owner)
    stranger = login_client(account(44))
    assert stranger.post(f'/api/v1/artifacts/{artifact.id}/link', {}, content_type='application/json').status_code == 404
    artifact.file.expires_at = timezone.now() - timedelta(minutes=1)
    artifact.file.save(update_fields=['expires_at'])
    answer = login_client(owner).post(f'/api/v1/artifacts/{artifact.id}/link', {}, content_type='application/json')
    assert answer.status_code == 410 and answer.json()['error']['code'] == 'file_expired'


def test_a_link_signed_with_another_salt_is_not_a_download_link():
    owner = account()
    artifact = result_of(owner)
    forged = signing.dumps({'artifact': str(artifact.id), 'account': str(owner.id), 'auth': owner.auth_version}, salt='other')
    from django.test import Client
    assert Client().get(f'/api/v1/artifacts/{artifact.id}/download?link={forged}').status_code == 401
    assert LINK_SALT != 'other'
