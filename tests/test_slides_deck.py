"""What a generated deck must be: a deck, editable, and readable back.

The visual result is judged by opening one. These are the properties that can
be checked without eyes, and every one of them is something that was wrong
before: the count was not the count, the text did not reflow when edited, the
theme was stock Office, and the file carried a binary part the platform's own
uploader refuses.
"""
import zipfile

import pytest
from pptx import Presentation
from pptx.enum.text import MSO_AUTO_SIZE

from apps.studio import slides
from apps.studio.slides import bullets_of, contrast_ratio, palette, render_pptx

ACCENTS = ['#FFFFE0', '#000010', '#FF0000', '#808080', '#255e49', '#285CFF']


def deck(sections, title='Measured', questions=None):
    return {'title': title, 'questions': questions or [], 'citations': [],
            'sections': [{'id': f's{i + 1}', 'heading': heading, 'body': body, 'notes': f'Say {i + 1}.'}
                         for i, (heading, body) in enumerate(sections)]}


CONTENT = [
    ('Q3 Results', 'What changed, and what we do next.'),
    ('Revenue grew faster than costs', 'Revenue up 18 percent\nDelivery cost flat since April\nMargin widened again'),
    ('One number matters most', 'Net retention reached 118 percent'),
    ('Where the growth came from', 'Enterprise renewals held\nTwo public sector wins\nSelf-serve up\nChurn down\nPricing landed'),
    ('What we do next', ''),
]


@pytest.fixture
def built(tmp_path):
    path = tmp_path / 'deck.pptx'
    result = render_pptx(deck(CONTENT), path, style={'accent': '#255e49'})
    return path, result, Presentation(str(path))


# --------------------------------------------------------------- the file


def test_a_generated_deck_carries_no_binary_part(built):
    """The platform must be able to read back what it produced.

    `processors/engine.py` refuses any `.bin` member on upload, and python-pptx's
    bundled template ships printer settings. Without the strip, a customer
    re-uploading their own deck is told it contains active content.
    """
    path, _, _ = built
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        assert not [n for n in names if n.lower().endswith('.bin')], names
        assert not [n for n in names if any(x in n.lower() for x in ('vbaproject', 'activex', '/embeddings/'))]
        assert 'docProps/thumbnail.jpeg' not in names, 'a blank 4:3 preview for a 16:9 deck'
        for name in names:
            if name.endswith(('.xml', '.rels')):
                body = archive.read(name)
                assert b'<!DOCTYPE' not in body and b'<!ENTITY' not in body, name
                assert b'MACROENABLED' not in body.upper(), name
                if name.endswith('.rels'):
                    assert b'TargetMode="External"' not in body, name


def test_the_platform_can_read_back_the_deck_it_produced(built):
    """The real proof: run it through the same inspector an upload would."""
    from apps.core.services import engine_inspect
    path, result, _ = built
    checked = engine_inspect(path)
    assert checked['kind'] == 'pptx'
    assert checked['page_count'] == result['page_count'] == len(CONTENT)


# --------------------------------------------------------------- editable


def test_every_text_box_reflows_when_it_is_edited(built):
    """The old deck wrote one paragraph per wrapped line with wrapping off.

    Editing a line grew the box off the slide instead of rewrapping, which made
    "editable deck" untrue. Wrapping belongs to the viewer.
    """
    _, _, presentation = built
    frames = [shape.text_frame for slide in presentation.slides
              for shape in slide.shapes if shape.has_text_frame]
    assert frames
    # Decorative autoshapes carry an empty frame that inherits its wrapping;
    # every box that actually holds text must reflow, and none may be pinned off.
    for frame in frames:
        assert frame.word_wrap is not False, 'a frame that cannot rewrap breaks on edit'
        if frame.text.strip():
            assert frame.word_wrap is True
            assert frame.auto_size == MSO_AUTO_SIZE.NONE


def test_a_bullet_is_a_real_hanging_bullet(built):
    """One paragraph per bullet, with the glyph outside the text."""
    _, _, presentation = built
    body = presentation.slides[1].shapes[-1].text_frame
    assert len(body.paragraphs) == 3, 'one paragraph per bullet, not per wrapped line'
    for paragraph in body.paragraphs:
        xml = paragraph._p.xml
        assert 'buChar' in xml, xml
        assert 'indent="-' in xml, 'the glyph must hang outside the text'


# --------------------------------------------------------------- the look


