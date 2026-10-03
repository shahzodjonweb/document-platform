"""Free accounts join the owner's Telegram channels before using a service."""
import json
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core import channel_gate
from apps.core.errors import DomainError
from apps.core.models import ChannelMembership
from operations.integrations import channel_gate_config, parse_channels, save_config
from tests.test_platform import account, login_client, quote, upload

pytestmark = pytest.mark.django_db


class Telegram:
    """A stand-in Bot API: `statuses` maps chat → the customer's member status."""

    def __init__(self, statuses=None, fail=False):
        self.statuses, self.fail, self.calls = statuses or {}, fail, []

    def __call__(self, method, params, token):
        self.calls.append((method, params['chat_id']))
        if self.fail:
            return False, 'unavailable'
        if method == 'getChat':
            return True, {'title': f"Title of {params['chat_id']}", 'type': 'channel'}
        status = self.statuses.get(params['chat_id'], 'left')
        return True, {'status': status, 'is_member': status == 'restricted'}


@pytest.fixture
def telegram(monkeypatch):
    fake = Telegram()
    monkeypatch.setattr(channel_gate, '_call', fake)
    monkeypatch.setattr(channel_gate, '_token', lambda: '123456:TOKEN')
    return fake


def require_channels(lines='@pdfmaster_news', enabled=True):
    save_config('channels', {'channels': lines, 'enabled': 'true' if enabled else 'false'})


# ---------------------------------------------------------------- settings


def test_channels_are_written_the_way_people_copy_them():
    parsed = parse_channels('@pdfmaster_news\nhttps://t.me/pdfmaster_tips\n\n'
                            'https://t.me/+AbCdEf12345 -1001234567890\n-1009876543210 https://t.me/joinchat/XyZ12345678\n@PDFMASTER_NEWS')
    assert parsed == [
        {'chat': '@pdfmaster_news', 'url': 'https://t.me/pdfmaster_news'},
        {'chat': '@pdfmaster_tips', 'url': 'https://t.me/pdfmaster_tips'},
        {'chat': '-1001234567890', 'url': 'https://t.me/+AbCdEf12345'},
        {'chat': '-1009876543210', 'url': 'https://t.me/joinchat/XyZ12345678'},
    ], 'the same channel twice is kept once'


@pytest.mark.parametrize('line', ['pdfmaster', 'https://t.me/+AbCdEf12345', 'http://t.me/name', 'https://evil.example/name',
                                  '@ab', 'https://t.me/joinchat', '-1001234567890', '@name extra'])
def test_a_line_that_is_not_a_channel_is_refused(line):
    with pytest.raises(DomainError, match='invalid_channel'):
        parse_channels(line)


def test_at_most_five_channels():
    with pytest.raises(DomainError, match='too_many_channels'):
        parse_channels('\n'.join(f'@channel_{n}' for n in range(6)))


def test_switching_on_needs_a_channel():
    with pytest.raises(DomainError, match='channels_not_configured'):
        save_config('channels', {'channels': '', 'enabled': 'true'})


# ---------------------------------------------------------------- who is asked


def test_nobody_is_asked_while_it_is_off_or_empty(telegram):
    customer = account()
    assert channel_gate.status(customer) == {'required': False, 'joined': True, 'channels': []}
    require_channels(enabled=False)
    assert channel_gate.status(customer)['required'] is False
    assert telegram.calls == []


def test_a_paid_plan_is_never_asked(telegram, settings):
    from apps.core.models import Account
    require_channels()
    customer = account()
    Account.objects.filter(pk=customer.pk).update(staff_plan='premium')
    customer.refresh_from_db()
    assert channel_gate.status(customer)['required'] is False and telegram.calls == []


def test_a_free_account_that_has_not_joined_cannot_start_a_task(telegram):
    require_channels('@pdfmaster_news\n@pdfmaster_tips')
    telegram.statuses = {'@pdfmaster_news': 'member'}
    customer = account()
    asset = upload(customer)
    with pytest.raises(DomainError) as refused:
        quote(customer, asset)
    assert refused.value.code == 'channels_required' and refused.value.status == 403
    assert refused.value.params['channels'] == [
        {'title': 'pdfmaster_news', 'url': 'https://t.me/pdfmaster_news', 'joined': True},
        {'title': 'pdfmaster_tips', 'url': 'https://t.me/pdfmaster_tips', 'joined': False}]


def test_after_joining_every_channel_the_task_goes_ahead(telegram):
    require_channels()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    customer = account()
    assert quote(customer, upload(customer)).feature_id == 'pdf.rotate'


@pytest.mark.parametrize('status,joined', [('creator', True), ('administrator', True), ('member', True),
                                           ('restricted', True), ('left', False), ('kicked', False)])
def test_every_telegram_member_status_is_read_correctly(telegram, status, joined):
    require_channels()
    telegram.statuses = {'@pdfmaster_news': status}
    assert channel_gate.status(account())['joined'] is joined


def test_a_job_cannot_start_without_joining_but_a_retry_of_one_that_did_is_fine(telegram):
    from apps.core.services import submit_job
    require_channels()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    customer = account()
    pending = quote(customer, upload(customer))
    job, _ = submit_job(customer, pending.id, 'channel-request-1')
    ChannelMembership.objects.all().delete()
    telegram.statuses = {}
    again, created = submit_job(customer, pending.id, 'channel-request-1')
    assert again.pk == job.pk and not created, 'the retry is the same job, not a new service'
    with pytest.raises(DomainError, match='channels_required'):
        submit_job(customer, pending.id, 'channel-request-2')


