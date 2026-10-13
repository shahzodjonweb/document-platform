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
def test_no_bot_error_sends_people_to_a_balance_that_no_longer_exists(locale):
    """Plans are weekly limits now; an already-paid invoice points to the plan."""
    for words in COPY[locale].values():
        assert not any(word in words.lower() for word in ('balance', 'balans', 'баланс', 'credit', 'kredit', 'кредит'))
    paid = bot_error(DomainError('invoice_already_paid'), locale)
    assert {'en': 'Subscription', 'uz': 'Obuna', 'ru': 'Подписка'}[locale] in paid
