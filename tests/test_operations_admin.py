"""Administrative control: plans, weekly limits and customer documents.

Every capability here changes something a customer paid for or can read, so
each one is reason-gated, role-gated and written to the audit trail. These
tests are mostly about those three properties rather than the happy path.
"""
import io
import re
from datetime import timedelta, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import Client
from django.utils import timezone
from pypdf import PdfWriter

from apps.core.allowance import week_bounds
from apps.core.models import Account, FileAsset, Job, Quote, UsageGrant
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

    response = client.post(f'/ops/users/{account.id}/plan', {'plan': 'premium', 'days': '30'})
    assert response.status_code == 302
    account.refresh_from_db()
    assert account.staff_plan == 'premium' and account.plan == 'premium'
    assert account.staff_plan_expires_at > timezone.now()
    entry = AuditLog.objects.get(action='account.plan_assign')
    assert entry.actor == user and entry.reason == 'Assigned a plan'
    assert entry.before['effective'] == 'free' and entry.after['effective'] == 'premium'

    client.post(f'/ops/users/{account.id}/plan', {'plan': ''})
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


def test_assigning_a_plan_needs_a_real_plan_and_a_sane_duration(settings):
    settings.DEBUG = True
    client, _ = staff_client()
    account = customer()
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


# --- this week -------------------------------------------------------------

def file_task(account, status='succeeded'):
    quote = Quote.objects.create(account=account, feature_id='pdf.merge', expires_at=timezone.now())
    return Job.objects.create(account=account, quote=quote, feature_id='pdf.merge', status=status,
                              idempotency_key=str(quote.id), request_hash='x')


def test_the_account_page_shows_this_week_instead_of_a_balance(settings):
    settings.DEBUG = True
    client, _ = staff_client()
    account = customer()
    file_task(account), file_task(account), file_task(account, 'failed')
    page = client.get(f'/ops/users/{account.id}').content.decode()
    assert 'Left this week' in page and 'File tasks a week' in page
    assert '<strong>13 / 15</strong>' in page, 'two tasks counted; the failed one gave its place back'
    assert '<strong>5 / 5</strong>' in page and 'AI edits per file' in page
    # Monday 00:00 in Tashkent, shown in the viewer's zone (UTC here): Sunday 19:00.
    resets = week_bounds()[1].astimezone(dt_timezone.utc)
    assert resets.weekday() == 6 and f'New week: {resets:%d %b %Y} · 19:00</p>' in page
    assert 'id="grant"' not in page and 'data-grant' not in page, 'there is no balance to top up'


def test_an_unlimited_limit_shows_what_was_used(settings):
    settings.DEBUG = True
    client, _ = staff_client()
    account = customer()
    client.post(f'/ops/users/{account.id}/plan', {'plan': 'premium'})
    file_task(account)
    page = client.get(f'/ops/users/{account.id}').content.decode()
    assert 'No limit · 1 used' in page and 'No limit · 0 used' in page
    assert '/ 15' not in page


def test_a_task_page_has_no_charges_to_show(settings):
    settings.DEBUG = True
    client, _ = staff_client('Operations')
    job = file_task(customer())
    page = client.get(f'/ops/jobs/{job.id}').content.decode()
    assert 'pdf.merge' in page and 'Allowance ledger' not in page


def test_the_old_grant_route_is_gone(settings):
    """Support helps a customer who ran out by assigning a plan; nothing writes credits."""
    settings.DEBUG = True
    import uuid
    client, _ = staff_client()
    account = customer()
    body = {'idempotency_key': str(uuid.uuid4()), 'ai_credits': '500'}
    assert client.post(f'/ops/users/{account.id}/grants', body).status_code == 404
    assert not UsageGrant.objects.exists() and not AuditLog.objects.filter(action='quota.grant').exists()


# --- customer documents ----------------------------------------------------

def test_staff_can_open_a_customer_document_and_it_is_recorded(settings):
    settings.DEBUG = True
    client, user = staff_client('Support')
    account = customer()
    asset = upload_file(account, SimpleUploadedFile('contract.pdf', pdf_bytes(), 'application/pdf'))

    listing = client.get(f'/ops/users/{account.id}').content.decode()
    assert 'contract.pdf' in listing, 'the account page lists what the customer has'

    response = client.get(f'/ops/files/{asset.id}/download')
    assert response.status_code == 200
    assert b''.join(response.streaming_content).startswith(b'%PDF-')
    entry = AuditLog.objects.get(action='file.download')
    assert entry.actor == user and entry.target == str(asset.id)
    assert entry.after['account'] == str(account.id) and entry.after['name'] == 'contract.pdf'
    assert entry.reason == 'Opened a customer document'
    assert 'file-reason' not in listing, 'no reason is asked for'


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


def test_the_jobs_page_no_longer_speaks_of_charges():
    from operations.i18n import CATALOGS
    assert CATALOGS['en']['job_desc'] == 'Inspect task state without opening private files.'
    for locale, word in (('en', 'charge'), ('uz', 'sarf'), ('ru', 'списан')):
        assert word not in CATALOGS[locale]['job_desc'].lower(), locale


