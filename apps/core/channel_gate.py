"""Free accounts join the owner's Telegram channels before using a service.

The owner lists the channels in the panel. A free account that has not joined
every one of them cannot start a task — on the web, in the bot or in the mini
app — and is shown the channels to join; paid plans are never asked.

This is a growth rule, not a security boundary, so it fails open: when Telegram
cannot be asked, or a channel is set up so the bot cannot see its members, the
customer is let through rather than locked out of a product they could
otherwise use. The panel's check says which channel needs fixing.
"""
import json
import urllib.error
import urllib.request
from datetime import timedelta
from urllib.parse import urlencode

from django.utils import timezone

from .errors import DomainError

MEMBER_HOURS = 6
NOT_MEMBER_SECONDS = 60
UNKNOWN_SECONDS = 120
TIMEOUT = 5
MEMBER = {'creator', 'administrator', 'member'}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('redirect_refused')


def _call(method, params, token):
    """One Bot API call: (ok, result or description). Never raises."""
    url = f'https://api.telegram.org/bot{token}/{method}?' + urlencode(params)
    try:
        with urllib.request.build_opener(_NoRedirect).open(urllib.request.Request(url), timeout=TIMEOUT) as response:
            data = json.loads(response.read(65_536))
    except urllib.error.HTTPError as error:
        try:
            data = json.loads(error.read(65_536))
        except Exception:
            return False, 'unavailable'
    except Exception:
        return False, 'unavailable'
    if not isinstance(data, dict):
        return False, 'unavailable'
    if data.get('ok'):
        return True, data.get('result') or {}
    return False, str(data.get('description') or 'error')[:200]


def member(chat, user_id, token):
    """True if joined, False if not, None if Telegram would not say."""
    ok, result = _call('getChatMember', {'chat_id': chat, 'user_id': user_id}, token)
    if not ok or not isinstance(result, dict):
        return None
    status = result.get('status')
    if status in MEMBER:
        return True
    if status == 'restricted':
        return bool(result.get('is_member'))
    if status in ('left', 'kicked'):
        return False
    return None


def inspect(chat, bot_id, token):
    """Whether the bot can see who has joined this chat, and the chat's title."""
    ok, chat_info = _call('getChat', {'chat_id': chat}, token)
    if not ok:
        return {'ok': False, 'title': '', 'reason': 'chat_not_found'}
    title = str(chat_info.get('title') or '')[:80]
    seen, me = _call('getChatMember', {'chat_id': chat, 'user_id': bot_id}, token)
    status = me.get('status') if seen and isinstance(me, dict) else ''
    kind = chat_info.get('type')
    # A channel's member list is visible only to its administrators.
    able = status in ('administrator', 'creator') or (kind in ('group', 'supergroup') and status == 'member')
    return {'ok': able, 'title': title, 'reason': '' if able else 'bot_not_admin'}


def _config():
    from operations.integrations import channel_gate_config
    return channel_gate_config()


def _token():
    from operations.integrations import telegram_config
    return telegram_config()['token']


def applies(account, config=None):
    """Whether this account is asked to join: only free accounts, only when on."""
    from apps.commerce.services import refresh_account_entitlement
    config = config or _config()
    if not config['ready']:
        return False
    refresh_account_entitlement(account)
    return account.plan == 'free'


def status(account, refresh=False):
    """Every required channel, and whether this account has joined it."""
    from .models import ChannelMembership
    config = _config()
    if not applies(account, config):
        return {'required': False, 'joined': True, 'channels': []}
    now = timezone.now()
    token = _token()
    rows = {row.chat: row for row in ChannelMembership.objects.filter(account=account)}
    channels = []
    for channel in config['channels']:
        row = rows.get(channel['chat'])
        if row is not None and row.expires_at > now and not refresh:
            joined = row.is_member
        elif account.telegram_user_id is None:
            # Membership can only be checked for a Telegram account.
            joined = False
        elif not token:
            joined = True
        else:
            seen = member(channel['chat'], account.telegram_user_id, token)
            joined = True if seen is None else seen
            ttl = (timedelta(seconds=UNKNOWN_SECONDS) if seen is None
                   else timedelta(hours=MEMBER_HOURS) if seen else timedelta(seconds=NOT_MEMBER_SECONDS))
            ChannelMembership.objects.update_or_create(
                account=account, chat=channel['chat'],
                defaults={'is_member': joined, 'checked_at': now, 'expires_at': now + ttl})
        channels.append({'title': channel['title'], 'url': channel['url'], 'joined': joined})
    return {'required': True, 'joined': all(c['joined'] for c in channels), 'channels': channels}


def require(account):
    """Stop a free account that has not joined, and say where to join."""
    current = status(account)
    if current['required'] and not current['joined']:
        raise DomainError('channels_required', 403, {
            'channels': [{'title': c['title'], 'url': c['url'], 'joined': c['joined']} for c in current['channels']],
            'telegram_linked': account.telegram_user_id is not None})
    return current
