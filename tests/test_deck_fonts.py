"""A deck is measured in the faces LibreOffice draws it with, and only a deck gets them.

Nothing here runs LibreOffice: scripts/deploy/deck_samples.py prints what the real
one embeds on every pull request. What can be held on any machine is held here:
the files, the letters each face has, the widths, the fontconfig file, and that a
customer's own Word or PowerPoint file reaches soffice exactly as it did before.
"""
import functools
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
from pptx import Presentation
from pptx.util import Pt
from pypdf import PdfWriter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont, TTFontFace
from reportlab.pdfgen import canvas

from apps.studio import deck_designs, slides, variants
from apps.studio.slide_layouts import _text_lines
from apps.studio.slides import _face_units, _units, measured_in, render_pptx
from apps.studio.variants import fixtures
from processors import deck_fonts, engine, sandbox
from processors.deck_fonts import FILES, FOLDER, STAND_INS, stand_in, write_fontconfig
from processors.engine import office_runtime

SAMPLES = {'en': 'The team compared three approaches and chose the simplest one, because students could explain it.',
           'ru': 'Покажите две группы счётными предметами и посчитайте общее количество предметов на столе.',
           'uz': 'O‘quvchilar g‘oyani muhokama qiladi va natijani to‘liq gap bilan tushuntiradi: sa’y-harakat, oʻzbek.'}
UZBEK = '‘ʼ'
LATIN = ''.join(map(chr, range(0x20, 0x7f)))
CYRILLIC = ''.join(map(chr, range(0x410, 0x450))) + 'ЁёЎўҚқҒғҲҳ'


@functools.lru_cache(maxsize=None)
def widths(family, name=None):
    return TTFontFace(str(FOLDER / (name or FILES[family]))).charWidths


def look_of(heading, body):
    return {'heading_font': heading, 'body_font': body}


# ---------------------------------------------------------------- the files


def test_every_file_is_the_one_its_notice_records_with_its_licence():
    notice = (FOLDER / 'NOTICE.txt').read_text()
    recorded = dict((name, digest) for digest, name in re.findall(r'^  ([0-9a-f]{64})  (\S+\.ttf)$', notice, re.M))
    assert set(recorded) == {f'{stem}-{style}.ttf' for stem in ('Carlito', 'Caladea', 'LiberationSans') for style in ('Regular', 'Bold')}
    for name, digest in recorded.items():
        assert hashlib.sha256((FOLDER / name).read_bytes()).hexdigest() == digest, name
    for licence in ('OFL-Carlito.txt', 'OFL-Caladea.txt', 'OFL-LiberationSans.txt'):
        assert 'SIL OPEN FONT LICENSE' in (FOLDER / licence).read_text().upper(), licence


def test_the_vendored_faces_stay_small():
    added = sum((FOLDER / f'{stem}-{style}.ttf').stat().st_size for stem in ('Carlito', 'Caladea', 'LiberationSans') for style in ('Regular', 'Bold'))
    assert added < 2_500_000


def test_every_face_a_deck_can_name_has_a_stand_in_we_ship():
    assert deck_designs.FONTS | set(deck_designs.DEFAULT_FONTS) | {slides.HEADING_FONT, slides.BODY_FONT, slides.BULLET_FONT} == set(STAND_INS)
    for families in STAND_INS.values():
        for family in families:
            assert (FOLDER / FILES[family]).is_file()
            # What LibreOffice draws bold must exist too, or it would smear the regular.
            assert (FOLDER / FILES[family].replace('Regular', 'Bold')).is_file()


