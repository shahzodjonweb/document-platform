"""Handing a Telegram draft's files to the web app.

Generation runs in the chat now, so the remaining hand-offs are `/editor`,
which opens a PDF for editing, and the studio link on the describe-your-document
screen for anyone who prefers the fuller web form. Whatever the customer has already sent
to the chat must travel with them, or they upload the same document twice. The
web side reads these `file_id` parameters; this pins the bot's half.
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


def test_the_editor_opens_the_document_already_in_the_chat(customer):
    inputs = [f'00000000-0000-4000-8000-{i:012d}' for i in range(1, 8)]
    BotDraft.objects.create(account=customer, feature_id='pdf.merge', input_ids=inputs)

    # Editing a PDF is a canvas and stays on the web; it opens one document.
    assert linked_files(customer, 'editor') == inputs[:1]
    assert urlsplit(workspace_link(customer, 'editor')).path == '/en/app/editor'

    # /web is the home page, not a tool; it carries nothing.
    assert linked_files(customer, 'web') == []


def test_an_empty_draft_links_to_a_clean_workspace(customer):
    BotDraft.objects.create(account=customer, feature_id='pdf.merge', input_ids=[])
    assert linked_files(customer, 'editor') == []
    assert workspace_link(customer, 'editor').endswith('/en/app/editor')


def test_the_studio_link_on_the_examples_screen_still_carries_the_files(customer):
    """Generation now runs in the chat, but the richer web form is one tap away
    and must not ask for the same upload twice.

    The link sits on the screen that asks for the description — the two services
    are offered directly now, so there is no menu of two for it to sit beside.
    """
    inputs = [f'00000000-0000-4000-8000-{i:012d}' for i in range(1, 8)]
    BotDraft.objects.create(account=customer, feature_id='pdf.merge', input_ids=inputs)
    result = dispatch_local(customer, text='/examples')
    link = next(button['url'] for message in result['messages']
                for row in message['buttons'] for button in row if button.get('url'))
    # Generation accepts at most five sources, so a longer file-tool draft is
    # truncated rather than producing a link that fails on arrival.
    assert parse_qs(urlsplit(link).query)['file_id'] == inputs[:5]
    assert urlsplit(link).path == '/en/app/create'
