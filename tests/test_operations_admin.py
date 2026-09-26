"""Administrative control: plans, allowances and customer documents.

Every capability here changes something a customer paid for or can read, so
each one is reason-gated, role-gated and written to the audit trail. These
tests are mostly about those three properties rather than the happy path.
"""
import io
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import Client
from django.utils import timezone
from pypdf import PdfWriter

from apps.core.models import Account, FileAsset, UsageGrant
from apps.core.policy import limits_for_plan
from apps.core.services import upload_file
from operations.auth import COOKIE, begin_session
from operations.models import AuditLog, IntegrationConfig

pytestmark = pytest.mark.django_db


def staff_client(role='Administrator'):
    user = get_user_model().objects.create_user(
        username=f'admin-{role.lower().replace(" ", "-")}', password='long-staff-password', is_staff=True)
    user.groups.add(Group.objects.get_or_create(name=role)[0])
    client = Client()
    client.cookies[COOKIE] = begin_session(HttpResponse(), user).cookies[COOKIE].value
    return client, user


def customer(uid=770001):
    return Account.objects.create(telegram_user_id=uid, display_name='Customer')


def pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# --- assigning a plan ------------------------------------------------------

def test_staff_can_assign_and_remove_a_plan(settings):
    settings.DEBUG = True
    client, user = staff_client()
    account = customer()
    assert account.plan == 'free'

    response = client.post(f'/ops/users/{account.id}/plan',
                           {'plan': 'premium', 'days': '30', 'reason': 'Comped for a support incident.'})
    assert response.status_code == 302
    account.refresh_from_db()
    assert account.staff_plan == 'premium' and account.plan == 'premium'
    assert account.staff_plan_expires_at > timezone.now()
    entry = AuditLog.objects.get(action='account.plan_assign')
    assert entry.actor == user and 'support incident' in entry.reason
    assert entry.before['effective'] == 'free' and entry.after['effective'] == 'premium'

    client.post(f'/ops/users/{account.id}/plan', {'plan': '', 'reason': 'Incident closed, reverting.'})
    account.refresh_from_db()
    assert account.staff_plan == '' and account.plan == 'free'
    assert AuditLog.objects.filter(action='account.plan_clear').exists()


def test_an_assigned_plan_lapses_on_its_own(settings):
    settings.DEBUG = True
    client, _ = staff_client()
    account = customer()
    client.post(f'/ops/users/{account.id}/plan', {'plan': 'plus', 'days': '1', 'reason': 'Trial for a week.'})
    account.refresh_from_db()
    assert account.plan == 'plus'

    Account.objects.filter(pk=account.pk).update(staff_plan_expires_at=timezone.now() - timedelta(seconds=1))
    account.refresh_from_db()
    from apps.commerce.services import refresh_account_entitlement
    assert refresh_account_entitlement(account) == 'free', 'the assignment expires without anyone acting'


def test_assigning_a_plan_needs_a_reason_and_a_real_plan(settings):
    settings.DEBUG = True
    client, _ = staff_client()
    account = customer()
    assert client.post(f'/ops/users/{account.id}/plan', {'plan': 'premium', 'reason': 'no'}).status_code == 400
    assert client.post(f'/ops/users/{account.id}/plan',
                       {'plan': 'unlimited', 'reason': 'Trying an unknown plan.'}).status_code == 400
    assert client.post(f'/ops/users/{account.id}/plan',
                       {'plan': 'plus', 'days': '9999', 'reason': 'Far too long.'}).status_code == 400
    account.refresh_from_db()
    assert account.staff_plan == '' and not AuditLog.objects.filter(action__startswith='account.plan').exists()


def test_an_assignment_is_not_a_payment(settings):
    """It must never reach revenue reporting or invent a subscription."""
    settings.DEBUG = True
    from apps.commerce.models import Payment, Subscription, SubscriptionPeriod
    client, _ = staff_client()
    account = customer()
    client.post(f'/ops/users/{account.id}/plan', {'plan': 'premium', 'reason': 'Comped for review.'})
    assert not Payment.objects.exists()
    assert not Subscription.objects.exists()
    assert not SubscriptionPeriod.objects.exists()


# --- granting allowance ----------------------------------------------------