def test_the_bold_faces_keep_within_what_bold_is_measured_as():
    """Bold is Regular with an allowance of 6%, inside the safety margin: not more, in any language."""
    for family in FILES:
        regular, bold = widths(family), widths(family, FILES[family].replace('Regular', 'Bold'))
        for locale, sample in SAMPLES.items():
            fallback = widths('Noto Serif' if family == 'Caladea' else 'Noto Sans')
            fallback_bold = widths('Noto Serif', 'NotoSerif-Bold.ttf') if family == 'Caladea' else widths('Noto Sans', 'NotoSans-Bold.ttf')
            plain = sum(regular.get(ord(letter)) or fallback[ord(letter)] for letter in sample)
            heavy = sum(bold.get(ord(letter)) or fallback_bold[ord(letter)] for letter in sample)
            assert heavy <= plain * 1.06 * slides.WIDTH_SAFETY, (family, locale, heavy / plain)


# ---------------------------------------------------------------- the letters


@pytest.mark.parametrize('family', ['Carlito', 'Liberation Sans', 'Noto Sans', 'Noto Serif'])
def test_the_full_faces_have_every_letter_our_three_languages_use(family):
    letters = widths(family)
    assert not [letter for letter in LATIN + CYRILLIC + UZBEK if ord(letter) not in letters]


def test_caladea_lacks_cyrillic_and_its_fallback_has_it():
    letters = widths('Caladea')
    assert all(ord(letter) in letters for letter in LATIN + '‘')
    assert not any(ord(letter) in letters for letter in CYRILLIC + 'ʼ')
    assert stand_in('Cambria')[:2] == ('Caladea', 'Noto Serif')


def test_a_face_no_table_knows_is_measured_as_noto_sans_not_refused():
    assert stand_in('Comic Sans MS') == ('Noto Sans',)
    assert _face_units('Word', 'Comic Sans MS') == _face_units('Word', 'Trebuchet MS')


# ---------------------------------------------------------------- the widths


def test_calibri_is_measured_in_carlito_in_every_language():
    carlito = widths('Carlito')
    for sample in SAMPLES.values():
        assert _face_units(sample, 'Calibri') == pytest.approx(sum(carlito[ord(letter)] for letter in sample))


def test_a_cambria_heading_takes_each_letter_from_the_first_family_that_has_it():
    caladea, serif = widths('Caladea'), widths('Noto Serif')
    assert _face_units('Tides', 'Cambria') == sum(caladea[ord(letter)] for letter in 'Tides')
    assert _face_units('Приливы', 'Cambria') == pytest.approx(sum(serif[ord(letter)] for letter in 'Приливы'))
    mixed = 'Приливы, of'
    assert _face_units(mixed, 'Cambria') == pytest.approx(_face_units('Приливы', 'Cambria') + sum(caladea[ord(letter)] for letter in ', of'))
    assert _face_units('oʻzbek', 'Cambria') == pytest.approx(sum(caladea[ord(letter)] for letter in 'ozbek') + serif[0x2bc])


# The widest digit in each real face, Regular and Bold (Microsoft PowerPoint for Mac's own files, and macOS's Georgia and Trebuchet MS).
REAL_DIGITS = {'Calibri': (506.8, 506.8), 'Arial': (556.2, 556.2), 'Corbel': (524.4, 555.7), 'Candara': (551.8, 536.6), 'Cambria': (553.7, 592.3),
               'Trebuchet MS': (524.4, 585.9), 'Georgia': (613.8, 701.2), 'Constantia': (546.4, 577.1)}


def test_every_face_a_deck_can_name_has_its_real_digits_recorded():
    assert set(REAL_DIGITS) == set(STAND_INS)


@pytest.mark.parametrize('face', sorted(REAL_DIGITS))
def test_no_digit_of_the_real_face_outruns_the_margin_so_no_figure_does(face):
    regular, bold = REAL_DIGITS[face]
    for digit in '0123456789':
        assert regular <= _face_units(digit, face) * slides.WIDTH_SAFETY, digit
        assert bold <= _face_units(digit, face) * slides.WIDTH_SAFETY * 1.06, digit