def test_the_deck_carries_its_own_theme_not_office_stock(built):
    path, _, _ = built
    with zipfile.ZipFile(path) as archive:
        theme = archive.read('ppt/theme/theme1.xml').decode()
    assert '255E49' in theme, 'the accent reaches the theme'
    assert slides.HEADING_FONT in theme and slides.BODY_FONT in theme
    assert 'Calibri' not in theme, 'a deck that inherits Calibri reads as stock Office'


def test_the_theme_hook_is_pinned_to_the_library_it_was_written_against():
    """Guard: `blob` on a generic part is how the theme is rewritten."""
    from pptx import Presentation as New
    from pptx.opc.constants import RELATIONSHIP_TYPE as RT
    part = New().slide_masters[0].part.part_related_by(RT.THEME)
    assert hasattr(part, 'blob'), 'python-pptx==1.0.2 exposed a writable blob on the theme part'
    assert isinstance(type(part).blob, property) and type(part).blob.fset is not None


@pytest.mark.parametrize('accent', ['#FFE08A', '#101820', '#285CFF'])
def test_the_first_shape_is_the_accent_exactly_as_the_brand_supplied_it(tmp_path, accent):
    """A brand colour is not ours to correct.

    Text colours are darkened until they read; repainting the customer's own
    accent to win a contrast check would be worse than the check.
    """
    render_pptx(deck(CONTENT), tmp_path / 'branded.pptx', style={'accent': accent})
    presentation = Presentation(str(tmp_path / 'branded.pptx'))
    for slide in presentation.slides:
        assert str(slide.shapes[0].fill.fore_color.rgb) == accent.lstrip('#').upper()


@pytest.mark.parametrize('accent', ACCENTS)
def test_text_reads_against_its_background_whatever_the_accent(accent):
    roles = palette(accent)
    assert contrast_ratio(roles['ink'], roles['surface']) >= 7.0
    assert contrast_ratio(roles['muted'], roles['surface']) >= 4.5
    assert contrast_ratio(roles['accent_text'], roles['surface']) >= 4.5
    assert contrast_ratio(roles['on_accent'], roles['accent']) >= 3.0
    assert roles['accent'] == accent.lstrip('#').upper(), 'the brand colour is never adjusted'


# --------------------------------------------------------------- content


@pytest.mark.parametrize('body,expected,cut', [
    ('a\nb\nc', ['a', 'b', 'c'], False),
    ('- a\n• b\n1. c\n(d) x', ['a', 'b', 'c', 'x'], False),
    ('', [], False),
    ('\n'.join(f'line {n}' for n in range(12)), None, True),
])
def test_bullets_are_read_out_of_the_body_without_doubling_the_glyph(body, expected, cut):
    found, shortened = bullets_of(body)
    if expected is not None:
        assert found == expected
    assert shortened is cut
    assert not any(line[:1] in '•·-–—*‣' for line in found), found


def test_a_body_written_as_prose_still_becomes_a_deck():
    """Legacy drafts, local authoring and a model that ignored the brief."""
    prose = ('Revenue rose sharply this quarter. Costs stayed flat throughout. '
             'Margin widened for the third time. Retention reached a new high. '
             'The pipeline looks stronger than last year.')
    found, _ = bullets_of(prose)
    assert 2 <= len(found) <= 5, found
    assert found[0].startswith('Revenue rose')


# --------------------------------------------------------------- the count


@pytest.mark.parametrize('count', [1, 2, 3, 5, 9, 12])
def test_the_slide_count_is_the_section_count(tmp_path, count):
    """What was quoted is what is delivered. The cover is one of the slides."""
    sections = [(f'Heading {n}', f'point one\npoint two\npoint three') for n in range(count)]
    result = render_pptx(deck(sections), tmp_path / f'{count}.pptx')
    assert result['page_count'] == count


def test_a_deck_opens_with_a_title_slide_and_a_single_slide_does_not(tmp_path):
    render_pptx(deck(CONTENT), tmp_path / 'many.pptx')
    many = Presentation(str(tmp_path / 'many.pptx'))
    cover = [s.text_frame.text for s in many.slides[0].shapes if s.has_text_frame]
    assert any('Q3 Results' in text for text in cover)
    assert 'buChar' not in many.slides[0].shapes[-1].text_frame.paragraphs[0]._p.xml

    alone = render_pptx(deck([('Only slide', 'first point\nsecond point')]), tmp_path / 'one.pptx')
    one = Presentation(str(tmp_path / 'one.pptx'))
    assert alone['page_count'] == 1
    assert any('buChar' in paragraph._p.xml for shape in one.slides[0].shapes if shape.has_text_frame
               for paragraph in shape.text_frame.paragraphs), 'one slide has nothing to introduce'