# --- editing plan limits ---------------------------------------------------

def test_editing_a_plan_changes_what_it_allows(settings):
    settings.DEBUG = True
    client, user = staff_client('Finance')
    before = limits_for_plan('plus')['max_generated_pdf_pages']

    response = client.post('/ops/plans/plus', {'max_generated_pdf_pages': str(before + 5),
                                               'reason': 'Raising the page ceiling for Plus.'})
    assert response.status_code == 302
    assert limits_for_plan('plus')['max_generated_pdf_pages'] == before + 5
    entry = AuditLog.objects.get(action='plan.limits', target='plus')
    assert entry.actor == user and entry.before['max_generated_pdf_pages'] == before
    # The page ceiling is every plan's: one audit row for each plan it changed.
    others = AuditLog.objects.filter(action='plan.limits').exclude(target='plus')
    assert sorted(others.values_list('target', flat=True)) == ['free', 'premium']
    assert all(row.actor == user and 'from the Plus plan' in row.reason
               and row.after == {'max_generated_pdf_pages': before + 5} for row in others)
    assert limits_for_plan('free')['max_generated_pdf_pages'] == limits_for_plan('premium')['max_generated_pdf_pages'] == before + 5

    # And an account on that plan sees the new ceiling immediately.
    account = customer(770002)
    account.plan = 'plus'
    from apps.core.policy import plan_limits
    from apps.commerce.services import refresh_account_entitlement  # noqa: F401
    account.staff_plan = 'plus'
    account.save(update_fields=['plan', 'staff_plan'])
    assert plan_limits(account)['max_generated_pdf_pages'] == before + 5


def test_the_plans_page_edits_the_weekly_limits(settings):
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    for lang, group in (('en', 'Weekly limits'), ('uz', 'Haftalik limitlar'), ('ru', 'Недельные лимиты')):
        page = client.get(f'/ops/plans?lang={lang}').content.decode()
        assert group in page, lang
        for field in ('weekly_ai_documents', 'weekly_file_jobs', 'edits_per_file'):
            assert f'name="{field}"' in page, (lang, field)
        for retired in ('file_tasks', 'file_page_units', 'ai_credits', 'daily_ai_documents'):
            assert f'name="{retired}"' not in page, (lang, retired)
    from operations.templatetags.ops_ui import money
    page = client.get('/ops/plans?lang=en').content.decode()
    assert all(f'plan-price">{money(price)} <span>' in page for price in (20_000, 60_000)), 'the owner\'s prices'


def test_the_plan_form_marks_the_limits_every_plan_shares(settings):
    """Saving a shared field from one plan's form changes all three, so the form says so beside them."""
    from operations import plans as plan_settings
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    for lang, note in (('en', 'Applies to every plan'), ('uz', 'Barcha tariflarga qo‘llanadi'),
                       ('ru', 'Применяется ко всем тарифам')):
        page = client.get(f'/ops/plans?lang={lang}').content.decode()
        fieldsets = [part.split('</fieldset>')[0] for part in page.split('<fieldset')[1:]]
        assert len(fieldsets) == 15, 'five groups on each of the three plans'
        for fieldset in fieldsets:
            names = set(re.findall(r'name="(\w+)"', fieldset))
            assert (note in fieldset) == (names <= set(plan_settings.SHARED)), (lang, names)
        assert all(f'name="{field}"' not in fieldset for fieldset in fieldsets if note in fieldset
                   for field in plan_settings.PER_PLAN)


def test_a_plan_edit_is_bounded_and_reversible(settings):
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    seed = limits_for_plan('plus')['max_generated_pdf_pages']

    assert client.post('/ops/plans/plus', {'max_generated_pdf_pages': '0',
                                           'reason': 'Zero would break the plan.'}).status_code == 400
    assert client.post('/ops/plans/plus', {'max_generated_pdf_pages': 'lots',
                                           'reason': 'Not a number at all.'}).status_code == 400
    assert client.post('/ops/plans/nonexistent', {'weekly_ai_documents': '10',
                                                  'reason': 'No such plan exists.'}).status_code == 400
    assert limits_for_plan('plus')['max_generated_pdf_pages'] == seed

    client.post('/ops/plans/plus', {'max_generated_pdf_pages': str(seed + 1), 'reason': 'A real change.'})
    assert limits_for_plan('plus')['max_generated_pdf_pages'] == seed + 1
    client.post('/ops/plans/plus', {'reset': '1', 'reason': 'Putting it back.'})
    assert all(limits_for_plan(plan)['max_generated_pdf_pages'] == seed for plan in ('free', 'plus', 'premium'))
    assert AuditLog.objects.get(action='plan.reset').target == 'plus'
    restored = AuditLog.objects.filter(action='plan.limits', reason__startswith='Restored')
    assert sorted(restored.values_list('target', flat=True)) == ['free', 'premium']