def test_cambria_figures_are_measured_as_wide_as_cambria_draws_them_and_not_as_caladea():
    assert widths('Caladea')[ord('1')] == 362
    for number in ('0123456789', '1 111', '118%', 'Q3 2021', '420', '2019'):
        digits = sum(letter.isdigit() for letter in number)
        others = sum(widths('Caladea')[ord(letter)] for letter in number if not letter.isdigit())
        assert _face_units(number, 'Cambria') == 554 * digits + others, number
    # In Russian too, where the letters beside them come from another family.
    assert _face_units('Приливы 2019', 'Cambria') == pytest.approx(_face_units('Приливы', 'Cambria') + widths('Caladea')[ord(' ')] + 4 * 554)
    # What LibreOffice draws is untouched, so a face with no floor measures as its file.
    assert _face_units('2019', 'Calibri') == sum(widths('Carlito')[ord(letter)] for letter in '2019')


@pytest.mark.parametrize('text, size, box, bold', [('118%', 40, 98.3, False), ('420', 44, 72, False), ('Q3 2021', 20, 72, False), ('Q3 2021', 18, 68.5, True)])
def test_a_figure_real_cambria_breaks_in_its_box_does_not_pass_as_fitting(text, size, box, bold):
    """Boxes of the variants that passed their trial on Caladea's digits: stats.circles, chart.stepped_rows, timeline.two_rows, timeline.vertical."""
    with measured_in(look_of('Cambria', 'Corbel')):
        assert _text_lines(text, size, Pt(box), bold=bold, heading=True) > 1, text


def test_a_letter_no_family_has_is_given_a_width_and_not_an_error():
    assert _face_units('\U0001F600', 'Calibri') > 0


@pytest.mark.parametrize('face, family', [('Calibri', 'Carlito'), ('Arial', 'Liberation Sans'), ('Trebuchet MS', 'Noto Sans'), ('Georgia', 'Noto Serif')])
def test_a_face_with_every_letter_measures_as_its_own_file_on_any_machine(face, family):
    letters = widths(family)
    assert _face_units(SAMPLES['ru'], face) == pytest.approx(sum(letters[ord(letter)] for letter in SAMPLES['ru']))


def test_a_deck_is_measured_in_its_own_design_and_only_while_it_is_drawn():
    text = SAMPLES['ru']
    assert _units(text, heading=False) == _face_units(text, slides.BODY_FONT)
    assert _units(text, heading=True) == _face_units(text, slides.HEADING_FONT)
    with measured_in(look_of('Arial', 'Georgia')):
        assert _units(text, heading=True) == _face_units(text, 'Arial')
        assert _units(text, heading=False) == _face_units(text, 'Georgia')
    assert _units(text, heading=False) == _face_units(text, slides.BODY_FONT)


def test_text_whose_face_nobody_named_gets_the_wider_of_the_two():
    text = SAMPLES['ru']
    assert _face_units(text, 'Cambria') > _face_units(text, 'Calibri') * 1.1
    with measured_in(look_of('Cambria', 'Calibri')):
        assert _units(text) == _face_units(text, 'Cambria')
    with measured_in(look_of('Calibri', 'Cambria')):
        assert _units(text) == _face_units(text, 'Cambria')


def test_a_russian_cambria_heading_is_counted_in_its_fallback_and_its_body_in_calibri():
    """The widest gap between a deck's two faces: read as one, a heading would overflow or a body would be cut."""
    text = ' '.join([SAMPLES['ru']] * 4)
    width = Pt(460)
    with measured_in(look_of('Cambria', 'Calibri')):
        assert _text_lines(text, 20, width, heading=True) > _text_lines(text, 20, width, heading=False)


def test_the_deck_size_is_taken_in_the_decks_own_body_face(tmp_path):
    section = {**fixtures.section('bullets', fixtures.RANGES['bullets'][1], 'ru'), 'layout': 'bullets', 'id': 's1'}
    deck = {'title': 'T', 'questions': [], 'citations': [], 'sections': [{**fixtures.section('statement', 1, 'ru'), 'layout': 'cover', 'id': 's0'}, section]}
    # Bullet lists at the size their face allows: the narrow one sets larger, or the same, never smaller.
    narrow = render_pptx(deck, tmp_path / 'a.pptx', locale='ru', style={'deck_design': 'boardroom'})['metadata']['body_size']   # Calibri
    wide = render_pptx(deck, tmp_path / 'b.pptx', locale='ru', style={'deck_design': 'classroom'})['metadata']['body_size']   # Trebuchet MS
    assert narrow >= wide


