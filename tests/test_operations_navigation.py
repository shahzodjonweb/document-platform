"""Real rendered links keep report filters without accumulating query keys."""
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest
from django.utils import timezone

from tests.test_operations import staff_client

pytestmark = pytest.mark.django_db
FILTERS = [
    ('date_from', '2026-09-01'), ('date_to', '2026-10-01'),
    ('timezone', 'Etc/GMT+5'), ('environment', 'development'),
    ('locale', 'ru'), ('channel', 'bot'), ('q', 'A&B + O‘zbek? / test'),
    ('tag', 'one'), ('tag', 'two'),
]


class Links(HTMLParser):
    def __init__(self, response):
        super().__init__()
        self.links = []
        self.feed(response.content.decode())

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == 'a' and 'href' in attrs:
            self.links.append(attrs)


def parameters(url):
    return parse_qs(urlsplit(url).query, keep_blank_values=True)


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_repeated_sidebar_navigation_retains_encoded_filters_and_one_language(locale):
    client, _ = staff_client()
    expected = parse_qs(urlencode(FILTERS)) | {'lang': [locale]}
    # Start with a URL produced by the old sidebar, including an existing page.
    target = '/ops/overview?' + urlencode(FILTERS + [('lang', 'en'), ('lang', locale), ('lang', locale), ('p', '3')])
    for destination in ('jobs', 'payments', 'integrations', 'analytics/acquisition', 'staff', 'overview'):
        response = client.get(target)
        assert response.status_code == 200
        assert response.context['lang'] == locale
        assert parse_qs(response.context['query']) == expected
        sidebar = [link for link in Links(response).links if 'nav-link' in link.get('class', '').split()]
        assert sidebar
        for link in sidebar:
            assert parameters(link['href']) == expected
            assert 'p' not in parameters(link['href'])
        target = next(link['href'] for link in sidebar if urlsplit(link['href']).path == '/ops/' + destination)
    assert client.get(target).status_code == 200


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_language_switch_and_report_links_normalize_language_without_losing_filters(locale):
    client, _ = staff_client()
    response = client.get('/ops/users?' + urlencode(FILTERS + [('lang', 'en'), ('lang', locale), ('p', '2')]))
    assert response.status_code == 200
    expected = parse_qs(urlencode(FILTERS))
    for link in response.context['locale_links']:
        assert parameters(link['url']) == expected | {'lang': [link['locale']], 'p': ['2']}
    assert parameters(response.context['export_url']) == expected | {'lang': [locale]}


@pytest.mark.parametrize('locale', ['en', 'uz', 'ru'])
def test_finance_pagination_replaces_page_and_language_once(locale, monkeypatch):
    client, _ = staff_client()
    now = timezone.now()
    rows = [SimpleNamespace(id=uuid4(), account=SimpleNamespace(display_name='Fixture'),
                            kind='subscription', is_renewal=False, amount_xtr=1, plan='basic', occurred_at=now)
            for _ in range(61)]
    monkeypatch.setattr('operations.commerce_views.financial_report',
                        lambda filters: {'totals': {'gross': 61}, 'rows': rows, 'as_of': now, 'issues': []})
    response = client.get('/ops/payments?' + urlencode(FILTERS + [('lang', 'en'), ('lang', locale), ('p', '1'), ('p', '2')]))
    assert response.status_code == 200
    page_links = [link['href'] for link in Links(response).links if link['href'].startswith('?') and 'p' in parameters(link['href']) and 'lang' not in link]
    assert len(page_links) == 2
    expected = parse_qs(urlencode(FILTERS)) | {'lang': [locale]}
    assert {tuple(parameters(link)['p']) for link in page_links} == {('1',), ('3',)}
    for link in page_links:
        query = parameters(link)
        assert len(query.pop('p')) == 1
        assert query == expected
