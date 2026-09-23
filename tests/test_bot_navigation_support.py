"""Commerce confirmations and Telegram UI transport contracts."""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram import Bot, Dispatcher, F
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from django.utils import timezone

from apps.commerce.models import LocalBotMessage
from apps.core.identity import resolve_account
from apps.core.models import BotCallback, BotConversation
from telegram.billing import COPY
from telegram.local import LocalTelegramSession, dispatch_local

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 980001, 'first_name': 'Navigation test'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='en', language_selected_at=timezone.now())
    return account


def action_token(result, action):
    for message in reversed(result['messages']):
        for row in message['buttons']:
            for button in row:
                token = button.get('callback_data')
                if token and BotCallback.objects.filter(pk=token, action=action).exists():
                    return token
    raise AssertionError(f'No button for {action}')


def purchase(customer):
    result = dispatch_local(customer, text='/buy plus')
    dispatch_local(customer, callback_data=action_token(result, 'commerce_pay'))
    customer.refresh_from_db()
    return customer.subscription


def test_native_menu_has_global_navigation_and_default_fallback():
    from telegram.commands import COMMANDS, install_commands
    bot = Mock(set_my_commands=AsyncMock(), set_chat_menu_button=AsyncMock())
    asyncio.run(install_commands(bot))
    assert [call.kwargs['language_code'] for call in bot.set_my_commands.await_args_list] == ['', 'en', 'uz', 'ru']
    assert set(COMMANDS['en']) == set(COMMANDS['uz']) == set(COMMANDS['ru'])
    assert {'start', 'help', 'settings', 'language', 'cancel', 'web', 'account'} <= set(COMMANDS['en'])
    assert all(1 <= len(label) <= 256 for commands in COMMANDS.values() for label in commands.values())
    assert bot.set_chat_menu_button.await_args.kwargs['menu_button'].type == 'commands'


def test_selected_language_menu_is_chat_scoped_and_safe_offline(customer):
    from telegram.commands import COMMANDS, install_chat_commands
    bot = Mock(set_my_commands=AsyncMock())
    assert asyncio.run(install_chat_commands(bot, customer.telegram_user_id, 'uz'))
    call = bot.set_my_commands.await_args
    assert call.kwargs['scope'].type == 'chat'
    assert call.kwargs['scope'].chat_id == customer.telegram_user_id
    assert call.kwargs['language_code'] == ''
    assert call.args[0][0].description == COMMANDS['uz']['start']
    async def run():
        session = LocalTelegramSession(customer)
        local = Bot('123456:LOCAL_SIMULATOR_NO_NETWORK', session=session)
        try:
            assert await install_chat_commands(local, customer.telegram_user_id, 'ru')
        finally:
            await session.close()
    asyncio.run(run())
    assert not LocalBotMessage.objects.filter(account=customer).exists()


def test_native_menu_provider_failure_does_not_block_onboarding():
    from aiogram.exceptions import TelegramNetworkError
    from aiogram.methods import SetMyCommands
    from telegram.commands import install_chat_commands
    bot = Mock(set_my_commands=AsyncMock(side_effect=TelegramNetworkError(method=SetMyCommands(commands=[]), message='Network unavailable')))
    assert asyncio.run(install_chat_commands(bot, 980003, 'en')) is False


def test_localized_offer_review_has_price_balance_and_safe_navigation(customer):
    customer.locale = 'uz'; customer.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale='uz')
    result = dispatch_local(customer, text='/buy')
    buttons = result['messages'][-1]['buttons']
    assert any('Qo‘shimcha fayl vazifalari' in b['label'] for row in buttons for b in row)
    assert all('tasks100' not in b['label'] and 'ai100' not in b['label'] for row in buttons for b in row)
    result = dispatch_local(customer, text='/buy tasks100')
    text = result['messages'][-1]['text']
    assert '25 Telegram Stars' in text and 'Fayl vazifalari: 100' in text and 'Sahifa birliklari: 1,000' in text
    assert COPY['uz']['sandbox'] in text
    assert action_token(result, 'plans') and action_token(result, 'home')


def test_billing_navigation_leaves_old_support_or_parameter_prompt(customer):
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(state='support', prompt={'payment': False})
    dispatch_local(customer, text='/buy')
    conversation = BotConversation.objects.get(pk=customer.telegram_user_id)
    assert conversation.state == '' and conversation.prompt == {}


