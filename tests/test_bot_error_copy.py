"""Recovery messages remain localized without exposing exception details."""
import pytest

from apps.core.errors import DomainError, error_data
from telegram.errors import COPY, bot_error
from telegram.ux_copy import UX


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_common_recovery_messages_are_localized_and_never_include_private_params(locale):
    secret = 'private-file-password-and-payment-reference'
    codes = ['invalid_pages', 'invalid_parameters', 'bot_transport_limit',
             'quote_expired', 'challenge_expired', 'password_required']
    for code in codes:
        value = bot_error(DomainError(code, params={'password': secret, 'detail': secret}), locale)
        assert value == COPY[locale][code]
        assert secret not in value and code not in value
        assert len(value) < 260
        if locale != 'en':
            assert value != bot_error(DomainError(code), 'en')
    assert bot_error(DomainError('bot_wrong_file'), locale) == UX[locale]['wrong_file']


def test_unknown_locale_and_error_code_have_safe_plain_language_fallbacks():
    error = DomainError('future_provider_failure', params={'token': 'never-show-this'})
    for locale in ('en', 'uz', 'ru'):
        value = bot_error(error, locale)
        assert value == '⚠️ ' + error_data(error, locale)['message']
        assert error.code not in value and 'never-show-this' not in value
    assert bot_error(DomainError('password_required'), 'xx') == COPY['en']['password_required']


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_used_up_limit_says_how_many_when_it_comes_back_and_offers_plans(locale):
    from types import SimpleNamespace
    reader = SimpleNamespace(time_zone='Asia/Tashkent')
    week = DomainError('weekly_ai_limit', 429, {'limit': 5, 'used': 5, 'resets_at': '2026-10-18T19:00:00+00:00'})
    value = bot_error(week, locale, reader)
    assert '5' in value and '2026-10-19 00:00 UTC+5' in value, 'Monday 00:00 in Tashkent, on the reader\'s clock'
    assert value != bot_error(week, 'en', reader) or locale == 'en'
    assert 'Monday' in bot_error(week, 'en') or locale != 'en', 'with no reader, the week is named'
    files = bot_error(DomainError('weekly_file_limit', 429, {'limit': 15, 'used': 15, 'requested': 1,
                                                             'resets_at': '2026-10-18T19:00:00+00:00'}), locale, reader)
    assert '15' in files and 'UTC+5' in files
    edits = bot_error(DomainError('edit_limit', 429, {'limit': 3, 'used': 3}), locale)
    assert '3' in edits and '{' not in edits
    for value in (bot_error(week, locale, reader), files, edits):
        assert len(value) < 260
    # Params that are not numbers never reach the message.
    forged = bot_error(DomainError('edit_limit', 429, {'limit': '<b>secret</b>', 'used': 3}), locale)
    assert 'secret' not in forged and forged == '⚠️ ' + error_data(DomainError('edit_limit'), locale)['message']


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_no_bot_error_sends_people_to_a_balance_or_a_checkout_that_no_longer_exists(locale):
    """Plans are weekly limits now, paid by card transfer: there is no balance
    to top up and no Stars invoice to verify, expire or renew."""
    for words in COPY[locale].values():
        assert not any(word in words.lower() for word in ('balance', 'balans', 'баланс', 'credit', 'kredit', 'кредит',
                                                           'stars', 'invoice', 'hisob-faktura'))
    # Nor to a renewal switch: a card plan has none, so nothing raises manual_subscription_not_renewable.
    for code in ('invalid_invoice', 'invoice_expired', 'invoice_already_paid', 'renewal_disabled',
                 'subscription_not_active', 'invalid_plan_change', 'offer_version_conflict',
                 'manual_subscription_not_renewable'):
        assert code not in COPY[locale], code
    # What a card transfer can still refuse keeps its words.
    for code in ('checkout_disabled', 'invalid_plan', 'manual_payment_pending'):
        assert bot_error(DomainError(code), locale) == COPY[locale][code]


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_sizes_pages_and_tools_never_send_people_to_another_plan(locale):
    """Every plan has the same sizes, page counts and tools (owner's decision,
    2026-10-16): only the weekly limits are a reason to change plan. A file too
    large used to say "choose another plan", which no plan would have fixed."""
    plan_words = ('plan', 'tarif', 'тариф')
    for code in ('file_too_large', 'file_size_limit', 'page_limit_exceeded', 'page_limit', 'feature_not_in_plan',
                 'aggregate_size_exceeded', 'input_count_exceeded', 'concurrency_limit', 'output_size_limit'):
        value = bot_error(DomainError(code), locale)
        assert value == COPY[locale][code].replace('{limit}', '1 000')
        assert not any(word in value.lower() for word in plan_words), (code, value)
    # A tool held back reads like one switched off: there is no plan to buy it with.
    assert bot_error(DomainError('feature_not_in_plan'), locale) == bot_error(DomainError('feature_unavailable'), locale)
    # The weekly limits are the one place a plan is still offered.
    for code in ('weekly_ai_limit', 'weekly_file_limit', 'edit_limit'):
        assert any(word in COPY[locale][code].lower() for word in plan_words), code


@pytest.mark.parametrize('code,offered', [('feature_not_in_plan', False), ('page_limit_exceeded', False),
                                          ('weekly_ai_limit', True), ('weekly_file_limit', True), ('edit_limit', True)])