def test_a_decks_faces_end_with_its_drawing_even_when_that_fails():
    before = _units('Приливы')
    with pytest.raises(RuntimeError), measured_in(look_of('Arial', 'Arial')):
        raise RuntimeError
    assert _units('Приливы') == before


# ---------------------------------------------------------------- the pins


real_units = slides._face_units


def old_widths(text, face):
    """What every face was measured as until this change: Noto Sans, which is Trebuchet MS's stand-in."""
    return real_units(text, 'Trebuchet MS')


@pytest.mark.parametrize('locale', fixtures.LOCALES)
def test_a_deck_pinned_before_the_fonts_changed_keeps_its_pins_or_says_so(locale, tmp_path, monkeypatch):
    sections = [{**fixtures.section('statement', 1, locale), 'layout': 'cover', 'id': 's0'}]
    sections += [{**fixtures.section(kind, fixtures.RANGES[kind][1], locale), 'id': f's{number}'} for number, kind in enumerate(variants.KINDS, 1) if not kind.startswith('image')]
    deck = {'title': 'Harbour', 'questions': [], 'citations': [], 'sections': sections}
    for design in ('boardroom', 'forest', 'midnight'):
        with monkeypatch.context() as patched:
            patched.setattr(slides, '_face_units', old_widths)
            drawn = render_pptx(deck, tmp_path / 'old.pptx', locale=locale, style={'deck_design': design})['metadata']
        pins = {'design': drawn['design'], 'deck_seed': drawn['deck_seed'], 'body_size': drawn['body_size'],
                'variants': {section['id']: variant for section, variant in zip(sections, drawn['variants'])}}
        again = render_pptx(deck, tmp_path / 'new.pptx', locale=locale, style={'deck_design': design}, pins=pins)['metadata']
        assert again['body_size'] == drawn['body_size'], design
        moved = {section['id'] for section, before, after in zip(sections, drawn['variants'], again['variants']) if before != after}
        assert moved == set(again['repinned']), design


def test_the_renderer_version_covers_what_a_drawing_depends_on(monkeypatch):
    studio = Path(deck_designs.__file__).parent
    # Noto measures every Russian Cambria heading and all Georgia, and NOTICE.txt records no sum for it.
    assert {'NotoSans-Regular.ttf', 'NotoSerif-Regular.ttf', 'NotoSans-Bold.ttf', 'NotoSerif-Bold.ttf', 'Carlito-Bold.ttf'} <= {path.name for path in deck_fonts.font_files()}
    first = deck_designs.version()
    read = Path.read_bytes
    for changed in (studio / 'slide_layouts.py', studio / 'variants' / 'kit.py', studio / 'variants' / 'cards_1.py', studio / 'layouts.py',
                    studio / 'slides.py', studio / 'compositions' / 'classic.py', Path(deck_fonts.__file__), *deck_fonts.font_files()):
        with monkeypatch.context() as patched:
            patched.setattr(Path, 'read_bytes', lambda path, target=changed: read(path) + (b'#' if path == target else b''))
            assert deck_designs.version() != first, changed
    assert deck_designs.version() == first


# ---------------------------------------------------------------- the pull request's samples


