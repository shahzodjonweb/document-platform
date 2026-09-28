"""A failed AI task retries through the same priced, owner-bound bot review."""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.errors import DomainError
from apps.core.models import BotCallback, BotConversation, Job, Quote
from apps.studio import checkpoints
from apps.studio.domain import update_draft
from apps.studio.models import GenerationDraft
from telegram import generation
from telegram.local import dispatch_local
from telegram.ux_copy import UX
from tests.test_bot_generation import body, buttons, customer, describe, tap

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


def action_token(result, action):
    for button in reversed(buttons(result)):
        token = button.get('callback_data')
        if token and BotCallback.objects.filter(pk=token, action=action).exists():
            return token
    raise AssertionError(f'Missing callback action {action}')


@pytest.fixture
def failed(customer, settings):
    settings.LOCAL_SYNC_JOBS = False
    review = describe(customer, 'A one page introduction to tidal energy.')
    tap(customer, review, 'Generate')
    job = Job.objects.get(account=customer)
    Job.objects.filter(pk=job.pk).update(status='failed', error_code='provider_failed')
    job.refresh_from_db()
    listing = dispatch_local(customer, text='/myfiles')
    status = dispatch_local(customer, callback_data=action_token(listing, 'job'))
    return customer, job, status, action_token(status, 'ai_retry')


def test_failed_generation_offers_retry_then_confirmation_without_new_form(failed):
    customer, previous, status, token = failed
    assert any(button['label'] == UX['en']['retry_task'] for button in buttons(status))
    review = dispatch_local(customer, callback_data=token)
    assert 'Pages: 1' in body(review) and UX['en']['review_title'] in body(review)
    assert action_token(review, 'ai_run')
    assert Job.objects.count() == 1, 'showing a retry quote must not run or charge'
    quote = Quote.objects.latest('created_at')
    assert quote.parameters[checkpoints.ROOT_FIELD] == str(previous.pk)
    assert quote.parameters[checkpoints.RETRY_FIELD] == str(previous.pk)
    assert BotConversation.objects.get(pk=customer.telegram_user_id).state == ''


def test_retry_and_generate_replays_make_one_quote_and_one_recovery_job(failed):
    customer, previous, _, token = failed
    first = dispatch_local(customer, callback_data=token)
    second = dispatch_local(customer, callback_data=token)
    assert Quote.objects.count() == 2
    control1 = BotCallback.objects.get(pk=action_token(first, 'ai_run'))
    control2 = BotCallback.objects.get(pk=action_token(second, 'ai_run'))
    assert control1.payload['quote_id'] == control2.payload['quote_id']
    dispatch_local(customer, callback_data=control1.pk)
    dispatch_local(customer, callback_data=control2.pk)
    dispatch_local(customer, callback_data=token)
    assert Quote.objects.count() == 2 and Job.objects.count() == 2
    retried = Job.objects.exclude(pk=previous.pk).get()
    assert retried.origin_channel == 'bot'
    assert retried.parameters[checkpoints.ROOT_FIELD] == str(previous.pk)


def test_bot_retry_keeps_completed_provider_result_in_same_checkpoint_chain(failed):
    customer, previous, _, token = failed
    draft = GenerationDraft.objects.get(pk=previous.parameters['generation_draft_id'])
    calls = []
    def invoke():
        calls.append('provider')
        return {'sections': [{'id': 's1', 'body': 'Kept completed text.'}]}, {'input_tokens': 100, 'output_tokens': 20}
    def validate(result):
        assert result['sections'][0]['id'] == 's1'
    arguments = dict(draft=draft, body={'model': 'same', 'input': 'same'}, stage='generate', span=(0, 1), invoke=invoke, validate=validate)
    original, _ = checkpoints.call(job=previous, **arguments)
    review = dispatch_local(customer, callback_data=token)
    dispatch_local(customer, callback_data=action_token(review, 'ai_run'))
    retried = Job.objects.exclude(pk=previous.pk).get()
    reused, usage = checkpoints.call(job=retried, **arguments)
    assert reused == original and usage['checkpoint_reused'] is True
    assert calls == ['provider']


def test_foreign_callback_owner_and_foreign_failed_job_cannot_retry(failed):
    from apps.core.identity import resolve_account
    customer, previous, _, token = failed
    other = resolve_account({'id': 980412, 'first_name': 'Other customer'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=other.telegram_user_id, locale='en', language_selected_at=timezone.now())
    dispatch_local(other, callback_data=token)
    assert Quote.objects.count() == 1 and Job.objects.count() == 1
    forged = BotCallback.objects.create(token='foreign-job-retry', account=other, action='ai_retry',
                                        payload={'job_id': str(previous.pk)}, expires_at=timezone.now() + timedelta(minutes=10))
    dispatch_local(other, callback_data=forged.pk)
    assert Quote.objects.count() == 1 and Job.objects.count() == 1


@pytest.mark.parametrize('stale', ['callback', 'draft', 'edited', 'not_failed'])
def test_stale_retry_controls_cannot_create_work(failed, stale):
    customer, previous, _, token = failed
    draft = GenerationDraft.objects.get(pk=previous.parameters['generation_draft_id'])
    if stale == 'callback':
        BotCallback.objects.filter(pk=token).update(expires_at=timezone.now() - timedelta(seconds=1))
    elif stale == 'draft':
        GenerationDraft.objects.filter(pk=draft.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    elif stale == 'edited':
        update_draft(customer, draft.id, {'version': draft.version, 'title': 'Changed after failure'})
    else:
        Job.objects.filter(pk=previous.pk).update(status='succeeded')
    dispatch_local(customer, callback_data=token)
    assert Quote.objects.count() == 1 and Job.objects.count() == 1


def test_edited_draft_invalidates_already_prepared_retry_confirmation(failed):
    customer, previous, _, token = failed
    review = dispatch_local(customer, callback_data=token)
    run = action_token(review, 'ai_run')
    draft = GenerationDraft.objects.get(pk=previous.parameters['generation_draft_id'])
    update_draft(customer, draft.id, {'version': draft.version, 'title': 'Changed after retry review'})
    dispatch_local(customer, callback_data=run)
    assert Job.objects.count() == 1
    with pytest.raises(DomainError, match='version_conflict'):
        generation.retry(customer, token)


def test_retry_label_uses_customers_language(failed):
    customer, _, _, _ = failed
    for locale in ('en', 'uz', 'ru'):
        customer.locale = locale
        customer.save(update_fields=['locale'])
        BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
        listing = dispatch_local(customer, text='/myfiles')
        status = dispatch_local(customer, callback_data=action_token(listing, 'job'))
        assert any(button['label'] == UX[locale]['retry_task'] for button in buttons(status))
