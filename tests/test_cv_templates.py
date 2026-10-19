"""A CV wears one of fifty templates, fits one or two pages and reads back clean in every language."""
import io
import re
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image
from pypdf import PdfReader

from apps.core.errors import DomainError
from apps.studio.cv import check, fonts, portrait, sample, templates
from apps.studio.cv.render import filename, render_cv
from apps.studio.cv.templates import (CATEGORIES, DEFAULT_TEMPLATE, DRAWERS, FONT_PAIRS, PHOTO_DRAWERS, RETIRED,
                                      TEMPLATE_IDS, TEMPLATES, TONES, catalogue, current, look, reference, remember,
                                      wanted)
from apps.studio.scripts import artifact_violations
from apps.studio.slides import _hls, contrast_ratio

LOCALES = ('en', 'uz', 'ru')
SIDE_DRAWERS = ('sidebar_left', 'sidebar_right', 'band')


def render(tmp_path, key, content, locale='en', name='', **kwargs):
    path = tmp_path / f'{key}-{name}-{locale}.pdf'
    return path, render_cv(content, path, locale=locale, style={'cv_template': key}, **kwargs)


def hex6(value):
    return value.lstrip('#')


# ------------------------------------------------------------------ catalogue

def test_fifty_templates_in_six_categories_with_the_classic_default_first():
    assert len(TEMPLATES) == 50 and len(CATEGORIES) == 6
    assert list(CATEGORIES)[0] == 'classic' and TEMPLATE_IDS[0] == DEFAULT_TEMPLATE == 'classic_navy'
    signatures = set()
    for category, (members, names) in CATEGORIES.items():
        assert len(members) >= 8 and len(names) == 3 and all(names), category
        # Within a category every template is its own colour.
        assert len({value['accent'].upper() for value in members.values()}) == len(members), category
    for key, value in TEMPLATES.items():
        assert re.fullmatch(r'[a-z_]+', key) and value['category'] in CATEGORIES
        assert value['drawer'] in DRAWERS and value['fonts'] in FONT_PAIRS and value['tone'] in TONES, key
        assert len(value['fits']) <= 110, key
        signatures.add((value['drawer'], value['accent'], value['tint'], value['fonts'], value['photo'], value['tone']))
        accent = hex6(value['accent'])
        assert contrast_ratio(accent, 'FFFFFF') >= 4.5, key
        if value['tone'] == 'light' and value['tint']:
            assert contrast_ratio(accent, hex6(value['tint'])) >= 4.5, key
            assert contrast_ratio('1A1A1A', hex6(value['tint'])) >= 7, key
        if value['tone'] == 'dark':
            assert contrast_ratio('FFFFFF', hex6(look({'cv_template': key})['fill'])) >= 4.5, key
        if value['tone'] == 'paper':
            assert value['tint'] and _hls(hex6(value['tint']))[1] >= 0.9, key
        if value['photo']:
            assert value['drawer'] in PHOTO_DRAWERS, key
    assert len(signatures) == len(TEMPLATES), 'no two templates are the same look'
    assert {value['drawer'] for value in TEMPLATES.values()} == set(DRAWERS)
    assert all(old not in TEMPLATES and new in TEMPLATES for old, new in RETIRED.items())


def test_the_picker_gets_every_template_with_its_colours_and_a_versioned_preview():
    groups = catalogue('uz')
    assert [group['id'] for group in groups] == list(CATEGORIES)
    assert groups[0]['name'] == 'Klassik' and groups[-1]['name'] == 'Ilmiy va texnik'
    assert catalogue('ru')[4]['name'] == 'Для руководителей'
    entries = [entry for group in groups for entry in group['templates']]
    assert [entry['id'] for entry in entries] == TEMPLATE_IDS
    stamp = templates.version()
    assert re.fullmatch(r'[0-9a-f]{12}', stamp)
    navy = entries[0]
    assert navy == {'id': 'classic_navy', 'name': 'Classic Navy', 'category': 'classic', 'drawer': 'column',
                    'photo': False, 'tone': 'light',
                    'preview': f'/api/v1/studio/cv-templates/classic_navy.png?locale=uz&v={stamp}',
                    'fonts': {'heading': 'serif', 'body': 'sans'},
                    'colours': {'accent': '#1F3A68', 'secondary': '#B08D57', 'tint': '#FFFFFF', 'ink': '#1A1A1A',
                                'fill': '#1F3A68'}}
    assert next(entry for entry in entries if entry['id'] == 'boardroom_cv')['name'] == 'Boardroom CV'
    assert next(entry for entry in entries if entry['id'] == 'ocean_dark')['colours']['fill'] == '#0B3954'
    assert all(entry['preview'].startswith(f"/api/v1/studio/cv-templates/{entry['id']}.png?locale=uz&v=")
               for entry in entries)


