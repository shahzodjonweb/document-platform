"""Handing a Telegram draft's files to the web app.

`/create`, `/study`, `/school`, `/teach` and `/editor` open the web workspace.
Whatever the customer has already sent to the chat must travel with them, or
they upload the same document twice. The web side reads these `file_id`
parameters; this pins the half the bot is responsible for.
"""
from urllib.parse import parse_qs, urlsplit

import pytest
from django.utils import timezone

from apps.core.identity import resolve_account
from apps.core.models import BotConversation, BotDraft
from operations.integrations import save_config
from telegram.local import dispatch_local

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    save_config('telegram', {'token': '', 'username': 'fixture_bot', 'webapp_url': 'https://pdfmaster.example/en/app'})
    account = resolve_account({'id': 980311, 'first_name': 'Handoff test'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en',
                                   language_selected_at=timezone.now())
    return account


def workspace_link(customer, command):
    result = dispatch_local(customer, text=f'/{command}')
    for message in reversed(result['messages']):
        for row in message['buttons']:
            for button in row:
                if button.get('url'):
                    return button['url']
    raise AssertionError(f'/{command} offered no link to the web app')


def linked_files(customer, command):
    return parse_qs(urlsplit(workspace_link(customer, command)).query).get('file_id', [])


def test_the_draft_files_travel_to_the_web_workspace(customer):
    inputs = [f'00000000-0000-4000-8000-{i:012d}' for i in range(1, 8)]
    BotDraft.objects.create(account=customer, feature_id='pdf.merge', input_ids=inputs)

    # Generation refuses more than five sources, so send what it can accept
    # rather than a link that fails once the customer is already there.
    assert linked_files(customer, 'create') == inputs[:5]
    for command in ('study', 'school', 'teach'):
        assert linked_files(customer, command) == inputs[:5], command

    # The editor opens exactly one document.
    assert linked_files(customer, 'editor') == inputs[:1]

    # /web is the home page, not a tool; it carries nothing.
    assert linked_files(customer, 'web') == []
    assert urlsplit(workspace_link(customer, 'study')).path == '/en/app/study'


def test_an_empty_draft_links_to_a_clean_workspace(customer):
    BotDraft.objects.create(account=customer, feature_id='pdf.merge', input_ids=[])
    assert linked_files(customer, 'create') == []
    assert workspace_link(customer, 'create').endswith('/en/app/create')
