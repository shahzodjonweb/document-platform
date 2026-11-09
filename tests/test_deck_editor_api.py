"""What the deck editor asks of the platform beside the deck itself, and what its saves must never do to a deck already drawn.

A Latin preview for an Uzbek deck typed in Cyrillic saves nothing. The lines a
customer keeps for their next decks' covers are theirs alone, packed at rest,
never in the profile, and a settings save keeps them. A deck is saved whole on
every edit, long ones too. And a drawn deck's saves keep it the deck it is:
never blanked by an options or title save, never refused for a file it was made
from that has gone since, its pins kept, even for a change once made on one slide.
"""
import copy
import json
import uuid

import pytest

from apps.core.errors import DomainError
from apps.core.models import Account, FileAsset
from apps.studio import cover_lines as kept
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, draft_data, unpack, update_draft
from apps.studio.models import GenerationDraft
from apps.studio.variants import fixtures
from telegram.generation import relocale, resize
from tests.test_deck_pins import CARDS, customer, generate, pins_of, run, stock_photos  # noqa: F401
from tests.test_platform import account, login_client, upload
from tests.test_render_export import branded_deck
from tests.test_studio import paid
from tests.test_studio_branding import logo

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deck_editor_on(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')


def post(customer, path, body, client=None):  # noqa: F811
    # In UTF-8, as a browser sends it: the test client's own encoding sends every Cyrillic letter as six bytes.
    return (client or login_client(customer)).post(f'/api/v1/{path}', json.dumps(body, ensure_ascii=False).encode(), content_type='application/json')


def error(answer):
    return answer.json()['error']['code']


def stored(draft):
    return unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)


def patch(customer, draft, body):  # noqa: F811
    return login_client(customer).patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps(body), content_type='application/json')


def save_content(customer, draft, change):  # noqa: F811
    """A save as the editor makes one: the whole content, as it now stands, with `change` made to it."""
    data = stored(draft)
    content = copy.deepcopy(data['content'])
    change(content)
    answer = patch(customer, draft, {'version': GenerationDraft.objects.get(pk=draft.pk).version, 'content': content})
    assert answer.status_code == 200, answer.content
    return answer


# ---------------------------------------------------------------- the Latin preview


