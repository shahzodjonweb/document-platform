"""The AI categories' switch: off and empty until the owner ticks a ready category, read on every call, audited."""
import copy
import json

import pytest

from apps.studio import categories
from apps.studio.categories import catalogue
from operations.categories_settings import KEY, CategorySettingsError, get, save, validate
from operations.integrations import EDITOR_FLAGS
from operations.models import AuditLog, IntegrationConfig
from tests.test_operations import staff_client
from tests.test_platform import account, login_client

pytestmark = pytest.mark.django_db
OFF = {'on': False, 'live': []}


@pytest.fixture
def ready(monkeypatch):
    """The catalogue with the three examples marked ready, as N1 and N2 will mark entries."""
    entries, templates, index = copy.deepcopy(catalogue.read())
    for raw in entries.values():
        raw['status'] = 'ready'
    made = catalogue.build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    return made


def ids(entries):
    return [entry.id for entry in entries]


def test_it_is_off_and_empty_by_default_so_every_flow_is_todays(ready):
    assert get() == OFF and not IntegrationConfig.objects.filter(pk=KEY).exists()
    assert categories.on() is False
    assert categories.live('ai.pdf_topic') == [] and categories.menu('ai.pptx') == []


def test_a_saved_switch_is_what_the_catalogue_reads_on_the_next_call(ready):
    client, user = staff_client('Operations')
    save({'on': 'true', 'live': ['slides.himoya']}, user)
    assert categories.on() is True
    assert ids(categories.live('ai.pptx')) == ['slides.himoya'] and categories.live('ai.pdf_topic') == []
    assert [node.id for node in categories.menu('ai.pptx')] == ['slides.himoya', 'other']
    save({'on': 'false'}, user)
    assert categories.on() is False and categories.menu('ai.pptx') == []
    assert get() == {'on': False, 'live': ['slides.himoya']}, 'the ticks wait for the switch to come back on'


def test_only_ready_entries_can_be_ticked_and_unknown_ids_are_refused(monkeypatch):
    # A paper is a draft until its family's N2 makes it ready; the test is held one here (ready since N2a).
    entries, templates, index = copy.deepcopy(catalogue.read())
    entries['pdf.test']['status'] = 'draft'
    made = catalogue.build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    for values in ({'live': ['pdf.test']}, {'live': ['pdf.nothing']}, {'live': ['other']},
                   {'on': 'maybe'}, {'sources': 'true'}, {}):
        with pytest.raises(CategorySettingsError):
            validate(values)
    client, user = staff_client('Operations')
    with pytest.raises(CategorySettingsError):
        save({'on': 'true', 'live': ['pdf.test']}, user)
    assert get() == OFF and not AuditLog.objects.filter(action='categories.settings').exists()


def test_a_retired_entry_is_never_ticked(monkeypatch):
    entries, templates, index = copy.deepcopy(catalogue.read())
    entries['slides.himoya']['status'] = 'retired'
    made = catalogue.build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    with pytest.raises(CategorySettingsError):
        validate({'live': ['slides.himoya']})


def test_saving_writes_everything_in_force_and_audits_only_a_change(ready):
    client, user = staff_client('Operations')
    before, after = save({'on': 'true', 'live': ['slides.himoya', 'pdf.test', 'pdf.test']}, user)
    assert before == {'on': False, 'live': []} and after == {'on': True, 'live': ['pdf.test', 'slides.himoya']}
    row = AuditLog.objects.get(action='categories.settings')
    assert row.actor == user and row.target == KEY and row.before == before and row.after == after
    save({'live': ['slides.himoya']}, user)
    assert IntegrationConfig.objects.get(pk=KEY).configuration == {'on': True, 'live': ['slides.himoya']}
    assert AuditLog.objects.filter(action='categories.settings').count() == 2
    assert save({'on': 'on', 'live': ['slides.himoya']}, user) == ({}, {})
    assert AuditLog.objects.filter(action='categories.settings').count() == 2, 'an unchanged save leaves no row'


def test_a_ticked_entry_sent_back_to_draft_leaves_the_bot_without_an_edit(monkeypatch):
    # Ticked while ready, then a deploy marks it draft again: the row is untouched, the bot no longer lists it.
    entries, templates, index = copy.deepcopy(catalogue.read())
    entries['slides.himoya']['status'] = 'draft'
    made = catalogue.build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    IntegrationConfig.objects.create(key=KEY, configuration={'on': True, 'live': ['slides.himoya']})
    assert get() == {'on': True, 'live': ['slides.himoya']}
    assert categories.live('ai.pptx') == [] and categories.menu('ai.pptx') == []


