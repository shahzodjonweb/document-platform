"""The excerpts a category draft is made from (apps/studio/categories/sources.excerpts).

A category reads PDF, Word (.docx and old .doc) and text files: a PDF page by
page, a Word or text file in parts of at most 3,000 characters. Files that
together hold no text to work from (a scan, an empty file) are refused with
'source_unreadable', naming them; in a mix, a file that gave no letter is
dropped and said. A defence deck keeps the beginning and the end of a thesis
too long for the request instead of refusing it whole, and says so; every other
category refuses as today. A draft whose files have not changed keeps its
excerpts without reading the files again, while a file gone is still refused.

A draft without a category keeps domain.source_excerpts exactly as it was,
blank scanned pages and all.

The people and organisations in these files are invented.
"""
import io
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.errors import DomainError, error_data
from apps.studio import categories, extraction
from apps.studio.categories import sources
from apps.studio.domain import source_excerpts
from processors import source_text
from tests.test_upload_ai_source import RUSSIAN, UZBEK, antiword, office_pages, principal, upload, word_doc  # noqa: F401  (fixtures)

pytestmark = pytest.mark.django_db

DECK = 'slides.himoya'      # sources.take: head_tail
PAPER = 'pdf.xat.ariza'     # today's refusal


def entry(category_id):
    found = categories.get(category_id)
    assert found is not None
    return found


def pdf(*pages):
    """A PDF with these lines of text, one page each; an empty string is a page with no text layer (a scan)."""
    from reportlab.pdfgen.canvas import Canvas
    raw = io.BytesIO()
    canvas = Canvas(raw)
    for text in pages:
        if text:
            canvas.drawString(45, 700, text)
        canvas.showPage()
    canvas.save()
    return raw.getvalue()


def docx(*paragraphs):
    from docx import Document
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    raw = io.BytesIO()
    document.save(raw)
    return raw.getvalue()


def ids(*assets):
    return [str(asset.id) for asset in assets]


def refusal(*args, **kwargs):
    with pytest.raises(DomainError) as refused:
        sources.excerpts(*args, **kwargs)
    return refused.value


# ------------------------------------------------------------------ every kind


def test_a_pdf_a_word_file_an_old_word_file_and_a_text_file_are_read_in_order(office_pages, antiword):
    account, _ = principal(89301)
    thesis = upload(account, 'thesis.pdf', pdf('Kirish: raqamli marketing.', '', 'Xulosa: savdo oshdi.'))
    plan = upload(account, 'reja.docx', docx('Reja', '1. Kirish', '2. Asosiy qism'))
    old = upload(account, 'eski.doc', word_doc())
    notes = upload(account, 'notes.txt', RUSSIAN.encode('cp1251'))
    excerpts, said = sources.excerpts(account, ids(thesis, plan, old, notes), entry(DECK))
    assert said == {'unread': [], 'cut': False}
    assert [(item['asset_id'], item['page']) for item in excerpts] == [
        (str(thesis.id), 1), (str(thesis.id), 3), (str(plan.id), 1), (str(old.id), 1), (str(notes.id), 1)]
    texts = [item['text'] for item in excerpts]
    # A blank page is left out; a citation's page is still the PDF's own.
    assert 'Kirish: raqamli marketing.' in texts[0] and 'Xulosa: savdo oshdi.' in texts[1]
    assert texts[2] == 'Reja\n1. Kirish\n2. Asosiy qism'
    assert texts[3] == source_text.pages(source_text.doc_text(f'{UZBEK}\n\n{RUSSIAN}\n'.encode()))[0]
    assert texts[4] == RUSSIAN
    assert set(excerpts[0]) == {'asset_id', 'page', 'text'}


def test_a_text_files_excerpts_are_as_many_as_the_pages_its_upload_counted():
    account, _ = principal(89302)
    text = '\n'.join(['Konspekt: fotosintez jarayoni o‘simlik bargida kechadi. ' * 25] * 8)
    notes = upload(account, 'konspekt.txt', text.encode('utf-8'))
    excerpts, _ = sources.excerpts(account, ids(notes), entry(PAPER))
    assert len(excerpts) == notes.page_count > 3
    assert [item['page'] for item in excerpts] == list(range(1, notes.page_count + 1))
    assert all(len(item['text']) <= source_text.PAGE_CHARS for item in excerpts)


# ------------------------------------------------------------------ nothing to read


def test_a_scan_alone_is_refused_as_unreadable_naming_it_in_every_language():
    account, _ = principal(89303)
    scan = upload(account, 'scan.pdf', pdf('', ''))
    refused = refusal(account, ids(scan), entry(DECK))
    assert (refused.code, refused.status, refused.params) == ('source_unreadable', 400, {'asset_ids': ids(scan)})
    for locale in ('en', 'uz', 'ru'):
        message = error_data(refused, locale)['message']
        assert message and message != error_data(DomainError('invalid_request'), locale)['message']
    assert 'Word' in error_data(refused, 'uz')['message'] and '’' in error_data(refused, 'uz')['message']