def test_renewal_button_requires_confirmation_and_is_owner_scoped(customer):
    sub = purchase(customer)
    result = dispatch_local(customer, text='/subscription')
    result = dispatch_local(customer, callback_data=action_token(result, 'commerce_cancel'))
    confirm = action_token(result, 'commerce_renewal_confirm')
    sub.refresh_from_db(); assert sub.renewal_enabled
    other = resolve_account({'id': 980002, 'first_name': 'Other'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=other.telegram_user_id, locale='en', language_selected_at=timezone.now())
    dispatch_local(other, callback_data=confirm)
    sub.refresh_from_db(); assert sub.renewal_enabled
    dispatch_local(customer, callback_data=confirm)
    sub.refresh_from_db(); assert not sub.renewal_enabled
    result = dispatch_local(customer, text='/resumerenewal')
    sub.refresh_from_db(); assert not sub.renewal_enabled
    dispatch_local(customer, callback_data=action_token(result, 'commerce_renewal_confirm'))
    sub.refresh_from_db(); assert sub.renewal_enabled


def test_plan_change_command_explains_and_confirms_before_mutating(customer):
    sub = purchase(customer)
    result = dispatch_local(customer, text='/changeplan premium')
    assert 'separate checkout' in result['messages'][-1]['text']
    sub.refresh_from_db(); assert sub.scheduled_plan == '' and sub.renewal_enabled
    dispatch_local(customer, callback_data=action_token(result, 'commerce_plan_confirm'))
    sub.refresh_from_db(); assert sub.scheduled_plan == 'premium' and not sub.renewal_enabled


def test_expired_confirmation_cannot_change_subscription(customer):
    sub = purchase(customer)
    result = dispatch_local(customer, text='/cancelrenewal')
    token = action_token(result, 'commerce_renewal_confirm')
    BotCallback.objects.filter(pk=token).update(expires_at=timezone.now())
    dispatch_local(customer, callback_data=token)
    sub.refresh_from_db(); assert sub.renewal_enabled


def test_invoice_callback_is_acknowledged_before_provider_work(customer, monkeypatch):
    from aiogram.methods import AnswerCallbackQuery
    from apps.commerce import services
    events = []
    original_request = LocalTelegramSession.make_request
    original_present = services.present_invoice
    async def tracked_request(self, bot, method, timeout=None):
        if isinstance(method, AnswerCallbackQuery):
            events.append('ack')
        return await original_request(self, bot, method, timeout)
    def present(invoice):
        assert events == ['ack']
        events.append('provider')
        return original_present(invoice)
    monkeypatch.setattr(LocalTelegramSession, 'make_request', tracked_request)
    monkeypatch.setattr(services, 'present_invoice', present)
    result = dispatch_local(customer, text='/buy')
    dispatch_local(customer, callback_data=action_token(result, 'commerce_offer'))
    assert events == ['ack', 'provider']


def test_simulator_supports_keyboard_types_and_edits_existing_message(customer):
    async def run():
        session = LocalTelegramSession(customer)
        bot = Bot('123456:LOCAL_SIMULATOR_NO_NETWORK', session=session)
        try:
            reply = await bot.send_message(customer.telegram_user_id, 'Choose', reply_markup=ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text='Main menu')]]))
            await bot.send_message(customer.telegram_user_id, 'Removed', reply_markup=ReplyKeyboardRemove(remove_keyboard=True))
            inline = await bot.send_message(customer.telegram_user_id, 'Old', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Old', callback_data='example')]]))
            await bot.edit_message_text(chat_id=customer.telegram_user_id, message_id=inline.message_id, text='Updated')
            await bot.edit_message_reply_markup(chat_id=customer.telegram_user_id, message_id=inline.message_id, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Back', callback_data='back')]]))
            return reply.message_id, inline.message_id
        finally:
            await session.close()
    reply_id, inline_id = asyncio.run(run())
    assert LocalBotMessage.objects.filter(account=customer).count() == 3
    assert LocalBotMessage.objects.get(telegram_message_id=reply_id).buttons == [[{'label': 'Main menu', 'text': 'Main menu', 'callback_data': None, 'url': None}]]
    message = LocalBotMessage.objects.get(telegram_message_id=inline_id)
    assert message.text == 'Updated' and message.buttons[0][0]['callback_data'] == 'back'


def test_simulated_callback_targets_its_original_message_across_sessions(customer, monkeypatch):
    dispatcher = Dispatcher()
    @dispatcher.message()
    async def start(message):
        await message.answer('Original', reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Edit', callback_data='edit-example')]]))
    @dispatcher.callback_query(F.data == 'edit-example')
    async def edit(query):
        await query.answer()
        await query.message.edit_text('Changed in place')
    monkeypatch.setattr('telegram.bot.build_dispatcher', lambda: dispatcher)
    first = dispatch_local(customer, text='Open')
    first_message = first['messages'][-1]['id']
    result = dispatch_local(customer, callback_data='edit-example')
    outbound = [m for m in result['messages'] if m['direction'] == 'outbound']
    assert len(outbound) == 1 and outbound[0]['id'] == first_message
    assert outbound[0]['text'] == 'Changed in place'
    dispatch_local(customer, text='Another')
    identifiers = list(LocalBotMessage.objects.filter(direction='outbound').values_list('telegram_message_id', flat=True))
    assert len(identifiers) == len(set(identifiers))