@pytest.mark.parametrize('configuration', [{'on': 'yes', 'live': 'slides.himoya'}, {'on': 1, 'live': [3, None]}, []])
def test_a_row_that_does_not_hold_together_reads_as_off(configuration):
    IntegrationConfig.objects.create(key=KEY, configuration=configuration)
    assert get() == OFF


def test_the_page_shows_the_switch_and_every_category_with_its_renderer_and_gates():
    client, _ = staff_client('Operations')
    page = client.get('/ops/categories')
    assert page.status_code == 200
    html = page.content.decode()
    assert 'name="on" value="true">' in html and 'action="/ops/categories/settings"' in html
    for entry in (*categories.for_feature('ai.pdf_topic'), *categories.for_feature('ai.pptx')):
        # The decks are ready since N1 and can be ticked; a draft is shown greyed, never tickable.
        ready = entry.status == catalogue.READY
        assert (f'value="{entry.id}" disabled' in html) is not ready
        assert f'value="{entry.id}"' in html
        assert entry.label('en') in html
    assert 'study_test' in html and 'official_ariza' in html and 'boardroom' in html
    assert 'A native Uzbek reader checks the fixed headings' in html


def test_the_form_saves_audits_and_shows_it(ready):
    client, user = staff_client('Operations')
    page = client.get('/ops/categories').content.decode()
    assert 'value="slides.himoya">' in page and 'disabled' not in page.split('name="live" value="slides.himoya"')[1][:20]
    saved = client.post('/ops/categories/settings', {'on': ['false', 'true'], 'live': ['', 'slides.himoya', 'pdf.xat.ariza']})
    assert saved.status_code == 302 and saved['Location'] == '/ops/categories?saved=1'
    assert get() == {'on': True, 'live': ['pdf.xat.ariza', 'slides.himoya']}
    row = AuditLog.objects.get(action='categories.settings')
    assert row.actor == user and row.after == {'on': True, 'live': ['pdf.xat.ariza', 'slides.himoya']}
    shown = client.get('/ops/categories?saved=1').content.decode()
    assert 'name="on" value="true" checked' in shown and 'value="slides.himoya" checked' in shown
    assert shown.count('Open in the bot') == 2
    # The hidden empty value is all that is sent with every box unticked: the last tick goes too.
    client.post('/ops/categories/settings', {'on': 'false', 'live': ''})
    assert get() == OFF and AuditLog.objects.filter(action='categories.settings').count() == 2


def test_a_bad_form_is_refused_with_nothing_saved(ready):
    client, _ = staff_client('Operations')
    assert client.post('/ops/categories/settings', {'on': 'true', 'live': ['pdf.nothing']}).status_code == 400
    assert client.post('/ops/categories/settings', {'on': 'true', 'editor_v2': 'true'}).status_code == 400
    assert client.post('/ops/categories/settings', {}).status_code == 400
    assert get() == OFF and not AuditLog.objects.filter(action='categories.settings').exists()


def test_only_operations_may_see_or_change_it():
    client, _ = staff_client('Analyst')
    assert client.get('/ops/categories').status_code == 403
    assert client.post('/ops/categories/settings', {'on': 'true'}).status_code == 403
    customer = login_client(account())
    assert customer.post('/ops/categories/settings', {'on': 'true'}).status_code in (302, 401, 403)
    assert get() == OFF


def test_it_is_not_an_editor_flag_and_the_web_is_not_told():
    save({'on': 'true'}, None)
    client = login_client(account())
    config = client.get('/api/v1/studio/config').json()
    assert set(config['limits']['editor']) == set(EDITOR_FLAGS)
    assert 'categories' not in json.dumps(config)


@pytest.mark.parametrize('lang', ['en', 'uz', 'ru'])
def test_the_page_is_in_every_language(lang):
    from operations.i18n import CATALOGS
    client, _ = staff_client('Operations')
    page = client.get(f'/ops/categories?lang={lang}')
    assert page.status_code == 200
    for label in ('categories_desc', 'categories_on', 'categories_switch_note', 'categories_service_pdf',
                  'categories_status_draft', 'save_changes'):
        assert CATALOGS[lang][label] in page.content.decode(), label
    assert categories.get('pdf.xat.ariza').label(lang) in page.content.decode()
