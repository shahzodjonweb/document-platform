"""The redesigned admin: Today, the support inbox, customer search and the audit table."""
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models import Account, Job, Quote, SupportTicket
from operations.models import AuditLog
from operations.views import audit_changes
from tests.test_operations import staff_client

pytestmark = pytest.mark.django_db


def failed_job(account):
    quote = Quote.objects.create(account=account, feature_id='pdf.merge', parameters={}, input_ids=[], meters={},
                                 policy={'plan': 'free'}, expires_at=timezone.now() + timedelta(hours=1))
    return Job.objects.create(account=account, quote=quote, feature_id='pdf.merge', parameters={}, input_ids=[],
                              meters={}, policy={'plan': 'free'}, idempotency_key=uuid.uuid4().hex,
                              request_hash=uuid.uuid4().hex, status='failed')


def ticket(account, status='open', subject='Cannot download'):
    return SupportTicket.objects.create(account=account, subject=subject, message='The file will not open.',
                                        category='processing', status=status)


def test_today_is_the_landing_page_and_shows_what_is_waiting():
    client, _ = staff_client()
    account = Account.objects.create(telegram_user_id=81001, display_name='Malika')
    ticket(account)
    failed_job(account)

    assert client.get('/ops/').url == '/ops/today'
    response = client.get('/ops/today?lang=en')
    assert response.status_code == 200
    page = response.content.decode()
    assert 'Support questions open' in page and 'Card payments to review' in page
    cards = {card['key']: card['count'] for card in response.context['actions']}
    assert cards['support'] == 1 and cards['failed'] == 1
    stats = {stat['key']: stat['value'] for stat in response.context['stats']}
    assert stats['new_users'] == 1 and stats['tasks'] == 1
    # Open support cases show as a count beside Support in the sidebar.
    support = next(item for group in response.context['nav'] for item in group['items'] if item['path'] == 'support')
    assert support['badge'] == 1


def test_today_shows_each_role_only_the_cards_it_can_open():
    client, _ = staff_client('Analyst')
    response = client.get('/ops/today')
    assert response.status_code == 200
    assert response.context['actions'] == []
    assert not response.context['recent_jobs']
    keys = {stat['key'] for stat in response.context['stats']}
    assert 'received' in keys
    support, _ = staff_client('Support')
    keys = {stat['key'] for stat in support.get('/ops/today').context['stats']}
    assert 'received' not in keys, "so'm totals are for Finance and Analysts"


def test_support_inbox_opens_on_open_cases_whenever_they_arrived():
    client, _ = staff_client('Support')
    account = Account.objects.create(telegram_user_id=81002)
    old = ticket(account, subject='An old question')
    SupportTicket.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=200))
    ticket(account, status='resolved', subject='Already answered')

    page = client.get('/ops/support').content.decode()
    assert 'An old question' in page and 'Already answered' not in page
    resolved = client.get('/ops/support?status=resolved').content.decode()
    assert 'Already answered' in resolved and 'An old question' not in resolved
    everything = client.get('/ops/support?status=all').content.decode()
    assert 'Already answered' in everything and 'An old question' in everything


def test_support_conversation_reply_waits_for_the_customer():
    client, _ = staff_client('Support')
    case = ticket(Account.objects.create(telegram_user_id=81003))
    page = client.get(f'/ops/support/{case.id}').content.decode()
    assert 'The file will not open.' in page and 'name="reply"' in page
    assert client.post(f'/ops/support/{case.id}', {'reply': 'Please try again now.', 'status': 'reply'}).status_code == 302
    case.refresh_from_db()
    assert case.status == 'waiting_customer'
    assert 'Please try again now.' in client.get(f'/ops/support/{case.id}').content.decode()


def test_customer_search_reaches_accounts_older_than_the_report_period():
    client, _ = staff_client('Support')
    old = Account.objects.create(telegram_user_id=81004, display_name='Javlonbek', username='javlon')
    Account.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=400))

    assert 'Javlonbek' not in client.get('/ops/users').content.decode()
    for query in ('Javlon', '@javlon', '81004'):
        assert 'Javlonbek' in client.get('/ops/users', {'q': query}).content.decode(), query


def test_customer_page_offers_plan_and_credit_dialogs_to_administrators_only():
    account = Account.objects.create(telegram_user_id=81005, display_name='Sardor')
    admin, _ = staff_client()
    page = admin.get(f'/ops/users/{account.id}').content.decode()
    assert 'id="assign-plan"' in page and 'id="grant"' in page
    support, _ = staff_client('Support')
    page = support.get(f'/ops/users/{account.id}').content.decode()
    assert 'id="assign-plan"' not in page and 'id="grant"' not in page


def test_audit_table_shows_what_changed():
    assert audit_changes({'status': 'open', 'same': 1}, {'status': 'resolved', 'same': 1}) == [
        {'key': 'status', 'before': 'open', 'after': 'resolved'}]
    assert audit_changes({}, {'plan': 'plus'}) == [{'key': 'plan', 'before': None, 'after': 'plus'}]
    assert audit_changes(None, 'not a dict') == []
    client, user = staff_client()
    AuditLog.objects.create(actor=user, action='plan.limits', target='plus', reason='Changed Plus plan limits',
                            before={'ai_credits': 100}, after={'ai_credits': 200})
    page = client.get('/ops/audit').content.decode()
    assert '<del>100</del>' in page and '<ins>200</ins>' in page


def test_customer_page_lists_their_payments_for_finance_and_their_cases_for_support():
    from apps.commerce.models import ManualPayment
    account = Account.objects.create(telegram_user_id=81006, display_name='Kamola')
    case = ticket(account, subject='Where is my plan?')
    transfer = ManualPayment.objects.create(account=account, plan='plus', amount=60000, currency='UZS',
                                            reference='PM-TEST1', expires_at=timezone.now() + timedelta(hours=1))
    admin, _ = staff_client()
    page = admin.get(f'/ops/users/{account.id}').content.decode()
    assert f'/ops/payments/manual/{transfer.id}' in page and f'/ops/support/{case.id}' in page
    support, _ = staff_client('Support')
    page = support.get(f'/ops/users/{account.id}').content.decode()
    assert f'/ops/support/{case.id}' in page
    assert f'/ops/payments/manual/{transfer.id}' not in page, 'card transfers are for Finance'


def test_users_can_be_sorted():
    client, _ = staff_client('Support')
    Account.objects.create(telegram_user_id=81007, display_name='Zarina')
    Account.objects.create(telegram_user_id=81008, display_name='Aziz')
    by_name = client.get('/ops/users', {'sort': 'name'}).content.decode()
    assert by_name.index('Aziz') < by_name.index('Zarina')
    oldest = [row.display_name for row in client.get('/ops/users', {'sort': 'old'}).context['pagination']]
    assert oldest == ['Zarina', 'Aziz']
    assert client.get('/ops/users', {'sort': 'nonsense'}).status_code == 200
