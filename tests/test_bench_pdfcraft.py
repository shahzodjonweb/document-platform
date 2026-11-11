"""The PdfCraft bench groups by a fixed list of generators and prints counts, never a document's text."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

import numpy
import pytest
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/bench_pdfcraft.py'
spec = importlib.util.spec_from_file_location('docmaster_bench_pdfcraft', SCRIPT)
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
REQUIRES_PDFCRAFT = pytest.mark.skipif(not os.environ.get('DOCMASTER_PDFCRAFT_BIN'), reason='needs DOCMASTER_PDFCRAFT_BIN')


def letters(text, font='arial', width=5.0):
    return [bench.Letter(char, 0, 0, width, font) for char in text]


@pytest.mark.parametrize(('producer', 'creator', 'expected'), [
    ('Skia/PDF m156', 'Mozilla/5.0 HeadlessChrome/156.0.0.0', 'chrome'),
    ('Skia/PDF m118 Google Docs Renderer', None, 'google-docs'),
    ('ReportLab PDF Library - (opensource)', 'anonymous', 'reportlab'),
    ('LibreOffice 7.4', 'Impress', 'libreoffice'),
    ('macOS Version 26.3.1 (Build 25D2128) Quartz PDFContext', None, 'quartz'),
    ('Microsoft® Word for Microsoft 365', 'Microsoft® Word for Microsoft 365', 'word'),
    (None, None, 'unknown'),
    ('Dilnoza Karimova', 'Her private scanner', 'other'),
])
def test_metadata_only_ever_becomes_a_fixed_class_name(producer, creator, expected):
    assert bench.generator_of(producer, creator) == expected


@pytest.mark.parametrize(('font', 'expected'), [
    ('ABCDEF+ArialMT', 'arial'), ('Arial-BoldMT', 'arial'), ('TimesNewRomanPS-BoldMT', 'timesnewroman'), ('NotoSans-Regular', 'notosans'), ('', ''),
])
def test_the_font_family_ignores_subset_and_style(font, expected):
    assert bench.family(font) == expected


def test_a_stand_in_is_a_near_twin_and_nothing_else():
    assert bench.close('arial', {'arial'})
    assert bench.close('helvetica', {'arial'})
    assert bench.close('times', {'timesnewroman'})
    assert not bench.close('helvetica', {'notosans'})
    assert not bench.close('', {'notosans'})


def test_the_new_letters_fault_separates_one_or_two_letters_from_a_changed_word():
    sources = {'notosans'}
    assert bench.new_letters_fault({'notosans': 9}, sources) is None
    assert bench.new_letters_fault({'notosans': 8, '': 1}, sources) == 'letters'
    assert bench.new_letters_fault({'': 9}, sources) == 'font'
    assert bench.new_letters_fault({'': 2}, sources) == 'font'
    assert bench.new_letters_fault({'notoserif': 9}, {'timesnewroman'}, {'notoserif'}) is None


def test_a_word_is_changed_in_the_last_row_and_the_row_breaks_stay():
    paragraph = {'editor_text': 'Договор поставки\nпридёт в Ташкент до конца месяца', 'text': 'Договор поставки придёт в Ташкент до конца месяца'}
    (scenario, new_text, new_letters, at), = bench.cases('body', paragraph, 'Самарканд')
    assert scenario == 'word'
    assert new_text == 'Договор поставки\nпридёт в Самарканд до конца месяца'
    assert new_text[at:at + len(new_letters)] == new_letters == 'Самарканд'


def test_a_number_keeps_its_length_and_a_cell_becomes_sevens():
    paragraph = {'editor_text': 'Договор 2025 года', 'text': 'Договор 2025 года'}
    cases = {case[0]: case for case in bench.cases('body', paragraph, 'Самарканд')}
    assert cases['number'][1:3] == ('Договор 7777 года', '7777')
    assert bench.cases('cell', {'editor_text': '12 500', 'text': '12 500'}, 'x') == [('number', '77 777', '77 777', 0)]


def test_the_picks_take_the_longest_body_the_shortest_a_short_one_and_a_number():
    paragraphs = [{'text': 'x' * 80}, {'text': 'y' * 70}, {'text': 'z' * 60}, {'text': 'Заголовок'}, {'text': '1 250'}]
    assert [(kind, item['text'][:1]) for kind, item in bench.picks(paragraphs)] == [('body', 'x'), ('body2', 'z'), ('short', 'З'), ('cell', '1')]


def test_stretch_compares_a_kept_row_letter_for_letter():
    assert bench.stretch_of(['Договор поставки'], ['Договор поставки'], letters('Договорпоставки'), letters('Договорпоставки', width=6.0)) == pytest.approx(1.2)
    # A row too short to tell is left out.
    assert bench.stretch_of(['Итог'], ['Итог'], letters('Итог'), letters('Итог', width=6.0)) == 1.0


def test_stretch_compares_a_changed_row_only_by_the_same_letter_in_the_same_font():
    old, new = letters('Ташкент'), letters('Самарканд', width=5.5)
    assert bench.stretch_of(['Ташкент'], ['Самарканд'], old, new) == pytest.approx(1.1)
    assert bench.stretch_of(['Ташкент'], ['Самарканд'], old, letters('Самарканд', font='', width=9.0)) == 1.0


BOX = [90, 90, 500, 140]
OLD = ['Стороны договорились о поставке', 'придёт в Ташкент до конца месяца']
NEW = ['Стороны договорились о поставке', 'придёт в Самарканд до конца месяца']


def read_as(rows, elsewhere=''):
    """A page as judge sees it: these rows inside BOX, that text far below it."""
    found = bench.Reading.__new__(bench.Reading)
    found.width, found.height, found.pixels = 595, 842, numpy.zeros((8, 8, 3), dtype=int)
    lines = [(100 + 16 * number, row) for number, row in enumerate(rows)] + [(700, elsewhere)]
    found.letters = [bench.Letter(char, 100 + 5 * column, top, 5.0, 'arial') for top, line in lines for column, char in enumerate(bench.norm(line))]
    found.pdfium = found.pypdf = ''.join(letter.char for letter in found.letters)
    return found


def judged(old, new, new_letters, after, elsewhere='', box=BOX, before=None):
    paragraph = {'paragraph': 1, 'rect': box, 'text': ' '.join(old), 'editor_text': '\n'.join(old), 'font': 'Arial'}
    return bench.judge(read_as(old if before is None else before, elsewhere), read_as(after, elsewhere), paragraph, [paragraph], box, '\n'.join(new), new_letters)


def test_an_edit_that_reads_right_in_its_box_has_no_fault():
    assert judged(OLD, NEW, 'Самарканд', NEW) == set()


def test_the_new_word_elsewhere_on_the_page_does_not_stand_in_for_the_box():
    assert judged(OLD, NEW, 'Самарканд', OLD, elsewhere='Филиал в Самарканд') == {'text'}
    assert judged(['Договор 12 марта'], ['Договор 77 марта'], '77', ['Договор 12 марта'], elsewhere='Основан в 1977') == {'text'}


def test_a_new_word_dropped_from_its_row_is_a_text_fault():
    assert judged(OLD, NEW, 'Самарканд', [OLD[0], 'придёт в до конца месяца'], elsewhere='Филиал в Самарканд') == {'text'}


def test_a_row_lost_from_the_box_is_a_text_fault():
    assert judged(OLD, NEW, 'Самарканд', NEW[1:]) == {'text'}


def test_the_old_row_left_beside_the_new_one_is_a_text_fault():
    assert judged(OLD, NEW, 'Самарканд', [*OLD, NEW[1]]) == {'text'}


def test_a_row_repeated_inside_another_is_not_taken_for_the_old_one_left_behind():
    old, new = ['Ташкент и Бухара', 'Ташкент'], ['Ташкент и Бухара', 'Самарканд']
    assert judged(old, new, 'Самарканд', new) == set()


@pytest.mark.parametrize(('old', 'word'), [('mark', 'Samarkand'), ('kand', 'Samarkand'), ('марка', 'Самарканд'), ('Самар', 'Самарканд'), ('марқа', 'Самарқанд'), ('Samar', 'Samarqand'), ('qand', 'Samarqand')])
def test_a_row_the_new_word_contains_is_not_taken_for_the_old_one_left_behind(old, word):
    assert bench.cases('short', {'text': old}, word) == [('word', word, word, 0)]
    assert judged([old], [word], word, [word]) == set()
    assert judged([old], [word], word, [old, word]) == {'text'}
    assert judged([old], [word], word, [old], elsewhere=word) == {'text'}


def test_a_last_row_the_new_word_contains_still_has_to_go():
    top = 'Рабочий лист для класса'
    assert judged([top, 'марка'], [top, 'Самарканд'], 'Самарканд', [top, 'Самарканд']) == set()
    assert judged([top, 'марка'], [top, 'Самарканд'], 'Самарканд', [top, 'марка', 'Самарканд']) == {'text'}
    # A second copy of it elsewhere in the box stays, and hides neither result.
    assert judged(['марка', 'марка'], ['марка', 'Самарканд'], 'Самарканд', ['марка', 'Самарканд']) == set()
    assert judged(['марка', 'марка'], ['марка', 'Самарканд'], 'Самарканд', ['марка', 'марка', 'Самарканд']) == {'text'}


def test_a_box_that_already_said_the_new_word_still_has_to_change():
    old, new = ['Samarkand', 'mark'], ['Samarkand', 'Samarkand']
    assert judged(old, new, 'Samarkand', new) == set()
    assert judged(old, new, 'Samarkand', old) == {'text'}
    assert judged(old, new, 'Samarkand', [*old, new[1]]) == {'text'}


def test_an_old_row_that_contains_the_new_word_still_has_to_go():
    assert judged(['Самарканда'], ['Самарканд'], 'Самарканд', ['Самарканд']) == set()
    assert judged(['Самарканда'], ['Самарканд'], 'Самарканд', ['Самарканда']) == {'text'}
    assert judged(['Самарканда'], ['Самарканд'], 'Самарканд', ['Самарканда', 'Самарканд']) == {'text'}


def test_a_row_pdfium_could_not_read_before_the_edit_says_nothing():
    # PdfCraft reads "ff" where pdfium reads the ligature, before the edit and after it.
    assert judged(['office 12 days'], ['office 77 days'], '77', ['oﬀice 77 days'], before=['oﬀice 12 days']) == set()
    # The new letters still have to be in the box when another row of it read.
    old, new, read = ['office 12 days', 'Договор поставки'], ['office 77 days', 'Договор поставки'], ['oﬀice 12 days', 'Договор поставки']
    assert judged(old, new, '77', read, elsewhere='Основан в 1977', before=read) == {'text'}


def test_a_box_that_does_not_line_up_with_the_letters_says_nothing():
    # A rotated page, say: nothing of the paragraph is in its box, or a blank row is all that "reads" there.
    assert judged(OLD, NEW, 'Самарканд', NEW, box=[300, 300, 500, 340]) == set()
    assert judged(['', *OLD], ['', *NEW], 'Самарканд', ['', *NEW], box=[300, 300, 500, 340]) == set()


def drawn(path, *lines):
    pdfmetrics.registerFont(TTFont('BenchNoto', str(ROOT / 'processors/assets/fonts/NotoSans-Regular.ttf')))
    drawing = canvas.Canvas(str(path), pagesize=(595, 842))
    drawing.setFont('BenchNoto', 12)
    for top, line in lines:
        drawing.drawString(72, top, line)
    drawing.save()
    return bench.Reading(path)


def test_on_a_real_page_only_the_box_counts(tmp_path):
    elsewhere = (300, 'Филиал в городе Самарканд')
    was = drawn(tmp_path / 'was.pdf', (730, OLD[0]), (714, OLD[1]), elsewhere)
    edited = drawn(tmp_path / 'edited.pdf', (730, NEW[0]), (714, NEW[1]), elsewhere)
    lost = drawn(tmp_path / 'lost.pdf', (714, NEW[1]), elsewhere)
    paragraph = {'paragraph': 1, 'rect': [70, 98, 560, 132], 'text': ' '.join(OLD), 'editor_text': '\n'.join(OLD), 'font': 'NotoSans'}
    faults = {name: bench.judge(was, after, paragraph, [paragraph], paragraph['rect'], '\n'.join(NEW), 'Самарканд') for name, after in (('none', was), ('edited', edited), ('lost', lost))}
    assert 'text' in faults['none'] and 'text' in faults['lost'] and 'text' not in faults['edited']


def page(path):
    pdfmetrics.registerFont(TTFont('BenchNoto', str(ROOT / 'processors/assets/fonts/NotoSans-Regular.ttf')))
    drawing = canvas.Canvas(str(path), pagesize=(595, 842))
    drawing.setFont('BenchNoto', 12)
    for top, line in ((770, 'Договор поставки учебников'), (730, 'Стороны договорились, что поставка книг и тетрадей обязательно состоится'), (714, 'и придёт в Ташкент до конца этого месяца 2025 года.')):
        drawing.drawString(72, top, line)
    drawing.save()


@REQUIRES_PDFCRAFT
def test_the_output_is_counts_without_a_file_name_or_a_word_of_the_document(tmp_path):
    page(tmp_path / 'private-contract-of-dilnoza.pdf')
    done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=300, env={**os.environ, 'PDFCRAFT_BENCH_DIR': str(tmp_path)})
    assert done.returncode == 0, done.stderr
    assert 'reportlab' in done.stdout
    for private in ('dilnoza', 'contract', 'Договор', 'Ташкент', 'Самарканд', str(tmp_path)):
        assert private not in done.stdout and private not in done.stderr
    row = next(line for line in done.stdout.splitlines() if line.startswith('reportlab'))
    assert [int(cell) for cell in row.split()[1:6]][1] > 0


@REQUIRES_PDFCRAFT
def test_one_file_reports_an_edit_as_json_with_codes_only(tmp_path):
    page(tmp_path / 'one.pdf')
    done = subprocess.run([sys.executable, '-I', str(SCRIPT), '--one', str(tmp_path / 'one.pdf')], capture_output=True, text=True, timeout=120, env=os.environ)
    found = json.loads(done.stdout)
    assert found['generator'] == 'reportlab' and found['alphabet'] == 'cyrillic' and found['edits']
    assert {row['outcome'] for row in found['edits']} <= {'clean', 'fallback', 'refused'}
    assert 'Договор' not in done.stdout


@REQUIRES_PDFCRAFT
def test_a_real_edit_of_a_word_the_new_one_contains_is_not_refused(tmp_path):
    drawn(tmp_path / 'one.pdf', (770, 'mark'))
    done = subprocess.run([sys.executable, '-I', str(SCRIPT), '--one', str(tmp_path / 'one.pdf')], capture_output=True, text=True, timeout=120, env=os.environ)
    edit = json.loads(done.stdout)['edits'][0]
    assert 'text' not in edit['faults'] and edit['outcome'] != 'refused'


def test_a_missing_binary_or_folder_is_said_plainly(tmp_path):
    environment = {key: value for key, value in os.environ.items() if key not in ('DOCMASTER_PDFCRAFT_BIN', 'PDFMASTER_PDFCRAFT_BIN', 'PDFCRAFT_BENCH_DIR')}
    done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=60, env=environment)
    assert done.returncode == 2 and 'DOCMASTER_PDFCRAFT_BIN' in done.stderr
    binary = tmp_path / 'pdfcraft-cli'
    binary.write_text('')
    done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=60, env={**environment, 'DOCMASTER_PDFCRAFT_BIN': str(binary)})
    assert done.returncode == 2 and 'PDFCRAFT_BENCH_DIR' in done.stderr


def stand_in(folder, script=None):
    """A pdfcraft-cli that notes each start and answers every script with a refusal; returns it and its notes."""
    binary, started = folder / 'pdfcraft-cli', folder / 'started'
    binary.write_text(script or f'#!/bin/sh\necho "$1" >> {shlex.quote(str(started))}\necho \'{{"ok": false, "steps": []}}\'\n')
    binary.chmod(0o755)
    return binary, started


@pytest.mark.parametrize('name', ['pdfcraft-cli', './pdfcraft-cli'])
def test_a_binary_named_relatively_still_starts_from_inside_each_temp_folder(tmp_path, name):
    _, started = stand_in(tmp_path)
    page(tmp_path / 'one.pdf')
    done = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True, timeout=60, env={**os.environ, 'PDFCRAFT_BENCH_DIR': str(tmp_path), 'DOCMASTER_PDFCRAFT_BIN': name})
    assert done.returncode == 0, done.stderr
    assert started.read_text().split() == ['--version', 'run']


@pytest.mark.parametrize(('script', 'mode'), [('not a program\n', 0o755), ('#!/bin/sh\nexit 3\n', 0o755), ('#!/bin/sh\necho hello\n', 0o644)])
def test_a_binary_that_cannot_start_is_an_error_not_a_table_of_refusals(tmp_path, script, mode):
    binary, _ = stand_in(tmp_path, script)
    binary.chmod(mode)
    page(tmp_path / 'one.pdf')
    done = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, timeout=60, env={**os.environ, 'PDFCRAFT_BENCH_DIR': str(tmp_path), 'DOCMASTER_PDFCRAFT_BIN': str(binary)})
    assert done.returncode == 2 and 'DOCMASTER_PDFCRAFT_BIN cannot start' in done.stderr
    assert 'generator' not in done.stdout