def test_the_account_page_shows_balances_before_a_grant(settings):
    settings.DEBUG = True
    client, _ = staff_client()
    account = customer()
    page = client.get(f'/ops/users/{account.id}').content.decode()
    assert 'Remaining now' in page, 'the current balance is shown beside the field'
    assert 'data-grant-input' in page and 'data-grant-preset' in page


def test_a_grant_is_idempotent_and_audited(settings):
    settings.DEBUG = True
    import uuid
    client, _ = staff_client()
    account = customer()
    key = str(uuid.uuid4())
    body = {'idempotency_key': key, 'ai_credits': '500', 'reason': 'Goodwill after an outage.'}
    assert client.post(f'/ops/users/{account.id}/grants', body).status_code == 302
    assert client.post(f'/ops/users/{account.id}/grants', body).status_code == 302
    assert UsageGrant.objects.filter(account=account, meter='ai_credits').count() == 1
    assert AuditLog.objects.filter(action='quota.grant').count() == 1


# --- customer documents ----------------------------------------------------

def test_staff_can_open_a_customer_document_and_it_is_recorded(settings):
    settings.DEBUG = True
    client, user = staff_client('Support')
    account = customer()
    asset = upload_file(account, SimpleUploadedFile('contract.pdf', pdf_bytes(), 'application/pdf'))

    listing = client.get(f'/ops/users/{account.id}').content.decode()
    assert 'contract.pdf' in listing, 'the account page lists what the customer has'

    response = client.get(f'/ops/files/{asset.id}/download', {'reason': 'Investigating a reported bad export.'})
    assert response.status_code == 200
    assert b''.join(response.streaming_content).startswith(b'%PDF-')
    entry = AuditLog.objects.get(action='file.download')
    assert entry.actor == user and entry.target == str(asset.id)
    assert entry.after['account'] == str(account.id) and entry.after['name'] == 'contract.pdf'
    assert 'reported bad export' in entry.reason


def test_a_document_cannot_be_opened_without_a_reason(settings):
    settings.DEBUG = True
    client, _ = staff_client('Support')
    account = customer()
    asset = upload_file(account, SimpleUploadedFile('private.pdf', pdf_bytes(), 'application/pdf'))
    assert client.get(f'/ops/files/{asset.id}/download').status_code == 400
    assert client.get(f'/ops/files/{asset.id}/download', {'reason': 'why'}).status_code == 400
    assert not AuditLog.objects.filter(action='file.download').exists()