def test_the_list_the_model_reads_is_grouped_small_and_names_the_default():
    plain, with_photo = reference(), reference(photo=True)
    assert len(plain) <= 4500 and len(with_photo) <= 4500
    assert 'Classic:\n- classic_navy:' in plain and 'Choose `classic_navy` unless' in plain
    assert '- azure_side: blue sidebar with photo and skills; IT, product, marketing (photo)' in plain
    assert 'prefer a template marked (photo)' in with_photo and 'prefer a template' not in plain
    assert all(f'- {key}:' in plain for key in TEMPLATE_IDS)


def test_a_brand_colour_replaces_the_accent_and_an_unknown_template_falls_back_to_the_default():
    assert look({})['id'] == look({'cv_template': 'nope'})['id'] == DEFAULT_TEMPLATE
    assert current('azure_side') == 'azure_side'
    shown = look({'cv_template': 'coral_band', 'accent': '#285CFF', 'accent_fixed': True})
    assert shown['accent'] == '#285CFF' and shown['secondary'] is None and shown['drawer'] == 'band'
    assert contrast_ratio('FFFFFF', hex6(shown['fill'])) >= 4.5
    # The template's own accent is not a choice anyone made for the CV.
    assert look({'cv_template': 'coral_band', 'accent': '#255e49'})['accent'] == '#9F1239'
    # A pale brand colour is darkened until it reads as text.
    pale = look({'cv_template': 'classic_navy', 'accent': '#FFE066', 'accent_fixed': True})
    assert contrast_ratio(hex6(pale['accent']), 'FFFFFF') >= 4.5


def test_the_model_chooses_once_and_a_pick_or_a_saved_choice_is_kept():
    data = {'output_format': 'pdf', 'options': {'template_style': {}}}
    assert wanted(data) and not wanted(data, first=8)
    assert not wanted({**data, 'feature_id': 'ai.pdf_topic'}) and wanted({**data, 'feature_id': 'ai.cv'})
    assert not wanted({**data, 'output_format': 'pptx'})
    remember(data, {'design': 'nope'})
    assert data['options']['template_style'] == {}
    remember(data, {'design': 'lab'})
    assert data['options']['template_style']['cv_template'] == 'lab' and not wanted(data)
    remember(data, {'design': 'onyx'})
    assert data['options']['template_style']['cv_template'] == 'lab'
    remember(data, {'design': 'onyx'}, replace=True)
    assert data['options']['template_style']['cv_template'] == 'onyx'
    change = {**data, 'revision': {'request': 'Fix a typo.', 'edit': {'redesign': False}}}
    assert not wanted(change)
    assert wanted({**data, 'revision': {'request': 'A new look.', 'edit': {'redesign': True}}})
    assert templates.chosen({'cv_template': 'lab'}) == 'lab'
    assert templates.chosen({'cv_template': 'auto'}) == templates.chosen({}) == ''


# ------------------------------------------------------------------ fonts

def test_both_families_are_bundled_and_draw_every_letter_a_cv_needs():
    names = fonts.internal_names()
    assert names == {'CVSans': 'NotoSans-Regular', 'CVSans-Bold': 'NotoSans-Bold', 'CVSans-Italic': 'NotoSans-Italic',
                     'CVSerif': 'NotoSerif-Regular', 'CVSerif-Bold': 'NotoSerif-Bold',
                     'CVSerif-Italic': 'NotoSerif-Italic'}
    wanted_codes = {ord(char) for char in fonts.GLYPHS}
    for face in fonts.FACES:
        assert fonts.path(face).is_file(), face
        assert wanted_codes <= fonts.coverage(face), face
    assert (fonts.FOLDER / 'NOTICE.txt').is_file() and (fonts.FOLDER / 'OFL.txt').is_file()


# ------------------------------------------------------------------ rendering

@pytest.mark.parametrize('key', TEMPLATE_IDS)
def test_every_template_renders_both_samples_in_every_language(key, tmp_path):
    for locale in LOCALES:
        for variant, pages in (('short', (1,)), ('long', (1, 2))):
            content = getattr(sample, variant)(locale)
            path, result = render(tmp_path, key, content, locale, variant,
                                  portrait=sample.portrait() if TEMPLATES[key]['photo'] else None)
            assert result['page_count'] in pages, (locale, variant, result['page_count'])
            assert result['metadata']['design'] == key and result['metadata']['layouts'] == [TEMPLATES[key]['drawer']]
            assert result['metadata']['dropped_chars'] == [] and result['metadata']['trimmed'] == []
            assert check.problems(path, result['metadata']['frames'], sample.required(content, locale)) == [], (
                locale, variant)
            assert artifact_violations(path, locale) == [], (locale, variant)


