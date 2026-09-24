"""Recovery messages remain localized without exposing exception details."""
import pytest

from apps.core.errors import DomainError, error_data
from telegram.errors import COPY, bot_error
from telegram.ux_copy import UX


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_common_recovery_messages_are_localized_and_never_include_private_params(locale):
    secret = 'private-file-password-and-payment-reference'
    codes = ['invalid_pages', 'invalid_parameters', 'bot_transport_limit',
             'quote_expired', 'challenge_expired', 'quota_exceeded', 'password_required']
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