def test_latin_writes_an_uzbek_deck_s_cyrillic_in_latin_letters_and_saves_nothing(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    before = bytes(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    answer = post(customer, 'studio/latin', {'texts': ['Ҳаво ифлосланиши', 'Ўқувчилар ғалабаси', 'Already Latin', 'oʻzbek tili']})
    assert answer.status_code == 200, answer.content
    out = answer.json()['texts']
    assert out == ['Havo ifloslanishi', 'O‘quvchilar g‘alabasi', 'Already Latin', 'o‘zbek tili'] and answer.json()['changed'] is True
    assert '‘' in out[1] and not any(mark in text for text in out for mark in ('’', 'ʻ'))
    # х is x and ҳ is h: the letters are not one.
    assert post(customer, 'studio/latin', {'texts': ['Хаво']}).json() == {'texts': ['Xavo'], 'changed': True}
    assert post(customer, 'studio/latin', {'texts': ['Already Latin', '']}).json() == {'texts': ['Already Latin', ''], 'changed': False}
    now = GenerationDraft.objects.get(pk=draft.pk)
    assert now.version == draft.version and bytes(now.encrypted_data) == before


def test_latin_refuses_anything_but_a_short_list_of_texts(customer):  # noqa: F811
    for body in ({}, {'texts': 'Ҳаво'}, {'texts': []}, {'texts': ['Ҳаво'] * 41}, {'texts': ['Ҳаво', 7]}, {'texts': ['я' * 6000, 'я' * 6001]}):
        answer = post(customer, 'studio/latin', body)
        assert answer.status_code == 400 and error(answer) == 'invalid_parameters', body
    assert post(customer, 'studio/latin', {'texts': ['я' * 6000, 'я' * 6000]}).status_code == 200
    answer = login_client(customer).post('/api/v1/studio/latin', {'texts': 'Ҳаво'})
    assert answer.status_code == 415 and error(answer) == 'invalid_content_type'


def test_latin_and_cover_lines_wait_for_the_deck_editor_switch(customer, monkeypatch):  # noqa: F811
    monkeypatch.delenv('EDITOR_FLAG_DECK_EDITOR')
    client = login_client(customer)
    for answer in (client.get('/api/v1/studio/cover-lines'), post(customer, 'studio/cover-lines', {'lines': ['9-B sinf']}, client),
                   client.delete('/api/v1/studio/cover-lines'), post(customer, 'studio/latin', {'texts': ['Ҳаво']}, client)):
        assert answer.status_code == 409 and error(answer) == 'feature_unavailable'
    assert kept.remembered(Account.objects.get(pk=customer.pk)) == NONE


def test_latin_counts_per_account(customer, settings):  # noqa: F811
    from apps.studio import views
    client = login_client(customer)
    answers = [post(customer, 'studio/latin', {'texts': ['Ҳаво']}, client) for _ in range(views.LATIN_PER_MINUTE + 1)]
    assert [answer.status_code for answer in answers[:-1]] == [200] * views.LATIN_PER_MINUTE
    assert answers[-1].status_code == 429 and error(answers[-1]) == 'rate_limited' and answers[-1].json()['error']['retryable'] is True
    other = paid(settings, account(77))
    assert post(other, 'studio/latin', {'texts': ['Ҳаво']}).status_code == 200


# ---------------------------------------------------------------- kept cover lines


LINES = ['Tayyorladi: Karimova Dilnoza', '9-B sinf']
KEPT = {'lines': LINES, 'locale': 'uz', 'roles': ['made', 'group']}
NONE = {'lines': [], 'locale': None, 'roles': []}


def test_cover_lines_are_remembered_unreadable_at_rest_and_forgotten(customer):  # noqa: F811
    client = login_client(customer)
    assert client.get('/api/v1/studio/cover-lines').json() == NONE
    answer = post(customer, 'studio/cover-lines', {'lines': LINES}, client)
    assert answer.status_code == 200 and answer.json() == {'lines': LINES, 'locale': None, 'roles': [None, None]}
    # With the language of the deck they were written for and the Cover sheet row of each, which are kept with them.
    answer = post(customer, 'studio/cover-lines', KEPT, client)
    assert answer.status_code == 200 and answer.json() == KEPT
    assert client.get('/api/v1/studio/cover-lines').json() == KEPT
    assert 'Karimova' not in json.dumps(Account.objects.get(pk=customer.pk).preferences)
    answer = client.delete('/api/v1/studio/cover-lines')
    assert answer.status_code == 200 and answer.json() == NONE
    assert client.get('/api/v1/studio/cover-lines').json() == NONE
    assert 'cover_lines' not in Account.objects.get(pk=customer.pk).preferences


def test_cover_lines_refuse_more_than_eight_lines_or_a_long_one(customer):  # noqa: F811
    client = login_client(customer)
    for lines in ([f'Line {n}' for n in range(9)], ['a' * 161], [], ['   '], 'Tayyorladi: Karimova', ['9-B sinf', 9], None):
        answer = post(customer, 'studio/cover-lines', {'lines': lines}, client)
        assert answer.status_code == 400 and error(answer) == 'invalid_parameters', lines
    # A deck's language is one of the decks' own.
    for locale in ('de', 'UZ', '', 5, ['uz']):
        answer = post(customer, 'studio/cover-lines', {'lines': LINES, 'locale': locale}, client)
        assert answer.status_code == 400 and error(answer) == 'invalid_parameters', locale
    # A row for each line given, and one of the Cover sheet's.
    for roles in (['made'], ['made', 'group', 'school'], [], 'made', {'0': 'made'}, ['made', 'teacher'], ['made', 'Group'],
                  ['made', ''], ['made', 5], ['made', ['group']]):
        answer = post(customer, 'studio/cover-lines', {'lines': LINES, 'roles': roles}, client)
        assert answer.status_code == 400 and error(answer) == 'invalid_parameters', roles
    assert client.get('/api/v1/studio/cover-lines').json() == NONE
    # A tab or a zero-width space is a space, and spaces run together; blank lines go, and their rows with them.
    answer = post(customer, 'studio/cover-lines', {'lines': ['Tayyorladi:\tKarimova​D.', '', ' 9-B  sinf ', 'a' * 160], 'locale': 'ru',
                                                   'roles': ['made', 'school', 'group', None]}, client)
    assert answer.json() == {'lines': ['Tayyorladi: Karimova D.', '9-B sinf', 'a' * 160], 'locale': 'ru', 'roles': ['made', 'group', None]}


def test_kept_rows_that_no_longer_match_their_lines_are_not_said(customer):  # noqa: F811
    from apps.studio.domain import pack
    client = login_client(customer)
    for roles, read in ((['made', 'group'], ['made', 'group']), (['made'], [None, None]), ('made', [None, None]),
                        (['made', 'teacher'], ['made', None]), (None, [None, None])):
        Account.objects.filter(pk=customer.pk).update(preferences={'cover_lines': pack({'lines': LINES, 'locale': 'uz', 'roles': roles}).decode()})
        assert client.get('/api/v1/studio/cover-lines').json() == {'lines': LINES, 'locale': 'uz', 'roles': read}, roles


def test_cover_lines_never_reach_the_profile_and_survive_a_settings_save(customer):  # noqa: F811
    client = login_client(customer)
    post(customer, 'studio/cover-lines', KEPT, client)
    assert 'cover_lines' not in client.get('/api/v1/me').json()['preferences']
    settings_save = {'theme': 'dark', 'paper_size': 'A4', 'output_locale': 'uz', 'adult_assistance': False}
    answer = client.patch('/api/v1/me', json.dumps({'preferences': settings_save}), content_type='application/json')
    assert answer.status_code == 200 and answer.json()['preferences'] == settings_save
    assert client.get('/api/v1/studio/cover-lines').json() == KEPT
    held = Account.objects.get(pk=customer.pk).preferences
    answer = client.patch('/api/v1/me', json.dumps({'time_zone': 'Asia/Tashkent'}), content_type='application/json')
    assert answer.status_code == 200
    assert Account.objects.get(pk=customer.pk).preferences == held and Account.objects.get(pk=customer.pk).time_zone == 'Asia/Tashkent'
    answer = client.patch('/api/v1/me', json.dumps({'preferences': {**settings_save, 'cover_lines': 'anything'}}), content_type='application/json')
    assert answer.status_code == 400 and error(answer) == 'invalid_profile_fields'
    assert client.get('/api/v1/studio/cover-lines').json() == KEPT
    # Preferences that are not even an object still answer.
    Account.objects.filter(pk=customer.pk).update(preferences=[])
    assert client.get('/api/v1/me').status_code == 200
    assert client.get('/api/v1/studio/cover-lines').json() == NONE


def test_cover_lines_are_the_accounts_own(customer, settings):  # noqa: F811
    post(customer, 'studio/cover-lines', KEPT)
    other = paid(settings, account(77))
    client = login_client(other)
    assert client.get('/api/v1/studio/cover-lines').json() == NONE
    assert client.delete('/api/v1/studio/cover-lines').json() == NONE
    assert login_client(customer).get('/api/v1/studio/cover-lines').json() == KEPT


# ---------------------------------------------------------------- saves of a drawn deck


def long_sections(count, letters=1300):
    line = 'Гавань принимает суда круглый год '
    return [{'id': f's{n}', 'heading': f'Раздел {n}', 'body': (line * (letters // len(line) + 1))[:letters], 'layout': 'bullets'}
            for n in range(1, count + 1)]


def test_a_long_deck_saves_whole_up_to_128_kib_and_is_refused_past_it(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    data = stored(draft)
    content = {**data['content'], 'sections': long_sections(42)}
    # As a browser sends it, in UTF-8 (post above).
    raw = json.dumps({'version': draft.version, 'content': content}, ensure_ascii=False).encode()
    assert 100_000 < len(raw) <= 131_072
    client = login_client(customer)
    answer = client.patch(f'/api/v1/generation/drafts/{draft.id}', data=raw, content_type='application/json')
    assert answer.status_code == 200, answer.content
    assert [section['body'] for section in stored(draft)['content']['sections']] == [section['body'] for section in content['sections']]
    version = GenerationDraft.objects.get(pk=draft.pk).version
    raw = json.dumps({'version': version, 'content': {**content, 'sections': long_sections(56)}}, ensure_ascii=False).encode()
    assert len(raw) > 140_000
    answer = client.patch(f'/api/v1/generation/drafts/{draft.id}', data=raw, content_type='application/json')
    assert answer.status_code == 413 and error(answer) == 'payload_too_large'
    assert GenerationDraft.objects.get(pk=draft.pk).version == version
    # Every other draft keeps the old bound.
    document = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Harbour notes', 'source_text': 'Notes about the harbour.'})
    raw = json.dumps({'version': document.version, 'source_text': 'я' * 17_000}, ensure_ascii=False).encode()
    assert len(raw) > 32_768
    answer = client.patch(f'/api/v1/generation/drafts/{document.id}', data=raw, content_type='application/json')
    assert answer.status_code == 413 and error(answer) == 'invalid_request'


def test_a_drawn_deck_saves_after_its_source_file_is_read_no_more_or_deleted(customer, stock_photos, monkeypatch):  # noqa: F811
    from apps.studio import extraction
    from tests.test_deck_pins import deck_sections, questions
    source = upload(customer)
    draft = create_draft(customer, {'feature_id': SLIDES, 'title': 'Harbour logistics review', 'source_ids': [str(source.id)], 'options': {'pages': 8}})
    assert stored(draft)['source_ids'] == [str(source.id)]
    draft = update_draft(customer, draft.id, {'version': draft.version, 'content': {
        'title': 'Harbour logistics review', 'sections': deck_sections(), 'questions': questions(), 'citations': []}})
    job = run(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert pins_of(draft)

    def unreadable(*args, **kwargs):
        raise AssertionError('a save of a drawn deck read its source file again')
    monkeypatch.setattr(extraction, 'extract_pages', unreadable)
    save_content(customer, draft, lambda content: content['sections'][1].update(heading='Reworded while the file is unreadable'))
    answer = login_client(customer).delete(f'/api/v1/files/{source.id}')
    assert answer.status_code == 200, answer.content
    save_content(customer, draft, lambda content: content['sections'][1].update(heading='Reworded after the file was deleted'))
    data = stored(draft)
    assert data['content']['sections'][1]['heading'] == 'Reworded after the file was deleted' and data['source_ids'] == [str(source.id)]
    assert pins_of(draft) and 'render' in draft_data(GenerationDraft.objects.get(pk=draft.pk))
    # Files named anew are still looked for.
    other = upload(customer, name='other.pdf')
    answer = patch(customer, draft, {'version': GenerationDraft.objects.get(pk=draft.pk).version, 'source_ids': [str(source.id), str(other.id)]})
    assert answer.status_code == 404 and error(answer) == 'file_unavailable'


def test_a_drawn_deck_saves_after_its_logo_is_deleted(customer):  # noqa: F811
    mark = logo(customer)
    draft = branded_deck(customer, mark)
    answer = login_client(customer).delete(f'/api/v1/files/{mark.id}')
    assert answer.status_code == 200, answer.content
    assert FileAsset.objects.get(pk=mark.pk).state == 'revoked'
    save_content(customer, draft, lambda content: content['sections'][1].update(heading='Reworded after the logo went'))
    branding = stored(draft)['options']['branding']
    assert branding['logo_asset_id'] == str(mark.id) and branding['logo_sha256'] == mark.sha256 and branding['name'] == 'Harbour School'
    version = GenerationDraft.objects.get(pk=draft.pk).version
    answer = post(customer, f'generation/drafts/{draft.id}/export-quote', {'version': version, 'format': 'pptx', 'deliver': 'chat'})
    assert answer.status_code == 201, answer.content
    assert answer.json()['summary']['warnings'] == ['logo_left_out']


def shape_of(draft):
    draft.refresh_from_db()
    data = unpack(draft.encrypted_data)
    return [section['id'] for section in data['content']['sections']], data['options']


def test_an_options_only_save_after_slides_were_added_keeps_the_deck_and_its_pins(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    added = str(uuid.uuid4())
    save_content(customer, draft, lambda content: content['sections'].append({**fixtures.light('bullets', 3), 'id': added}))
    ids, options = shape_of(draft)
    assert ids[-1] == added and len(ids) == 9
    # The web's Review draft sends the options back as they are.
    saves = [lambda: update_draft(customer, draft.id, {'version': GenerationDraft.objects.get(pk=draft.pk).version, 'options': shape_of(draft)[1]}),
             lambda: update_draft(customer, draft.id, {'version': GenerationDraft.objects.get(pk=draft.pk).version, 'title': 'A new title'})]
    for save in saves:
        save()
        now, options = shape_of(draft)
        assert now == ids, 'not rebuilt'
        assert pins_of(draft) and 'render' in draft_data(GenerationDraft.objects.get(pk=draft.pk))
        assert options['length'] == len(now) + options['question_slides']
    assert stored(draft)['title'] == 'A new title'
    # A count asked for anew is another deck, as it always was (test_deck_pins.py, another_count). The bot's old
    # review no longer asks for one on a deck already made (below).
    update_draft(customer, draft.id, {'version': GenerationDraft.objects.get(pk=draft.pk).version, 'options': {**shape_of(draft)[1], 'pages': 5}})
    assert pins_of(draft) is None and shape_of(draft)[0] != ids


def test_an_old_reviews_count_and_language_buttons_leave_a_made_deck_as_it_is(customer, stock_photos):  # noqa: F811
    """A review left in the chat keeps its ➖/➕ and language buttons for 30 minutes: on a deck already made they
    would build it anew, over the slides edited since. They refuse, and ✏️ Edit under the file changes it."""
    draft, _ = generate(customer)
    save_content(customer, draft, lambda content: content['sections'].append({**fixtures.light('bullets', 3), 'id': 'added-slide'}))
    before, pins, version = stored(draft), pins_of(draft), GenerationDraft.objects.get(pk=draft.pk).version
    for tap in (lambda: resize(customer, draft.id, 5), lambda: resize(customer, draft.id, 10), lambda: relocale(customer, draft.id, 'ru')):
        with pytest.raises(DomainError) as refused:
            tap()
        assert refused.value.code == 'generation_finished' and refused.value.status == 409
    assert stored(draft) == before and pins_of(draft) == pins and GenerationDraft.objects.get(pk=draft.pk).version == version
    assert 'added-slide' in [section['id'] for section in before['content']['sections']]


def test_the_button_their_refusal_names_is_the_one_under_the_file(customer, stock_photos, monkeypatch):  # noqa: F811
    """✏️ Edit only where delivery.result_controls draws it under the deck's file: the Edit buttons and the deck
    editor on, the deck drawn (its pins), an address for the web app. Anywhere else, the AI change it draws."""
    from apps.commerce.models import BotDelivery
    from apps.studio.domain import pack
    from telegram.delivery import deck_change_label, enqueue, result_controls
    from telegram.ux_copy import UX
    config = {'webapp_url': 'https://pdfmaster.example/en/app'}
    monkeypatch.setattr('telegram.delivery.telegram_config', lambda: config)
    monkeypatch.setenv('EDITOR_FLAG_EDIT_BUTTONS', '1')
    draft, job = generate(customer)
    enqueue(job.artifacts.get(), f'job:{job.id}')
    delivery = BotDelivery.objects.get(artifact__job=job)
    copy_of = UX[customer.locale if customer.locale in UX else 'en']

    def named():
        label = copy_of[deck_change_label(customer, draft.id)]
        assert label in [button.text for row in result_controls(delivery).inline_keyboard for button in row], label
        return label

    assert named() == copy_of['edit']
    config['webapp_url'] = ''
    assert named() == copy_of['ai_ask_to_change']
    config['webapp_url'] = 'http://localhost:3000/en/app'  # a link rather than a Mini App, but under the file all the same
    assert named() == copy_of['edit']
    monkeypatch.delenv('EDITOR_FLAG_DECK_EDITOR')
    assert named() == copy_of['ai_ask_to_change']
    monkeypatch.delenv('EDITOR_FLAG_EDIT_BUTTONS')
    assert named() == copy_of['ai_revise']
    # A deck made with no pins (their write failed, which never fails the job) is refused all the same, and has no ✏️ Edit.
    monkeypatch.setenv('EDITOR_FLAG_EDIT_BUTTONS', '1')
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')
    data = stored(draft)
    del data['_render']
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    assert named() == copy_of['ai_ask_to_change']
    with pytest.raises(DomainError) as refused:
        resize(customer, draft.id, 5)
    assert refused.value.code == 'generation_finished'


def test_a_deck_changed_on_one_slide_by_ai_can_be_restructured_once_drawn(customer, stock_photos):  # noqa: F811
    original, _ = generate(customer)

    def selected_change():
        return create_draft(customer, {'prompt': 'Fix the typos on slide 2.', 'options': {
            'revise_draft_id': str(original.id), 'revise_section_ids': [CARDS], 'revise_base_version': original.version}})

    def restructured(content):
        cover, *rest = content['sections']
        content['sections'] = [cover, *reversed(rest), {**fixtures.light('bullets', 3), 'id': 'added-slide'}]

    selected = selected_change()
    assert run(customer, selected).status == 'succeeded'
    assert pins_of(selected)
    ids = [section['id'] for section in stored(selected)['content']['sections']]
    save_content(customer, selected, restructured)
    assert [section['id'] for section in stored(selected)['content']['sections']] == [ids[0], *reversed(ids[1:]), 'added-slide']
    assert pins_of(selected)

    # Before it is drawn, a change on one slide still keeps every slide where it is.
    undrawn = selected_change()
    content = copy.deepcopy(stored(undrawn)['content'])
    restructured(content)
    answer = patch(customer, undrawn, {'version': undrawn.version, 'content': content})
    assert answer.status_code == 400 and error(answer) == 'invalid_parameters'


def test_the_editors_saves_keep_the_pins_after_slides_are_added_and_removed(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    pins = pins_of(draft)
    lines = stored(draft)['options'].get('title_lines')
    assert pins['variants']
    changes = [lambda content: content['sections'].append({**fixtures.light('bullets', 3), 'id': 'added-slide'}),
               lambda content: content['sections'].pop(3),
               lambda content: content['sections'][1].update(heading='Only the heading changed')]
    for change in changes:
        save_content(customer, draft, change)
        data = stored(draft)
        ids = [section['id'] for section in data['content']['sections']]
        assert 'render' in draft_data(GenerationDraft.objects.get(pk=draft.pk))
        assert {key: value for key, value in pins_of(draft)['variants'].items() if key in ids} == {key: value for key, value in pins['variants'].items() if key in ids}
        assert data['options'].get('title_lines') == lines
        assert data['options']['length'] == len(ids) + data['options']['question_slides']
    assert stored(draft)['content']['sections'][1]['heading'] == 'Only the heading changed'