@pytest.mark.parametrize('key', ['azure_side', 'cobalt_right', 'circuit_dark', 'coral_band', 'lab'])
def test_a_crowded_side_column_moves_whole_groups_into_the_main_column(key, tmp_path):
    content = sample.crowded('uz')
    path, result = render(tmp_path, key, content, 'uz', portrait=sample.portrait())
    moved = result['metadata']['sidebar_moved']
    # Certificates leave first, then languages, then skills; contacts never do.
    assert moved and moved == ['certificates', 'languages', 'skills'][:len(moved)]
    assert result['page_count'] <= 2
    required = sample.required(content, 'uz')
    assert len([item for item in required if item]) >= 1 + 6 + 9 + 6
    assert check.problems(path, result['metadata']['frames'], required) == []


def test_portraits_appear_only_on_templates_with_a_place_for_one(tmp_path):
    for key in TEMPLATE_IDS:
        path, result = render(tmp_path, key, sample.short('en'), portrait=sample.portrait())
        images = sum(len(page.images) for page in PdfReader(path).pages)
        assert result['metadata']['portrait'] == TEMPLATES[key]['photo'] == (images == 1), key


def test_an_unreadable_portrait_leaves_the_cv_without_one(tmp_path):
    good = sample.portrait()
    assert portrait.square(b'\xff\xd8\xff\xe0 not really a jpeg') is None
    assert portrait.square(good[:len(good) // 3]) is None
    webp = io.BytesIO()
    Image.new('RGB', (300, 300), '#888888').save(webp, 'WEBP')
    assert portrait.square(webp.getvalue()) is None
    path, result = render(tmp_path, 'azure_side', sample.short('en'), portrait=b'\xff\xd8 broken')
    assert result['metadata']['portrait'] is False and result['metadata']['warnings'] == ['cv_photo_unusable']
    assert result['page_count'] == 1 and sum(len(page.images) for page in PdfReader(path).pages) == 0
    placed = portrait.square(good)
    assert placed and placed['width'] == placed['height'] <= 600 and len(placed['jpeg']) <= 250_000


def test_a_tall_photo_is_cropped_square_from_its_upper_part_and_keeps_no_metadata():
    tall = Image.new('RGB', (400, 1000), '#FFFFFF')
    tall.paste(Image.new('RGB', (400, 300), '#FF0000'), (0, 0))
    raw = io.BytesIO()
    exif = Image.Exif()
    exif[0x010E] = 'private description'
    tall.save(raw, 'JPEG', exif=exif)
    placed = portrait.square(raw.getvalue())
    image = Image.open(io.BytesIO(placed['jpeg']))
    assert image.size == (400, 400) and not image.getexif()
    # The square starts above the middle, where a face is, so the red top is in it.
    assert image.getpixel((200, 5))[0] > 200 and image.getpixel((200, 5))[1] < 80


def test_twelve_roles_are_trimmed_to_two_pages_and_keep_every_contact_and_role(tmp_path):
    content = sample.many_roles('en', 12)
    path, result = render(tmp_path, 'classic_navy', content)
    assert result['page_count'] <= 2 and result['shortened'] and result['metadata']['trimmed']
    assert result['metadata']['fit_step'] == 4
    assert check.problems(path, result['metadata']['frames'], sample.required(content, 'en')) == []
    text = ' '.join(page.extract_text() for page in PdfReader(path).pages)
    assert text.count('Head of Data Analytics') >= 2 + 1  # two roles of that title, plus the headline
    for organisation in ('Registon Retail Group', 'Tumaris Fintech', 'Bodomzor Logistics', 'Kamalak Telecom',
                         'Navruz Market Research'):
        assert organisation in text
    assert text.count('·') >= 12  # every role keeps its organisation line


def test_content_is_cleaned_rather_than_refused(tmp_path):
    content = {'title': 'Ali 😀 Valiyev', 'sections': [
        {'id': 'profile', 'heading': '🚀 Backend developer', 'body': 'Builds APIs.', 'items': [
            {'label': 'tel', 'text': '+998 90 000 00 00', 'value': ''}, {'label': 'email', 'text': '', 'value': ''}]},
        {'id': 'experience', 'heading': 'ignored', 'body': '', 'items': [
            {'label': 'Developer', 'value': '2020 – 2024',
             'text': 'Acme · Tashkent\n• Shipped the payments API\n- Cut response time by half\n* Mentored two juniors\n'
                     + 'Wrote the onboarding guide for new engineers and kept it ' + 'up ' * 200}]},
        {'id': 'skills', 'items': 'not a list'}, 'not a section',
        {'id': 'extra', 'heading': 'Interests', 'items': [{'label': 'Chess', 'text': '', 'value': ''}]},
    ]}
    path, result = render(tmp_path, 'classic_navy', content)
    assert result['metadata']['dropped_chars'] == ['😀', '🚀']
    text = PdfReader(path).pages[0].extract_text()
    assert 'Ali Valiyev' in text and 'Backend developer' in text and 'Phone' not in text
    assert 'EXPERIENCE' in text and 'ignored' not in text.lower() and 'INTERESTS' in text
    # The renderer draws its own bullets: the ones the model typed are gone, none doubled.
    assert text.count('•') == 4 and '• •' not in text and '- Cut' not in text and '* Mentored' not in text
    for line in ('Shipped the payments API', 'Cut response time by half', 'Mentored two juniors'):
        assert line in text
    assert check.problems(path, result['metadata']['frames'], ['Ali Valiyev', '+998 90 000 00 00']) == []
    for empty in ({}, {'title': 'Ali Valiyev'}, {'title': None, 'sections': [{'id': 'experience', 'items': [{}]}]}):
        assert render(tmp_path, 'azure_side', empty)[1]['page_count'] == 1


def test_a_field_cut_at_its_cap_loses_its_partial_last_word(tmp_path):
    from apps.studio.cv.render import prepare
    cut = ('Then: ' + 'led the migration of the reporting stack to a modern warehouse ' * 20)[:900]
    assert cut[-1].isalpha() and cut[-2].isalpha()
    cv, _ = prepare({'title': 'A B', 'sections': [{'id': 'projects', 'items': [
        {'label': 'Warehouse', 'text': cut, 'value': '2023'},
        {'label': 'Short', 'text': 'Ends with a full word', 'value': ''}]}]})
    kept = cv['sections'][0]['items'][0]['lines'][0]
    assert cut.startswith(kept) and len(kept) < 900 and cut[len(kept)] == ' '
    assert cv['sections'][0]['items'][1]['lines'] == ['Ends with a full word']


def test_headings_and_contact_labels_are_printed_in_the_cvs_language(tmp_path):
    for locale, words in (('uz', ('ISH TAJRIBASI', 'TAʼLIM', 'KO‘NIKMALAR', 'ALOQA', 'TELEFON')),
                          ('ru', ('ОПЫТ РАБОТЫ', 'ОБРАЗОВАНИЕ', 'НАВЫКИ', 'КОНТАКТЫ', 'ТЕЛЕФОН')),
                          ('en', ('EXPERIENCE', 'EDUCATION', 'SKILLS', 'CONTACT', 'PHONE'))):
        path, _ = render(tmp_path, 'azure_side', sample.short(locale), locale)
        text = PdfReader(path).pages[0].extract_text()
        assert all(word in text for word in words), (locale, [word for word in words if word not in text])


def test_the_pdf_names_the_person_and_the_file_is_named_after_them(tmp_path):
    path, result = render(tmp_path, 'classic_navy', sample.short('ru'), 'ru')
    meta = PdfReader(path).metadata
    assert meta['/Title'] == 'Дильноза Каримова — CV' and meta['/Author'] == 'Дильноза Каримова'
    assert meta['/Subject'] == 'Старший аналитик данных' and meta['/Creator'] == 'PDF Master'
    assert filename(sample.short('ru')) == 'Дильноза Каримова CV.pdf'
    assert filename({'title': 'O‘tkir Ne’matov <script>'}) == 'O‘tkir Ne’matov script CV.pdf'
    assert filename({'title': '***'}) == filename({}) == 'CV.pdf'
    assert len(filename({'title': 'Abdulaziz ' * 20})) <= 60


def test_thumbnails_are_480_wide_a4_pages(tmp_path):
    png = templates.thumbnail('azure_side', 'uz')
    image = Image.open(io.BytesIO(png))
    assert image.format == 'PNG' and image.width == 480 and abs(image.height - 679) <= 1


# ------------------------------------------------------------------ portrait validation

def upload(account, name, fmt, size=(400, 500)):
    from apps.core.services import upload_file
    raw = io.BytesIO()
    Image.new('RGB', size, '#8899AA').save(raw, fmt)
    return upload_file(account, SimpleUploadedFile(name, raw.getvalue(), f'image/{fmt.lower()}'))


@pytest.mark.django_db
def test_a_portrait_is_the_customers_own_jpeg_or_png_and_its_fingerprint_is_pinned():
    from tests.test_platform import account
    owner, stranger = account(), account(43)
    jpeg = upload(owner, 'me.jpg', 'JPEG')
    options = portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': str(jpeg.id), 'portrait_sha256': 'forged'})
    assert options == {'portrait_asset_id': str(jpeg.id), 'portrait_sha256': jpeg.sha256}
    png = upload(owner, 'me.png', 'PNG')
    assert portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': str(png.id)})['portrait_sha256'] == png.sha256
    webp = upload(owner, 'me.webp', 'WEBP')
    with pytest.raises(DomainError, match='invalid_image'):
        portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': str(webp.id)})
    with pytest.raises(DomainError, match='file_unavailable'):
        portrait.prepare(stranger, 'ai.cv', {'portrait_asset_id': str(jpeg.id)})
    with pytest.raises(DomainError, match='invalid_parameters'):
        portrait.prepare(owner, 'ai.pdf_topic', {'portrait_asset_id': str(jpeg.id)})
    with pytest.raises(DomainError, match='invalid_parameters'):
        portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': 7})
    huge = upload(owner, 'huge.png', 'PNG', size=(3000, 2100))
    with pytest.raises(DomainError, match='image_pixel_limit'):
        portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': str(huge.id)})
    assert portrait.prepare(owner, 'ai.pdf_topic', {'pages': 3}) == {'pages': 3}
    assert portrait.prepare(owner, 'ai.cv', {'cv_template': 'lab'}) == {'cv_template': 'lab'}


@pytest.mark.django_db
def test_a_change_keeps_the_portrait_drops_one_that_expired_and_removes_it_when_asked():
    from tests.test_platform import account
    owner = account()
    jpeg = upload(owner, 'me.jpg', 'JPEG')
    before = portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': str(jpeg.id)})
    assert portrait.prepare(owner, 'ai.cv', {}, before)['portrait_asset_id'] == str(jpeg.id)
    assert 'portrait_asset_id' not in portrait.prepare(owner, 'ai.cv', {}, before, portrait_removed=True)
    jpeg.expires_at = timezone.now() - timedelta(minutes=1)
    jpeg.save(update_fields=['expires_at'])
    gone = portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': str(jpeg.id)}, before)
    assert 'portrait_asset_id' not in gone and gone['cv_warnings'] == ['cv_photo_gone']
    # A new draft is refused instead: the customer has just sent that photo.
    with pytest.raises(DomainError, match='file_unavailable'):
        portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': str(jpeg.id)})


@pytest.mark.django_db
def test_the_portrait_is_read_again_at_render_time_and_a_changed_file_is_left_out():
    from apps.core.services import storage_path
    from tests.test_platform import account
    owner = account()
    jpeg = upload(owner, 'me.jpg', 'JPEG')
    options = portrait.prepare(owner, 'ai.cv', {'portrait_asset_id': str(jpeg.id)})
    placed, warnings = portrait.load(owner, {'options': options})
    assert placed and placed['width'] == placed['height'] and warnings == []
    assert portrait.load(owner, {'options': {}}) == (None, [])
    storage_path(jpeg.object_key).write_bytes(b'\xff\xd8 changed after the quote')
    assert portrait.load(owner, {'options': options}) == (None, ['cv_photo_unusable'])


# ------------------------------------------------------------------ endpoints

@pytest.mark.django_db
def test_the_catalogue_is_for_customers_and_the_previews_are_public_and_immutable():
    from django.test import Client
    from tests.test_platform import account, login_client
    assert Client().get('/api/v1/studio/cv-templates').status_code == 401
    client = login_client(account())
    found = client.get('/api/v1/studio/cv-templates?locale=ru').json()
    assert found['default'] == 'classic_navy' and found['categories'][0]['name'] == 'Классика'
    assert found['categories'][0]['templates'][0]['preview'].startswith('/api/v1/studio/cv-templates/classic_navy.png')
    assert client.get('/api/v1/studio/cv-templates?locale=xx').json()['categories'][0]['name'] == 'Classic'
    public = Client()
    response = public.get('/api/v1/studio/cv-templates/lab.png?locale=uz&v=1')
    assert response.status_code == 200 and response['Content-Type'] == 'image/png'
    assert response['Cache-Control'] == 'public, max-age=604800, immutable'
    assert Image.open(io.BytesIO(response.content)).width == 480
    assert public.get('/api/v1/studio/cv-templates/nope.png?locale=uz').status_code == 404
    assert public.get('/api/v1/studio/cv-templates/lab.png?locale=de').status_code == 404