def test_the_cover_carries_no_speaker_notes(built):
    """There is nothing for a presenter to say over a title slide."""
    _, _, presentation = built
    assert presentation.slides[0].notes_slide.notes_text_frame.text == ''
    assert presentation.slides[1].notes_slide.notes_text_frame.text == 'Say 2.'


@pytest.mark.parametrize('locale,needle', [('ru', 'Отчёт'), ('uz', 'O‘zgarish'), ('en', 'Change')])
def test_every_language_survives_into_the_deck(tmp_path, locale, needle):
    content = deck([(needle, 'birinchi\nikkinchi'), (f'{needle} again', 'bir\nikki')], title=needle)
    render_pptx(content, tmp_path / f'{locale}.pptx', locale=locale)
    presentation = Presentation(str(tmp_path / f'{locale}.pptx'))
    text = ' '.join(s.text_frame.text for slide in presentation.slides
                    for s in slide.shapes if s.has_text_frame)
    assert needle in text


# --------------------------------------------------------------- themes


@pytest.mark.parametrize('brief,theme,accent', [
    ('8 slides on Q3 results', None, None),
    ('a dark deck about tide tables', 'dark', None),
    ('10 slides in navy, minimal', 'light', '#16305C'),
    ('bold 6 slide pitch in burgundy', 'bold', '#6E1230'),
    ("qorong'i 8 ta slayd, ko'k rangda", 'dark', '#1F4E9C'),
    ('тёмная презентация на 10 слайдов, зелёный', 'dark', '#1E6B45'),
    ('a deck about the history of black holes', None, '#14171A'),
])
def test_the_look_is_read_out_of_the_description(brief, theme, accent):
    """There is no theme picker: the brief is the brief, in all three languages."""
    from apps.studio.pages import requested_accent, requested_theme
    assert requested_theme(brief) == theme
    assert requested_accent(brief) == accent


@pytest.mark.parametrize('theme', ['light', 'dark', 'bold'])
@pytest.mark.parametrize('accent', ACCENTS)
def test_text_reads_in_every_theme_whatever_the_accent(theme, accent):
    """An arbitrary accent on a dark ground is where a palette usually breaks."""
    roles = palette(accent, theme)
    assert contrast_ratio(roles['ink'], roles['surface']) >= 7.0
    assert contrast_ratio(roles['muted'], roles['surface']) >= 4.5
    assert contrast_ratio(roles['accent_text'], roles['surface']) >= 4.5
    # A cover is set at 44pt and 18pt, which is large text: AAA is 4.5:1 there,
    # where the 7:1 above applies to the body copy.
    assert contrast_ratio(roles['cover_ink'], roles['cover_fill']) >= 4.5
    assert contrast_ratio(roles['cover_muted'], roles['cover_fill']) >= 4.5
    assert contrast_ratio(roles['on_accent'], roles['accent']) >= 4.5
    assert contrast_ratio(roles['band_ink'], roles['band']) >= 4.5
    assert roles['accent'] == accent.lstrip('#').upper(), 'the brand colour is never adjusted'


@pytest.mark.parametrize('theme,dark_ground', [('light', False), ('dark', True), ('bold', False)])
def test_a_theme_actually_changes_the_deck(tmp_path, theme, dark_ground):
    from apps.studio.slides import _luminance
    render_pptx(deck(CONTENT), tmp_path / f'{theme}.pptx',
                style={'accent': '#1F4E9C', 'deck_theme': theme})
    presentation = Presentation(str(tmp_path / f'{theme}.pptx'))
    ground = str(presentation.slides[1].background.fill.fore_color.rgb)
    assert (_luminance(ground) < 0.2) is dark_ground, f'{theme} ground {ground}'
    # A bold deck puts the accent behind the cover; the others keep it quiet.
    cover = str(presentation.slides[0].background.fill.fore_color.rgb)
    assert (cover == '1F4E9C') is (theme == 'bold'), f'{theme} cover {cover}'


def test_branding_beats_a_colour_named_in_the_description(settings, tmp_path):
    """A brand colour is a fact about the customer, not a preference."""
    style = {'accent': '#16305C', 'deck_theme': 'dark'}
    # render_style puts the brand accent over whatever the description asked for.
    style_with_brand = {**style, 'accent': '#285CFF', 'brand_name': 'Acme'}
    render_pptx(deck(CONTENT), tmp_path / 'brand.pptx', style=style_with_brand)
    presentation = Presentation(str(tmp_path / 'brand.pptx'))
    assert str(presentation.slides[0].shapes[0].fill.fore_color.rgb) == '285CFF'
