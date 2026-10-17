"""The plans screen says what each plan gives before it asks anyone to pay."""
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from apps.core.allowance import WEEK_ZONE
from apps.core.identity import resolve_account
from apps.core.models import Account, BotConversation
from operations import plans as plan_settings
from operations.models import IntegrationConfig
from telegram.billing import PLAN_COPY
from telegram.clock import day_label
from telegram.local import dispatch_local
from tests.test_manual_payments import configure

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]


@pytest.fixture
def customer(settings):
    settings.DEBUG = True
    settings.COMMERCE_SANDBOX_ENABLED = True
    account = resolve_account({'id': 984001, 'first_name': 'Chooser'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=account.telegram_user_id, locale='uz', language_selected_at=timezone.now())
    Account.objects.filter(pk=account.pk).update(locale='uz')
    account.refresh_from_db()
    return account


def screen(account):
    return dispatch_local(account, text='/plans')['messages'][-1]['text']


def discount(plan='plus', price=15_000, days=14):
    """A discount on `plan` as the admin enters it: the price, and its last day
    `days` from today in Tashkent. Returns that day, 'YYYY-MM-DD'."""
    until = (datetime.now(WEEK_ZONE).date() + timedelta(days=days)).isoformat()
    plan_settings.save(plan, {'discount_price_uzs': price, 'discount_until': until})
    return until


def ended_discount(plan='plus', price=15_000, until='2020-01-31'):
    """A discount whose last day has passed, left in the panel.

    The panel refuses a past date, so one can only be stored while still
    live; this writes it as it then stands.
    """
    row, _ = IntegrationConfig.objects.get_or_create(pk=plan_settings.KEY, defaults={'configuration': {}})
    stored = dict(row.configuration or {})
    stored[plan] = {**stored.get(plan, {}), 'discount_price_uzs': price, 'discount_until': until}
    row.configuration = stored
    row.save(update_fields=['configuration'])


def test_every_plan_says_what_it_includes_and_its_price(customer):
    configure(prices=None)  # the default prices: 20 000 and 60 000 so'm
    text = screen(customer)
    free, plus, premium = (text[text.index(head):] for head in ('Bepul</b>', 'Plus</b>', 'Premium</b>'))
    plus, free = plus[:plus.index('Premium</b>')], free[:free.index('Plus</b>')]
    for line in ("Bepul</b> — 0 so'm", 'AI hujjat va taqdimotlar: haftasiga 5 ta', 'AI tahrirlar: har bir faylga 3 ta',
                 'Fayl vositalari, Rasmlardan PDF ham: haftasiga 15 ta vazifa'):
        assert line in free, line
    for line in ("Plus</b> — 30 kun uchun 20 000 so'm", 'AI hujjat va taqdimotlar: haftasiga 20 ta',
                 'AI tahrirlar: har bir faylga 10 ta', 'Fayl vositalari: cheksiz'):
        assert line in plus, line
    for line in ("Premium</b> — 30 kun uchun 60 000 so'm", 'AI hujjat va taqdimotlar: cheksiz', 'AI tahrirlar: cheksiz',
                 'Fayl vositalari: cheksiz', 'Kanallarga obuna bo‘lish shart emas'):
        assert line in premium, line
    assert 'Kanallarga' not in free + plus, 'only Premium skips the channels'
    assert 'kredit' not in text.lower() and 'paket' not in text.lower()
    assert text.index('Bepul</b>') < text.index('Plus</b>') < text.index('Premium</b>') < text.index('Qanday to‘lanadi')
    assert 'Hozirgi tarifingiz: <b>Bepul</b>' in text and "Bepul</b> — 0 so'm · ✅ sizniki" in text


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_a_card_lists_only_the_weekly_limits_and_the_channels(customer, locale):
    """Plans differ only in the three weekly counts and the channels (owner's
    decision, 2026-10-16). File sizes, page and slide counts, tasks at once and
    saved workflows are the same on every plan, so no card sells one on them."""
    configure(prices=None)
    Account.objects.filter(pk=customer.pk).update(locale=locale)
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    customer.refresh_from_db()
    text = screen(customer)
    words = PLAN_COPY[locale]
    shown = text[:text.index(words['every_tool'])]  # the cards, and the title over them
    lines = [line[2:] for line in shown.splitlines() if line.startswith('• ')]
    assert len(lines) == 3 + 3 + 4, lines  # Premium adds the channels
    allowed = ('ai_week', 'ai_unlimited', 'edits', 'edits_unlimited', 'files_week', 'files_unlimited', 'no_channels')
    starts = {words[key].split('{')[0] for key in allowed}
    assert all(any(line.startswith(start) for start in starts) for line in lines), lines
    for size in ('MB', 'МБ', 'sahifagacha', 'slaydgacha', 'страниц', 'слайдов', 'pages', 'slides',
                 'saqlangan', 'Сохранённых', 'saved', 'at once', 'Bir vaqtda', 'Одновременно'):
        assert size not in shown, size
    for gone in ('ai_size', 'files', 'parallel', 'workflows'):
        assert gone not in words, gone
    # Said once, under every card and before how to pay.
    assert text.count(words['every_tool']) == 1
    assert text.index('Premium</b>') < text.index(words['every_tool']) < text.index(words['how'])


def test_every_tool_is_said_only_while_every_plan_has_it(customer, monkeypatch):
    from apps.core import policy
    configure(prices=None)
    assert PLAN_COPY['uz']['every_tool'] in screen(customer), 'the catalog gives every plan every tool'
    held_back = {**policy.FEATURES, 'pdf.merge': {**policy.FEATURES['pdf.merge'],
                                                  'plans': {'free': 'none', 'plus': 'included', 'premium': 'included'}}}
    monkeypatch.setattr(policy, 'FEATURES', held_back)
    text = screen(customer)
    assert PLAN_COPY['uz']['every_tool'] not in text and 'Qanday to‘lanadi' in text


def test_an_admin_change_is_what_customers_read(customer):
    configure(prices=None)
    plan_settings.save('plus', {'weekly_ai_documents': 25, 'weekly_file_jobs': 1500, 'price_uzs': 25000})
    text = screen(customer)
    assert 'haftasiga 25 ta' in text and 'haftasiga 1 500 ta vazifa' in text and "25 000 so'm" in text


def test_a_plan_not_on_sale_is_not_described(customer):
    configure(prices=None)
    plan_settings.save('premium', {'price_uzs': ''})
    assert 'Premium</b>' not in screen(customer)


def test_the_customers_own_plan_is_marked(customer):
    configure(prices=None)
    Account.objects.filter(pk=customer.pk).update(staff_plan='premium')
    customer.refresh_from_db()
    text = screen(customer)
    assert 'Hozirgi tarifingiz: <b>Premium</b>' in text and 'Premium</b> — 30 kun uchun 60 000 so\'m · ✅ sizniki' in text


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_each_language_gets_the_comparison_and_how_to_pay(customer, locale):
    configure(prices=None)
    Account.objects.filter(pk=customer.pk).update(locale=locale)
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    customer.refresh_from_db()
    text = screen(customer)
    words = PLAN_COPY[locale]
    assert text.startswith(words['title']) and words['how'] in text
    assert len(text) < 4096, 'one Telegram message'


def test_an_old_pack_button_or_pack_name_opens_the_plans(customer):
    """Packs and the Stars checkout are retired, but their buttons stay in chats
    and people still type /buy ai100 or /buy plus. They were told payments are
    unavailable, which is not so: the plans on sale today open instead."""
    from apps.commerce.models import Invoice
    from apps.core.models import BotCallback
    configure(prices=None)
    fresh = timezone.now() + timedelta(minutes=20)
    BotCallback.objects.create(token='old-pack-button', account=customer, action='commerce_offer',
                               payload={'offer_id': 'tasks100'}, expires_at=fresh)
    BotCallback.objects.create(token='old-pay-button', account=customer, action='commerce_pay',
                               payload={'invoice_id': 'gone'}, expires_at=fresh)
    for shown in (dispatch_local(customer, callback_data='old-pack-button'),
                  dispatch_local(customer, callback_data='old-pay-button'),
                  dispatch_local(customer, text='/buy ai100'),
                  dispatch_local(customer, text='/buy plus')):
        text = shown['messages'][-1]['text']
        assert text.startswith(PLAN_COPY['uz']['title']), text
        assert 'Plus</b>' in text and 'Premium</b>' in text
    assert not Invoice.objects.filter(account=customer).exists()


def test_russian_plan_cards_say_ii_like_every_other_russian_screen(customer):
    configure(prices=None)
    words = PLAN_COPY['ru']
    assert not [key for key, value in words.items() if 'AI' in value]
    Account.objects.filter(pk=customer.pk).update(locale='ru')
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale='ru')
    customer.refresh_from_db()
    text = screen(customer)
    assert 'ИИ-документы и презентации: 5 в неделю' in text and 'ИИ-правки: 3 на каждый файл' in text
    assert 'AI-' not in text


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_no_other_bot_line_puts_a_ceiling_on_the_plan(locale):
    """Page, slide and picture ceilings are the same on every plan, so the lines
    that say one was met name no plan: "your plan allows 7" read as an offer."""
    from telegram.ux_copy import UX
    for key in ('ai_pages_clamped', 'ai_images_capped', 'ai_images_capped_pdf', 'ai_images_none', 'images_limited'):
        assert not any(word in UX[locale][key].lower() for word in ('plan', 'tarif', 'тариф')), (key, UX[locale][key])