def test_only_a_used_up_weekly_allowance_puts_the_plans_under_an_error(monkeypatch, code, offered):
    """A tool refused for the plan reads "not available right now"; a plans
    button under it would sell what no plan adds."""
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import telegram.bot as bot

    async def button(account, label, action, payload=None):
        return label
    monkeypatch.setattr(bot, 'button', button)
    monkeypatch.setattr(bot, 'InlineKeyboardMarkup', lambda inline_keyboard: inline_keyboard)
    message = SimpleNamespace(from_user=SimpleNamespace(is_bot=False), edit_text=AsyncMock(), answer=AsyncMock())
    asyncio.run(bot.safe_error(message, SimpleNamespace(locale='en', telegram_user_id=1), DomainError(code)))
    rows = message.answer.await_args.kwargs['reply_markup']
    assert (['plans'] in rows) is offered
    assert ['continue_task', 'home'] in rows


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_api_names_no_plan_for_a_limit_every_plan_shares(locale):
    """The web shows these messages as the API sends them. "Your plan's size
    limit" pointed at a plan that would have been no larger."""
    plan_words = ('plan', 'tarif', 'тариф', 'план')
    for code in ('file_too_large', 'page_limit_exceeded', 'saved_limit'):
        message = error_data(DomainError(code), locale)['message']
        assert message and not any(word in message.lower() for word in plan_words), (code, message)
    # The weekly allowances still point at the plans.
    assert any(word in error_data(DomainError('weekly_ai_limit'), locale)['message'].lower() for word in plan_words)


# ---------------------------------------------------------------- pages: one file, or a task's files together

UPLOAD = {'en': '📄 This file has more than {limit} pages. Split it into smaller files before you upload it.',
          'uz': '📄 Bu faylda {limit} sahifadan ko‘p. Yuklashdan oldin uni kichikroq fayllarga bo‘lib oling.',
          'ru': '📄 В этом файле больше {limit} страниц. Перед загрузкой разделите его на файлы поменьше.'}
TOTAL = {'en': '📄 Too many pages for one task. Remove a file or choose fewer pages.',
         'uz': '📄 Bitta vazifa uchun sahifalar juda ko‘p. Bitta faylni olib tashlang yoki kamroq sahifa tanlang.',
         'ru': '📄 Слишком много страниц для одной задачи. Уберите файл или выберите меньше страниц.'}


def _refused_upload(account, pages):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from apps.core.services import upload_file
    from tests.test_platform import pdf_bytes
    with pytest.raises(DomainError) as refused:
        upload_file(account, SimpleUploadedFile('long.pdf', pdf_bytes((72,) * pages), 'application/pdf'))
    return refused.value


@pytest.mark.django_db
@pytest.mark.parametrize('plan', ['free', 'premium'])
def test_a_file_too_long_for_any_task_is_told_to_be_split_before_upload(plan):
    """No tool takes a file over the cap, our Split PDF included: it is split
    before uploading, and the message names the real figure."""
    from processors.engine import MAX_PAGES
    from telegram.ux_copy import TOOL_NAMES
    from tests.test_platform import account
    customer = account(78100)
    customer.plan = plan
    customer.save(update_fields=['plan'])
    error = _refused_upload(customer, MAX_PAGES + 1)
    assert (error.code, error.params) == ('page_limit', {'limit': 1000})
    for locale in ('en', 'uz', 'ru'):
        told = bot_error(error, locale, customer)
        assert told == UPLOAD[locale].format(limit='1 000'), told
        assert TOOL_NAMES['pdf.split'][locale] not in told
        assert error_data(error, locale)['message'] == UPLOAD[locale].format(limit='1 000')[2:]
        assert told != bot_error(DomainError('page_limit_exceeded'), locale)


@pytest.mark.django_db
def test_the_upload_refusal_names_the_cap_the_panel_set():
    from operations import plans as plan_settings
    from tests.test_platform import account
    plan_settings.save('premium', {'max_pages_per_job': '5'})
    error = _refused_upload(account(78101), 6)
    assert (error.code, error.params) == ('page_limit', {'limit': 5})
    assert bot_error(error, 'en') == UPLOAD['en'].format(limit='5')
    # A stored job's code carries no figure: it is the one in force.
    assert bot_error(DomainError('page_limit'), 'ru') == UPLOAD['ru'].format(limit='5')


@pytest.mark.django_db
def test_a_task_over_the_cap_is_told_to_drop_a_file_or_pages_not_to_split():
    from apps.core.services import create_quote
    from operations import plans as plan_settings
    from tests.test_platform import account, upload
    customer = account(78102)
    first, second = upload(customer, widths=(72,) * 3), upload(customer, widths=(72,) * 3)
    plan_settings.save('free', {'max_pages_per_job': '5'})
    with pytest.raises(DomainError) as refused:
        create_quote(customer, 'pdf.merge', [str(first.id), str(second.id)], {})
    assert refused.value.code == 'page_limit_exceeded'
    for locale in ('en', 'uz', 'ru'):
        assert bot_error(refused.value, locale) == TOTAL[locale]
        assert error_data(refused.value, locale)['message'] == TOTAL[locale][2:]


@pytest.mark.django_db
def test_a_pdf_with_no_pages_is_unreadable_not_too_long():
    from tests.test_platform import account
    error = _refused_upload(account(78103), 0)
    assert error.code == 'invalid_pdf'