def test_an_expired_document_is_not_served(settings):
    settings.DEBUG = True
    client, _ = staff_client('Support')
    account = customer()
    asset = upload_file(account, SimpleUploadedFile('old.pdf', pdf_bytes(), 'application/pdf'))
    FileAsset.objects.filter(pk=asset.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.get(f'/ops/files/{asset.id}/download', {'reason': 'Checking an old report.'}).status_code == 400


def test_an_analyst_cannot_reach_customer_documents(settings):
    settings.DEBUG = True
    client, _ = staff_client('Analyst')
    account = customer()
    asset = upload_file(account, SimpleUploadedFile('private.pdf', pdf_bytes(), 'application/pdf'))
    assert client.get(f'/ops/files/{asset.id}/download', {'reason': 'Curiosity is not a reason.'}).status_code == 403
    assert not AuditLog.objects.filter(action='file.download').exists()


def test_the_panel_no_longer_claims_documents_are_unreachable(settings):
    """The copy has to match what the panel actually does."""
    from operations.i18n import CATALOGS
    for locale, labels in CATALOGS.items():
        assert 'No document download permission' not in labels['private_note'], locale
        assert 'not accessible' not in labels['no_private'], locale


# --- editing plan limits ---------------------------------------------------

def test_editing_a_plan_changes_what_it_allows(settings):
    settings.DEBUG = True
    client, user = staff_client('Finance')
    before = limits_for_plan('plus')['max_generated_pdf_pages']

    response = client.post('/ops/plans/plus', {'max_generated_pdf_pages': str(before + 5),
                                               'reason': 'Raising the page ceiling for Plus.'})
    assert response.status_code == 302
    assert limits_for_plan('plus')['max_generated_pdf_pages'] == before + 5
    entry = AuditLog.objects.get(action='plan.limits')
    assert entry.actor == user and entry.target == 'plus'
    assert entry.before['max_generated_pdf_pages'] == before

    # And an account on that plan sees the new ceiling immediately.
    account = customer(770002)
    account.plan = 'plus'
    from apps.core.policy import plan_limits
    from apps.commerce.services import refresh_account_entitlement  # noqa: F401
    account.staff_plan = 'plus'
    account.save(update_fields=['plan', 'staff_plan'])
    assert plan_limits(account)['max_generated_pdf_pages'] == before + 5


def test_a_plan_edit_is_bounded_and_reversible(settings):
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    seed = limits_for_plan('plus')['max_generated_pdf_pages']

    assert client.post('/ops/plans/plus', {'max_generated_pdf_pages': '0',
                                           'reason': 'Zero would break the plan.'}).status_code == 400
    assert client.post('/ops/plans/plus', {'max_generated_pdf_pages': 'lots',
                                           'reason': 'Not a number at all.'}).status_code == 400
    assert client.post('/ops/plans/nonexistent', {'ai_credits': '10',
                                                  'reason': 'No such plan exists.'}).status_code == 400
    assert limits_for_plan('plus')['max_generated_pdf_pages'] == seed

    client.post('/ops/plans/plus', {'max_generated_pdf_pages': str(seed + 1), 'reason': 'A real change.'})
    assert limits_for_plan('plus')['max_generated_pdf_pages'] == seed + 1
    client.post('/ops/plans/plus', {'reset': '1', 'reason': 'Putting it back.'})
    assert limits_for_plan('plus')['max_generated_pdf_pages'] == seed
    assert AuditLog.objects.filter(action='plan.reset').exists()


def test_free_cannot_be_raised_above_every_paid_plan(settings):
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    assert client.post('/ops/plans/free', {'ai_credits': '999999',
                                           'reason': 'That would make paying pointless.'}).status_code == 400
    assert limits_for_plan('free')['ai_credits'] < limits_for_plan('premium')['ai_credits']


def test_a_plan_field_that_means_no_limit_can_be_left_blank(settings):
    """`daily_file_tasks` is null on paid plans and that means no daily cap."""
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    assert limits_for_plan('plus')['daily_file_tasks'] is None

    assert client.post('/ops/plans/plus', {'daily_file_tasks': '40',
                                           'reason': 'Capping Plus while we investigate abuse.'}).status_code == 302
    assert limits_for_plan('plus')['daily_file_tasks'] == 40

    assert client.post('/ops/plans/plus', {'daily_file_tasks': '',
                                           'reason': 'Lifting the cap again.'}).status_code == 302
    assert limits_for_plan('plus')['daily_file_tasks'] is None


def test_the_free_plan_cannot_have_its_daily_cap_removed(settings):
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    before = limits_for_plan('free')['daily_file_tasks']
    assert client.post('/ops/plans/free', {'daily_file_tasks': '',
                                           'reason': 'That would be unlimited free processing.'}).status_code == 400
    assert limits_for_plan('free')['daily_file_tasks'] == before
    # And a field that is not nullable still needs a value.
    assert client.post('/ops/plans/free', {'ai_credits': '',
                                           'reason': 'Blank is not a credit allowance.'}).status_code == 400


def test_an_edit_reaches_the_customer_pricing_page(settings):
    """What the platform enforces and what it advertises must be the same."""
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    client.post('/ops/plans/premium', {'max_generated_slides': '77',
                                       'reason': 'Raising the Premium slide ceiling.'})
    published = Client().get('/api/v1/plans').json()['plans']
    premium = next(row for row in published if row['id'] == 'premium')
    assert premium['limits']['max_generated_slides'] == 77


def test_a_support_agent_cannot_edit_plan_limits(settings):
    settings.DEBUG = True
    client, _ = staff_client('Support')
    before = limits_for_plan('plus')['ai_credits']
    assert client.post('/ops/plans/plus', {'ai_credits': '1', 'reason': 'Not my role.'}).status_code == 403
    assert limits_for_plan('plus')['ai_credits'] == before


def test_a_broken_override_never_takes_pricing_offline(settings):
    """A bad stored value must fall back to the seed, not raise."""
    settings.DEBUG = True
    IntegrationConfig.objects.update_or_create(pk='plan_limits', defaults={'configuration': 'not-a-dict'})
    assert limits_for_plan('premium')['ai_credits'] > 0