# ---------------------------------------------------------------- discounts


def test_a_discount_strikes_the_regular_price_through_and_says_until_when(customer):
    """The owner enters a discounted price and its last day; the card shows the
    regular price struck through, the price to pay, how much off and the day.
    No countdown, no "last chance": the line is its own, not one of the bullets."""
    configure(prices=None)
    until = discount('plus')
    text = screen(customer)
    plus = text[text.index('Plus</b>'):text.index('Premium</b>')]
    assert "Plus</b> — 30 kun uchun <s>20 000</s> <b>15 000</b> so'm" in plus
    line = f'−25% chegirma, {day_label(until, "uz")}gacha'  # the affix joins the day: '31-oktabrgacha'
    assert plus.splitlines()[1] == line, plus
    assert "Premium</b> — 30 kun uchun 60 000 so'm" in text and '<s>' not in text[text.index('Premium</b>'):]
    lines = [line for line in text.splitlines() if line.startswith('• ')]
    assert len(lines) == 3 + 3 + 4, 'the discount line is not a bullet'
    assert len(text) < 4096


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_the_discount_reads_naturally_in_each_language(customer, locale):
    configure(prices=None)
    until = discount('premium', price=45_000)
    Account.objects.filter(pk=customer.pk).update(locale=locale)
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(locale=locale)
    customer.refresh_from_db()
    text = screen(customer)
    words = PLAN_COPY[locale]
    head = words['head_discount'].format(icon='💎', name='Premium', regular='60 000', price='45 000')
    assert head + '\n' + words['discount_line'].format(percent=25, until=day_label(until, locale)) in text
    assert words['head'].format(icon='⭐', name='Plus', price='20 000') in text, 'Plus is at its regular price'
    assert text.count('<s>') == 1 and len(text) < 4096


def test_the_customers_own_discounted_plan_is_still_marked_on_the_head(customer):
    configure(prices=None)
    until = discount('plus')
    Account.objects.filter(pk=customer.pk).update(staff_plan='plus')
    customer.refresh_from_db()
    text = screen(customer)
    assert "<s>20 000</s> <b>15 000</b> so'm · ✅ sizniki\n−25% chegirma, " + day_label(until, 'uz') + 'gacha' in text


def test_a_discount_whose_last_day_has_passed_is_not_shown(customer):
    """It ends by itself at the end of its last day in Tashkent; a stored one
    left in the panel after that is ignored, not shown as −0% or struck through."""
    configure(prices=None)
    ended_discount('plus')
    text = screen(customer)
    assert "Plus</b> — 30 kun uchun 20 000 so'm" in text
    assert '<s>' not in text and 'chegirma' not in text and '%' not in text