def test_files_with_fewer_than_forty_letters_together_are_refused():
    account, _ = principal(89304)
    short = upload(account, 'title.txt', 'Mavzu: Suv. 2026'.encode('utf-8'))
    page = upload(account, 'page.pdf', pdf('12 / 2026'))
    refused = refusal(account, ids(short, page), entry(PAPER))
    assert (refused.code, refused.params) == ('source_unreadable', {'asset_ids': ids(short, page)})
    empty = upload(account, 'empty.txt', b' \r\n ')
    assert refusal(account, ids(empty), entry(PAPER)).code == 'source_unreadable'


def test_in_a_mix_a_file_with_no_letters_is_dropped_and_said():
    account, _ = principal(89305)
    scan = upload(account, 'scan.pdf', pdf('', ''))
    notes = upload(account, 'notes.txt', UZBEK.encode('utf-8'))
    excerpts, said = sources.excerpts(account, ids(scan, notes), entry(DECK))
    assert said == {'unread': ids(scan), 'cut': False}
    assert {item['asset_id'] for item in excerpts} == {str(notes.id)}


def test_a_boshqa_draft_still_reads_a_scan_as_it_always_did():
    account, _ = principal(89306)
    scan = upload(account, 'scan.pdf', pdf(''), '')
    assert source_excerpts(account, ids(scan)) == [{'asset_id': str(scan.id), 'page': 1, 'text': ''}]


# ------------------------------------------------------------------ too long


def long_text(paragraphs):
    return '\n'.join(f'{number}-bo‘lim. ' + 'Tadqiqot natijalari kichik biznes uchun muhim. ' * 60
                     for number in range(1, paragraphs + 1))


def test_a_long_thesis_keeps_its_beginning_and_end_for_a_defence_deck():
    account, _ = principal(89307)
    thesis = upload(account, 'thesis.txt', long_text(12).encode('utf-8'))
    parts = source_text.pages(long_text(12))
    assert len(parts) == thesis.page_count >= 6
    room = len(parts[0]) + len(parts[-1]) + len(parts[1]) + 10
    excerpts, said = sources.excerpts(account, ids(thesis), entry(DECK), room=room)
    assert said == {'unread': [], 'cut': True}
    # First, last, then the next from the front: in the file's order.
    assert [item['page'] for item in excerpts] == [1, 2, len(parts)]
    assert [item['text'] for item in excerpts] == [parts[0], parts[1], parts[-1]]
    assert sum(len(item['text']) for item in excerpts) <= room


def test_every_file_keeps_its_ends_before_any_keeps_a_middle():
    account, _ = principal(89308)
    first = upload(account, 'first.txt', long_text(8).encode('utf-8'))
    second = upload(account, 'second.txt', long_text(8).encode('utf-8'))
    parts = source_text.pages(long_text(8))
    room = 4 * len(parts[0]) + len(parts[1]) + 10
    excerpts, said = sources.excerpts(account, ids(first, second), entry(DECK), room=room)
    assert said['cut'] is True
    pages = [(item['asset_id'], item['page']) for item in excerpts]
    assert pages == [(str(first.id), 1), (str(first.id), 2), (str(first.id), len(parts)),
                     (str(second.id), 1), (str(second.id), len(parts))]


def test_when_even_the_ends_do_not_fit_a_defence_deck_is_refused():
    account, _ = principal(89309)
    thesis = upload(account, 'thesis.txt', long_text(12).encode('utf-8'))
    parts = source_text.pages(long_text(12))
    refused = refusal(account, ids(thesis), entry(DECK), room=len(parts[0]) + len(parts[-1]) - 1)
    assert (refused.code, refused.params) == ('generation_limit', {'asset_ids': ids(thesis)})


def test_any_other_category_refuses_a_source_over_the_wall_as_today():
    account, _ = principal(89310)
    # Over the plan's 130,000 characters, with the wall as it is by default.
    text = long_text(50)
    assert len(text) > 130_000
    thesis = upload(account, 'thesis.txt', text.encode('utf-8'))
    refused = refusal(account, ids(thesis), entry(PAPER))
    assert (refused.code, refused.params) == ('generation_limit', {'asset_ids': ids(thesis)})
    excerpts, said = sources.excerpts(account, ids(thesis), entry(DECK))
    assert said['cut'] is True and sum(len(item['text']) for item in excerpts) <= 130_000