def samples():
    spec = importlib.util.spec_from_file_location('deck_samples', Path(__file__).resolve().parent.parent / 'scripts/deploy/deck_samples.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_samples_read_the_fonts_a_pdf_embeds(tmp_path):
    pdfmetrics.registerFont(TTFont('SampleCarlito', str(FOLDER / 'Carlito-Regular.ttf')))
    page = canvas.Canvas(str(tmp_path / 'made.pdf'))
    page.setFont('SampleCarlito', 12)
    page.drawString(50, 50, 'Tides')
    page.save()
    assert 'Carlito-Regular' in samples().fonts_in(tmp_path / 'made.pdf')


@pytest.mark.parametrize('locale', ['en', 'ru', 'uz'])
def test_the_samples_are_made_up_decks_every_design_named_can_draw(locale, tmp_path):
    module = samples()
    for design in module.DESIGNS:
        assert design is None or design in deck_designs.DESIGNS
    module.draw(module.DESIGNS[1], locale, tmp_path / 'deck.pptx')
    assert len(Presentation(str(tmp_path / 'deck.pptx')).slides) == 1 + len(module.KINDS)


# ---------------------------------------------------------------- what soffice is given


def test_the_fontconfig_file_adds_our_folder_to_the_systems_and_stays_in_its_scratch(tmp_path):
    path = write_fontconfig(tmp_path)
    assert path.parent == tmp_path
    root = ElementTree.parse(path).getroot()
    assert root.tag == 'fontconfig'
    assert [node.text for node in root.findall('dir')] == [str(FOLDER)]
    assert root.find('include').text == '/etc/fonts/fonts.conf' and root.find('include').get('ignore_missing') == 'yes'
    assert root.find('cachedir').text == str(tmp_path / 'fontconfig')
    aliases = {alias.find('family').text: (alias.get('binding'), [node.text for node in alias.find('prefer') or []]) for alias in root.findall('alias') if alias.find('prefer') is not None}
    assert aliases == {face: ('same', list(families)) for face, families in STAND_INS.items()}
    fallbacks = {alias.find('family').text: [node.text for node in alias.find('accept')] for alias in root.findall('alias') if alias.find('accept') is not None}
    assert fallbacks['Caladea'][0] == 'Noto Serif' and fallbacks['Carlito'] == ['Noto Sans']


def test_a_path_with_a_mark_xml_gives_meaning_to_stays_a_path(tmp_path, monkeypatch):
    monkeypatch.setattr(deck_fonts, 'FOLDER', Path('/opt/a&b/<fonts>'))
    root = ElementTree.parse(write_fontconfig(tmp_path)).getroot()
    assert root.find('dir').text == '/opt/a&b/<fonts>'


@pytest.mark.skipif(not shutil.which('fc-match'), reason='fontconfig is not installed')
@pytest.mark.parametrize('asked, family, style', [
    ('Calibri', 'Carlito', 'Regular'), ('Calibri:bold', 'Carlito', 'Bold'), ('Corbel', 'Carlito', 'Regular'), ('Candara', 'Carlito', 'Regular'),
    ('Arial', 'Liberation Sans', 'Regular'), ('Arial:bold', 'Liberation Sans', 'Bold'), ('Trebuchet MS', 'Noto Sans', 'Regular'),
    ('Cambria', 'Caladea', 'Regular'), ('Cambria:bold', 'Caladea', 'Bold'), ('Georgia', 'Noto Serif', 'Regular'), ('Constantia', 'Noto Serif', 'Regular'),
    # How LibreOffice asks for a letter the face lacks: by the face, and the letter.
    ('Cambria:charset=0416', 'Noto Serif', 'Regular'), ('Cambria:bold:charset=0416', 'Noto Serif', 'Bold'),
    ('Caladea:charset=0416', 'Noto Serif', 'Regular'), ('Caladea:charset=2bc', 'Noto Serif', 'Regular'),
    ('Calibri:charset=0416', 'Carlito', 'Regular'),
])
def test_fontconfig_itself_finds_what_the_measure_assumes(asked, family, style, tmp_path):
    env = {**os.environ, 'FONTCONFIG_FILE': str(write_fontconfig(tmp_path)), 'HOME': str(tmp_path)}
    found = subprocess.run(['fc-match', asked, 'family', 'style'], env=env, capture_output=True, text=True, timeout=60, check=True).stdout
    assert found.startswith(f'{family}:style={style}'), found


def soffice_that_reports(tmp_path):
    """A stand-in LibreOffice in the real child: it writes down what it was given and leaves a PDF."""
    writer = PdfWriter()
    writer.add_blank_page(width=960, height=540)
    writer.write(tmp_path / 'made.pdf')
    binary = tmp_path / 'soffice'
    binary.write_text(f'''#!/bin/sh
if [ "$1" = "--version" ]; then echo "LibreOffice 24.2.0"; exit 0; fi
env > "{tmp_path}/env.txt"
echo "$@" > "{tmp_path}/args.txt"
while [ $# -gt 1 ]; do
  if [ "$1" = "--outdir" ]; then folder="$2"; fi
  shift
done
if [ -n "$FONTCONFIG_FILE" ]; then cp "$FONTCONFIG_FILE" "{tmp_path}/fonts.conf"; fi
cp "{tmp_path}/made.pdf" "$folder/input.pdf"
''')
    binary.chmod(0o755)
    return binary


@pytest.fixture
def reporting_office(tmp_path, monkeypatch):
    monkeypatch.setenv('DOCMASTER_SOFFICE_BIN', str(soffice_that_reports(tmp_path)))
    office_runtime.cache_clear()
    yield
    monkeypatch.delenv('DOCMASTER_SOFFICE_BIN')
    office_runtime.cache_clear()


def a_deck(tmp_path):
    deck = Presentation()
    deck.slides.add_slide(deck.slide_layouts[6])
    slides.strip_binary_parts(deck)
    deck.save(tmp_path / 'deck.pptx')
    return tmp_path / 'deck.pptx'


def given(tmp_path):
    return dict(line.split('=', 1) for line in (tmp_path / 'env.txt').read_text().splitlines() if '=' in line)


def test_a_customers_powerpoint_reaches_soffice_with_no_font_setting(tmp_path, reporting_office):
    done = sandbox.execute_sandbox('convert.pptx_to_pdf', [a_deck(tmp_path)], {}, tmp_path / 'out')
    assert done['artifacts'][0]['page_count'] == 1
    environment = given(tmp_path)
    assert not [name for name in environment if name.startswith(('FONTCONFIG', 'FC_', 'XDG_DATA'))]
    assert not (tmp_path / 'fonts.conf').exists()


def test_a_font_setting_in_the_workers_environment_does_not_reach_a_customers_file(tmp_path, reporting_office, monkeypatch):
    monkeypatch.setenv('FONTCONFIG_FILE', '/somewhere/else.conf')
    sandbox.execute_sandbox('convert.pptx_to_pdf', [a_deck(tmp_path)], {}, tmp_path / 'out')
    assert 'FONTCONFIG_FILE' not in given(tmp_path)


def test_a_customer_cannot_ask_for_the_deck_faces_in_their_parameters(tmp_path, reporting_office):
    with pytest.raises(engine.ProcessorError):
        sandbox.execute_sandbox('convert.pptx_to_pdf', [a_deck(tmp_path)], {'deck_fonts': True}, tmp_path / 'out')


def test_a_deck_of_ours_gets_the_deck_faces_in_its_own_scratch(tmp_path, reporting_office):
    sandbox.execute_sandbox('convert.pptx_to_pdf', [a_deck(tmp_path)], {}, tmp_path / 'out', deck_fonts=True)
    environment = given(tmp_path)
    scratch = Path(environment['HOME'])
    assert Path(environment['FONTCONFIG_FILE']) == scratch / 'deck-fonts.conf'
    assert '<family>Carlito</family>' in (tmp_path / 'fonts.conf').read_text()
    # A profile and a font cache of its own, gone with the conversion: nothing carries over to a customer's.
    assert f'-env:UserInstallation={(scratch / "profile").as_uri()}' in (tmp_path / 'args.txt').read_text()
    assert str(scratch / 'fontconfig') in (tmp_path / 'fonts.conf').read_text()
    assert not scratch.exists()
    assert not list((tmp_path / 'out').glob('**/deck-fonts.conf'))