def test_free_cannot_be_raised_above_a_paid_plan(settings):
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    assert client.post('/ops/plans/free', {'weekly_ai_documents': '999',
                                           'reason': 'That would make paying pointless.'}).status_code == 400
    assert limits_for_plan('free')['weekly_ai_documents'] == 5
    # Plus lowered in the panel is the Plus Free is held under, not the seed's.
    client.post('/ops/plans/plus', {'weekly_ai_documents': '8'})
    assert client.post('/ops/plans/free', {'weekly_ai_documents': '9'}).status_code == 400
    assert client.post('/ops/plans/free', {'weekly_ai_documents': '8'}).status_code == 302


def test_a_weekly_limit_left_blank_means_unlimited(settings):
    """File tasks are unlimited on Plus; staff can cap them and lift the cap again."""
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    assert limits_for_plan('plus')['weekly_file_jobs'] is None

    assert client.post('/ops/plans/plus', {'weekly_file_jobs': '40',
                                           'reason': 'Capping Plus while we investigate abuse.'}).status_code == 302
    assert limits_for_plan('plus')['weekly_file_jobs'] == 40

    assert client.post('/ops/plans/plus', {'weekly_file_jobs': '',
                                           'reason': 'Lifting the cap again.'}).status_code == 302
    assert limits_for_plan('plus')['weekly_file_jobs'] is None


def test_the_free_plan_keeps_both_weekly_limits(settings):
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    for field, before in (('weekly_ai_documents', 5), ('weekly_file_jobs', 15)):
        assert client.post('/ops/plans/free', {field: '',
                                               'reason': 'That would be unlimited free use.'}).status_code == 400
        assert limits_for_plan('free')[field] == before
    # And a field that is not nullable still needs a value.
    assert client.post('/ops/plans/free', {'max_file_mib': '',
                                           'reason': 'Blank is not a file size.'}).status_code == 400


def test_the_free_plan_keeps_a_limit_on_ai_edits(settings):
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    response = client.post('/ops/plans/free', {'edits_per_file': '', 'reason': 'That would be unlimited AI edits.'})
    assert response.status_code == 400 and 'edits per file' in response.content.decode()
    assert limits_for_plan('free')['edits_per_file'] == 3


def test_a_paid_plan_cannot_be_set_below_free_and_free_stays_editable(settings):
    """Plus at 2 documents and 1 edit would give paying customers less than Free;
    and the whole Free form must still save when only its file size changes."""
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    response = client.post('/ops/plans/plus', {'weekly_ai_documents': '2', 'edits_per_file': '1'})
    assert response.status_code == 400 and 'below the free plan' in response.content.decode()
    assert (limits_for_plan('plus')['weekly_ai_documents'], limits_for_plan('plus')['edits_per_file']) == (20, 10)
    free = limits_for_plan('free')
    form = {field: '' if free[field] is None else str(free[field]) for field in ('weekly_ai_documents', 'weekly_file_jobs',
            'edits_per_file', 'max_file_mib', 'max_pages_per_job', 'max_generated_pdf_pages', 'max_deck_images')}
    assert client.post('/ops/plans/free', {**form, 'max_file_mib': '30'}).status_code == 302
    assert limits_for_plan('free')['max_file_mib'] == 30


def test_every_seeded_form_saves_and_free_may_raise_a_shared_ceiling_first(settings):
    """Free and Plus carry Premium's caps now. Each plan's form saved as it stands
    must go through, and a page ceiling raised from Free's form is every plan's."""
    from operations import plans as plan_settings
    settings.DEBUG = True
    client, _ = staff_client('Finance')
    for plan in ('free', 'plus', 'premium'):
        limits = limits_for_plan(plan)
        form = {field: '' if limits[field] is None else str(limits[field]) for field in plan_settings.FIELDS}
        assert client.post(f'/ops/plans/{plan}', form).status_code == 302, plan
    assert not AuditLog.objects.filter(action='plan.limits').exists(), 'an unchanged form changes nothing'
    assert client.post('/ops/plans/free', {'max_generated_pdf_pages': '40'}).status_code == 302
    assert [limits_for_plan(plan)['max_generated_pdf_pages'] for plan in ('free', 'plus', 'premium')] == [40, 40, 40]
    assert AuditLog.objects.filter(action='plan.limits').count() == 3


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
    assert client.post('/ops/plans/plus', {'weekly_ai_documents': '1', 'reason': 'Not my role.'}).status_code == 403
    assert limits_for_plan('plus')['weekly_ai_documents'] == 20


def test_a_broken_override_never_takes_pricing_offline(settings):
    """A bad stored value must fall back to the seed, not raise."""
    settings.DEBUG = True
    IntegrationConfig.objects.update_or_create(pk='plan_limits', defaults={'configuration': 'not-a-dict'})
    assert limits_for_plan('premium')['price_uzs'] == 60_000


def test_no_admin_form_asks_staff_for_a_reason():
    """Every action is audited on its own (who, what, when, before → after);
    staff are not asked to explain themselves in a text box."""
    from django.conf import settings
    templates = (settings.BASE_DIR / 'operations' / 'templates' / 'ops').glob('*.html')
    asking = [path.name for path in templates if 'name="reason"' in path.read_text() or 'file-reason' in path.read_text()]
    assert asking == []
