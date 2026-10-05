"""Small pieces the admin templates share: icons, initials, plain-language times."""
from datetime import timedelta

from django import template
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()

# Line icons drawn on a 24px grid, stroked with the text colour.
ICONS = {
    'today': '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/><path d="M9.5 21v-6h5v6"/>',
    'users': '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
             '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    'support': '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
    'sparkle': '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>'
               '<path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
    'card': '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/><path d="M6 15h4"/>',
    'trending': '<path d="M22 7l-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/>',
    'chart': '<path d="M3 3v18h18"/><path d="M8 17v-5"/><path d="M13 17V8"/><path d="M18 17V11"/>',
    'list': '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/>'
            '<path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/>',
    'cpu': '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/>'
           '<path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    'layers': '<path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    'plug': '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v4a6 6 0 0 1-12 0z"/><path d="M12 18v4"/>',
    'shield': '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    'history': '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    'activity': '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    'globe': '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/>'
             '<path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
    'search': '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    'moon': '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
           'M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
    'menu': '<path d="M4 6h16M4 12h16M4 18h16"/>',
    'logout': '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
    'chevron-down': '<path d="m6 9 6 6 6-6"/>',
    'right': '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    'left': '<path d="M19 12H5"/><path d="m12 19-7-7 7-7"/>',
    'check': '<path d="M20 6 9 17l-5-5"/>',
    'download': '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    'external': '<path d="M15 3h6v6"/><path d="M10 14 21 3"/>'
                '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
    'alert': '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
             '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    'info': '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    'file': '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/>',
    'close': '<path d="M18 6 6 18M6 6l12 12"/>',
    'plus': '<path d="M12 5v14M5 12h14"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    'inbox': '<path d="M22 12h-6l-2 3h-4l-2-3H2"/>'
             '<path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"/>',
    'storage': '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>'
               '<path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>',
    'gift': '<rect x="3" y="8" width="18" height="4" rx="1"/><path d="M12 8v13"/>'
            '<path d="M19 12v7a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2v-7"/>'
            '<path d="M7.5 8a2.5 2.5 0 0 1 0-5C11 3 12 8 12 8s1-5 4.5-5a2.5 2.5 0 0 1 0 5"/>',
    'star': '<path d="m12 2 3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1z"/>',
    'send': '<path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/>',
}


@register.simple_tag
def icon(name, size=18):
    """An inline line icon; decorative, so hidden from screen readers."""
    return format_html(
        '<svg class="icon" width="{0}" height="{0}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
        '{1}</svg>', size, mark_safe(ICONS.get(name, ICONS['info'])))


@register.filter
def initial(value):
    """The first letter of a name, for an avatar."""
    text = str(value or '').strip().lstrip('@')
    return text[:1].upper() or '?'


@register.filter
def meter_state(row):
    """How full an allowance is, as a CSS class for its bar."""
    remaining, limit = row.get('remaining') or 0, row.get('limit') or 0
    if not limit or remaining <= 0:
        return 'empty'
    return 'low' if remaining / limit < 0.2 else ''


@register.filter
def meter_percent(row):
    remaining, limit = row.get('remaining') or 0, row.get('limit') or 0
    return 0 if not limit else max(0, min(100, round(remaining * 100 / limit)))


@register.filter
def money(amount):
    """1234567 → "1 234 567"."""
    try:
        return f'{int(amount or 0):,}'.replace(',', ' ')
    except (TypeError, ValueError):
        return amount


@register.simple_tag
def since(moment, lang='en'):
    """How long ago, in a few words: "5 min", "3 h", "2 d"."""
    if not moment:
        return '—'
    seconds = max(0, (timezone.now() - moment).total_seconds())
    units = {'en': ('min', 'h', 'd'), 'uz': ('daq', 'soat', 'kun'), 'ru': ('мин', 'ч', 'дн')}.get(lang, ('min', 'h', 'd'))
    if seconds < 3600:
        return f'{max(1, int(seconds // 60))} {units[0]}'
    if seconds < 86400:
        return f'{int(seconds // 3600)} {units[1]}'
    return f'{int(seconds // 86400)} {units[2]}'


@register.simple_tag(takes_context=True)
def query_with(context, **changes):
    """The current query string with some keys replaced (None removes one), pagination reset."""
    params = context['request'].GET.copy()
    params.pop('p', None)
    params['lang'] = context.get('lang', 'en')
    for key, value in changes.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


@register.inclusion_tag('ops/filters.html', takes_context=True)
def filter_bar(context, presets=True):
    """Date presets as one segmented control; everything else folded under "Filters"."""
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo
    filters = context.get('filters')
    if isinstance(filters, dict):
        # Reports hand their filters back as a plain dict.
        filters = SimpleNamespace(**filters)
    request = context['request']
    links = []
    if filters and presets:
        today = timezone.now().astimezone(ZoneInfo(filters.timezone)).date()
        end = str(today + timedelta(days=1))
        for days, key in ((1, 'today'), (7, 'last_7'), (30, 'last_30'), (90, 'last_90')):
            start = str(today - timedelta(days=days - 1))
            params = request.GET.copy()
            params.pop('p', None)
            params['lang'] = context.get('lang', 'en')
            params['date_from'], params['date_to'] = start, end
            links.append({'label': context['t'][key], 'url': '?' + params.urlencode(),
                          'active': filters.date_from == start and filters.date_to == end})
    hidden = [(key, value) for key, value in request.GET.items()
              if key in {'q', 'status', 'plan', 'text', 'service'}]
    # The summary says which narrowing filters are on, so nothing is hidden by surprise.
    active = []
    if filters:
        channels = {'web': 'Web', 'bot': 'Telegram Bot', 'mini_app': 'Mini App'}
        active = [value for value in (channels.get(filters.channel), filters.locale.upper(),
                                      context['t']['development'] if filters.environment == 'development' else '',
                                      filters.timezone if filters.timezone != 'UTC' else '') if value]
    return {'t': context['t'], 'lang': context.get('lang', 'en'), 'filters': filters, 'presets': links,
            'custom': filters and presets and not any(link['active'] for link in links), 'hidden': hidden,
            'active': active}