def test_the_plans_file_and_page_caps_hold_before_anything_is_read(monkeypatch):
    from operations import plans as plan_settings
    account, _ = principal(89311)
    files = [upload(account, f'notes-{n}.txt', UZBEK.encode('utf-8')) for n in range(3)]
    plan_settings.save(account.plan, {'max_ai_source_files': '2'})
    monkeypatch.setattr(extraction, 'read_source', lambda *args, **kwargs: pytest.fail('read before the caps'))
    refused = refusal(account, ids(*files), entry(DECK))
    assert (refused.code, refused.params) == ('generation_limit', {'asset_ids': ids(*files)})


# ------------------------------------------------------------------ what a file's refusal says


def test_a_file_that_cannot_be_read_or_is_no_source_is_named_in_its_refusal(monkeypatch):
    from PIL import Image
    account, _ = principal(89312)
    notes = upload(account, 'notes.txt', UZBEK.encode('utf-8'))
    picture = io.BytesIO()
    Image.new('RGB', (8, 8), 'white').save(picture, 'PNG')
    photo = upload(account, 'photo.png', picture.getvalue(), '')
    refused = refusal(account, ids(notes, photo), entry(DECK))
    assert (refused.code, refused.params) == ('unsupported_file', {'asset_ids': ids(photo)})

    def broken(path, kind, **kwargs):
        raise DomainError('source_extraction_failed')
    monkeypatch.setattr(extraction, 'read_source', broken)
    refused = refusal(account, ids(notes), entry(DECK))
    assert (refused.code, refused.params) == ('source_extraction_failed', {'asset_ids': ids(notes)})


# ------------------------------------------------------------------ reuse


def stored_draft(account, files, category_id, **options):
    excerpts, said = sources.excerpts(account, ids(*files), entry(category_id))
    return {'source_ids': ids(*files), 'excerpts': excerpts,
            'options': {'category': category_id, sources.CUT_KEY: said['cut'], **options}}


def test_unchanged_files_keep_their_excerpts_without_being_read_again(monkeypatch):
    account, _ = principal(89313)
    scan = upload(account, 'scan.pdf', pdf(''))
    notes = upload(account, 'notes.txt', UZBEK.encode('utf-8'))
    stored = stored_draft(account, [scan, notes], DECK)
    stored['options'][sources.CUT_KEY] = True
    monkeypatch.setattr(extraction, 'read_source', lambda *args, **kwargs: pytest.fail('read again'))
    monkeypatch.setattr(extraction, 'extract_pages', lambda *args, **kwargs: pytest.fail('read again'))
    excerpts, said = sources.excerpts(account, ids(scan, notes), entry(DECK), stored=stored)
    assert excerpts == stored['excerpts'] and excerpts is not stored['excerpts']
    assert said == {'unread': ids(scan), 'cut': True}


def test_other_files_or_another_category_are_read_again(monkeypatch):
    account, _ = principal(89314)
    notes = upload(account, 'notes.txt', UZBEK.encode('utf-8'))
    more = upload(account, 'more.txt', RUSSIAN.encode('utf-8'))
    stored = stored_draft(account, [notes], DECK)
    calls = []
    real = extraction.read_source
    monkeypatch.setattr(extraction, 'read_source', lambda *args, **kwargs: calls.append(args[1]) or real(*args, **kwargs))
    sources.excerpts(account, ids(notes, more), entry(DECK), stored=stored)
    assert calls == ['text', 'text']
    sources.excerpts(account, ids(notes), entry(PAPER), stored=stored)
    assert calls == ['text'] * 3


def test_stored_excerpts_that_no_longer_fit_are_fitted_again(monkeypatch):
    # An answer to the review question made the prompt longer: a thesis's ends are fitted to the room left.
    account, _ = principal(89318)
    thesis = upload(account, 'thesis.txt', long_text(12).encode('utf-8'))
    parts = source_text.pages(long_text(12))
    stored = stored_draft(account, [thesis], DECK)
    assert len(stored['excerpts']) == len(parts)
    excerpts, said = sources.excerpts(account, ids(thesis), entry(DECK), stored=stored, room=len(parts[0]) + len(parts[-1]))
    assert [item['page'] for item in excerpts] == [1, len(parts)] and said['cut'] is True


def test_a_file_gone_is_refused_even_when_its_excerpts_are_stored():
    account, _ = principal(89315)
    notes = upload(account, 'notes.txt', UZBEK.encode('utf-8'))
    stored = stored_draft(account, [notes], DECK)
    notes.expires_at = timezone.now() - timedelta(seconds=1)
    notes.save(update_fields=['expires_at'])
    assert refusal(account, ids(notes), entry(DECK), stored=stored).code == 'file_unavailable'
    other, _ = principal(89316)
    assert refusal(other, ids(notes), entry(DECK), stored=stored).code == 'file_unavailable'


def test_no_files_is_no_excerpts():
    account, _ = principal(89317)
    assert sources.excerpts(account, [], entry(DECK)) == ([], {'unread': [], 'cut': False})