def test_ai_documents_need_the_channels_too(telegram, settings):
    from apps.studio.domain import DOCUMENT, create_draft, generation_quote
    settings.ENABLE_BETA_TOOLS = True
    settings.DEBUG = True  # local authoring stands in for the AI provider
    require_channels()
    customer = account()
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'prompt': 'A two page note on tides.'})
    with pytest.raises(DomainError, match='channels_required'):
        generation_quote(customer, draft.id, draft.version)


# ---------------------------------------------------------------- asking Telegram


def test_a_member_is_remembered_for_hours_and_a_non_member_for_a_minute(telegram):
    require_channels()
    customer = account()
    channel_gate.status(customer)
    channel_gate.status(customer)
    assert len(telegram.calls) == 1, 'a fresh answer is reused'
    row = ChannelMembership.objects.get()
    assert row.is_member is False and row.expires_at - row.checked_at == timedelta(seconds=channel_gate.NOT_MEMBER_SECONDS)
    telegram.statuses = {'@pdfmaster_news': 'member'}
    assert channel_gate.status(customer, refresh=True)['joined'] is True, "\"I've joined\" asks again at once"
    row.refresh_from_db()
    assert row.expires_at - row.checked_at == timedelta(hours=channel_gate.MEMBER_HOURS)


def test_when_telegram_cannot_answer_the_customer_is_let_through(telegram):
    require_channels()
    telegram.fail = True
    customer = account()
    assert channel_gate.status(customer)['joined'] is True
    row = ChannelMembership.objects.get()
    assert row.expires_at - row.checked_at == timedelta(seconds=channel_gate.UNKNOWN_SECONDS)


def test_leaving_the_channel_is_noticed_once_the_answer_is_old(telegram):
    require_channels()
    telegram.statuses = {'@pdfmaster_news': 'member'}
    customer = account()
    assert channel_gate.status(customer)['joined']
    telegram.statuses = {}
    ChannelMembership.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert not channel_gate.status(customer)['joined']


# ---------------------------------------------------------------- API


def test_the_api_says_what_to_join_and_refuses_a_task_with_the_same_list(telegram):
    require_channels()
    customer = account()
    client = login_client(customer)
    state = client.get('/api/v1/channels').json()
    assert state['required'] and not state['joined'] and state['channels'][0]['url'] == 'https://t.me/pdfmaster_news'
    asset = upload(customer)
    refused = client.post('/api/v1/quotes', json.dumps({'feature_id': 'pdf.rotate', 'input_ids': [str(asset.id)], 'parameters': {'angle': 90}}),
                          content_type='application/json')
    error = refused.json()['error']
    assert refused.status_code == 403 and error['code'] == 'channels_required'
    assert error['message_params']['channels'][0]['title'] == 'pdfmaster_news'
    assert 'Telegram' in error['message']
    telegram.statuses = {'@pdfmaster_news': 'member'}
    assert client.post('/api/v1/channels/check').json()['joined'] is True


# ---------------------------------------------------------------- admin


def test_the_check_tells_the_owner_which_channel_needs_the_bot_as_admin(monkeypatch):
    from apps.core import channel_gate as gate
    from operations.integrations import test_channels
    monkeypatch.setattr('operations.integrations.telegram_config', lambda: {'token': '777:BOT'})
    require_channels('@good_channel\n@bad_channel')
    results = {'@good_channel': {'ok': True, 'title': 'Good News', 'reason': ''},
               '@bad_channel': {'ok': False, 'title': 'Bad', 'reason': 'bot_not_admin'}}
    monkeypatch.setattr(gate, 'inspect', lambda chat, bot_id, token: results[chat])
    with pytest.raises(DomainError, match='channels_bot_not_admin'):
        test_channels()
    channels = {c['chat']: c for c in channel_gate_config()['channels']}
    assert channels['@good_channel']['title'] == 'Good News' and channels['@good_channel']['check']['ok'] is True
    assert channels['@bad_channel']['check']['ok'] is False


def test_inspect_needs_the_bot_to_be_an_admin_of_a_channel(monkeypatch):
    replies = {('getChat', '@c'): (True, {'title': 'C', 'type': 'channel'}),
               ('getChat', '@g'): (True, {'title': 'G', 'type': 'supergroup'})}
    def fake(method, params, token):
        if method == 'getChat':
            return replies[(method, params['chat_id'])]
        return True, {'status': 'member'}
    monkeypatch.setattr(channel_gate, '_call', fake)
    assert channel_gate.inspect('@c', 1, 'T')['ok'] is False, 'a channel hides its members from a mere member'
    assert channel_gate.inspect('@g', 1, 'T')['ok'] is True, 'a group shows them to any member'


def test_only_administrators_set_the_channels():
    from tests.test_manual_payments import staff_client
    for role in ('Finance', 'Support'):
        client, _ = staff_client(role)
        client.post('/ops/integrations', {'integration': 'channels', 'channels': '@pdfmaster_news', 'enabled': 'true',
                                          'reason': 'Require the channel'})
        assert channel_gate_config()['ready'] is False, role
    client, _ = staff_client('Administrator')
    response = client.post('/ops/integrations', {'integration': 'channels', 'channels': '@pdfmaster_news',
                                                 'enabled': 'true', 'reason': 'Require the news channel'})
    assert response.status_code == 302 and channel_gate_config()['ready']
    assert 'channel-settings' in client.get('/ops/integrations').content.decode()
