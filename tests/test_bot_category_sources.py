"""Files and captions in the bot's category flows (architecture 8.3).

On the list of categories and in a category's question, a PDF, Word (.docx or
old .doc) or TXT file is one of the category's sources: stored as purpose
'ai_source', noted as received, and held in the chat's state beside the
category, never on the file tools' draft. A caption is the whole description,
so a file sent with its description makes the review in one message; a file
sent before the description is read with it; on the category's topic question
a file is what was missing. A file of another kind is never downloaded, a file
refused on upload is said in the category's words, and a file the draft could
not use is taken out, said, and the question asked again.

Boshqa and today's question, with the switch on or off, take files exactly as
before: a .txt is refused at the door, a scanned PDF still makes a draft, a
Word file is staged for the file tools and not read.

The people, organisations and descriptions are invented for these tests.
"""
import re
import secrets

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.commerce.models import LocalBotMessage
from apps.core.errors import DomainError
from apps.core.models import BotDraft, BotInputReceipt, FileAsset
from apps.studio.domain import DOCUMENT, SLIDES
from apps.studio.models import GenerationDraft
from telegram.errors import COPY as ERRORS, SOURCE_COPY, SOURCE_MESSAGES, source_error
from telegram.ux_copy import MESSAGES, UX
from tests.test_bot_categories import (DEFENCE, HIMOYA, QUIZ, TEST, customer, latest, opened, pending,  # noqa: F401
                                       ready, screen, speak, switch, tapped, turn)
from tests.test_bot_cv import feed_together
from tests.test_bot_generation import stage_pdf
from tests.test_bot_no_flood import Chat
from tests.test_category_sources import docx, pdf
from tests.test_upload_ai_source import RUSSIAN, UZBEK, antiword, office_pages, word_doc  # noqa: F401

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled', 'office_pages')]

THESIS = ('Kirish. Ushbu kurs ishi “Yashil vodiy” MChJ misolida kichik biznesda raqamli marketingni o‘rganadi. '
          'Xulosa: ijtimoiy tarmoqlardagi reklama savdoni sezilarli oshirdi.')
SCAN = pdf('')


def upload(name, raw):
    return SimpleUploadedFile(name, raw)


def asset(account, name):
    return FileAsset.objects.get(account=account, name=name)


def staged(account):
    draft = BotDraft.objects.filter(account=account).first()
    return [str(item) for item in draft.input_ids] if draft else []


def outbound(account, back=0):
    """The text of the bot's newest message, or of the one `back` before it."""
    return LocalBotMessage.objects.filter(account=account, direction='outbound').order_by('-created_at')[back].text


def question(chat, service=DOCUMENT, category=TEST):
    """The category's question on screen, from the menu through the list."""
    assert chat.tap('ai_tool', feature_id=service, category=category) == 0
    return chat


# --- A file with its description ------------------------------------------------------------------


def test_a_word_file_with_its_description_as_caption_is_one_review_in_one_message(customer, switch):
    chat = question(opened(customer, SLIDES), SLIDES, HIMOYA)
    assert chat.do(uploaded=upload('thesis.docx', docx(THESIS)), caption=DEFENCE) == 1, '"Preparing…" becomes the review'
    assert 'Slides:' in chat.last()
    thesis = asset(customer, 'thesis.docx')
    data = latest(customer, SLIDES)
    assert data['options']['category'] == HIMOYA
    assert data['source_ids'] == [str(thesis.id)]
    assert DEFENCE in data['prompt'] + data['source_text']
    assert any('raqamli marketing' in item['text'] for item in data['excerpts'])
    # The category's own file: never on the file tools' draft, but received once.
    assert thesis.metadata['kind'] == 'docx' and str(thesis.id) not in staged(customer)
    assert BotInputReceipt.objects.filter(account=customer, asset=thesis).count() == 1
    assert pending(customer) == ('', {})


def test_a_file_then_the_description_keeps_the_category_and_the_file(customer, switch):
    chat = question(opened(customer, SLIDES), SLIDES, HIMOYA)
    assert chat.do(uploaded=upload('thesis.docx', docx(THESIS))) == 1
    thesis = asset(customer, 'thesis.docx')
    text, _, _, _ = screen(customer)
    assert text.endswith('\n\n📎 1') and UX['en']['ai_cat_files'] in text
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES, 'category': HIMOYA, 'files': [str(thesis.id)]})
    assert chat.do(text=DEFENCE) == 1
    data = latest(customer, SLIDES)
    assert data['options']['category'] == HIMOYA and data['source_ids'] == [str(thesis.id)]
    assert pending(customer) == ('', {})


def test_an_album_with_a_caption_makes_one_draft_from_every_file(customer, switch, monkeypatch):
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0.3)
    question(opened(customer))
    group = secrets.token_hex(6)
    feed_together(customer, [(upload('plan.docx', docx('Reja: 1. Fotosintez. 2. Xlorofill.')), QUIZ, group),
                             (upload('notes.txt', UZBEK.encode()), '', group)], 0.02)
    plan, notes = asset(customer, 'plan.docx'), asset(customer, 'notes.txt')
    assert GenerationDraft.objects.filter(account=customer).count() == 1
    data = latest(customer)
    assert data['source_ids'] == [str(plan.id), str(notes.id)] and data['options']['category'] == TEST
    assert QUIZ in data['prompt'] + data['source_text']
    assert 'Ready to start' in outbound(customer)


# --- What is taken, and where ---------------------------------------------------------------------


def test_a_text_and_an_old_word_file_are_taken_only_in_a_category(customer, switch, antiword):
    # Today's question, the switch off: a .txt is refused at the door and nothing is stored.
    turn(on=False)
    chat = opened(customer)
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    assert chat.do(uploaded=upload('notes.txt', UZBEK.encode())) == 1
    assert outbound(customer) == UX['en']['unsupported']
    assert chat.do(uploaded=upload('old.doc', word_doc())) == 1
    assert outbound(customer) == UX['en']['unsupported']
    assert not FileAsset.objects.filter(account=customer).exists()

    # Boshqa with the switch on: the same door.
    turn()
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category='other')
    assert chat.do(uploaded=upload('notes.txt', UZBEK.encode())) == 1
    assert outbound(customer) == UX['en']['unsupported']
    assert not FileAsset.objects.filter(account=customer).exists()

    # A category's question takes both, as its own sources.
    chat = question(opened(customer))
    assert chat.do(uploaded=upload('notes.txt', RUSSIAN.encode('cp1251'))) == 1
    assert chat.do(uploaded=upload('old.doc', word_doc())) == 1
    notes, old = asset(customer, 'notes.txt'), asset(customer, 'old.doc')
    assert (notes.metadata['kind'], old.metadata['kind']) == ('text', 'doc')
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST, 'files': [str(notes.id), str(old.id)]})
    assert screen(customer)[0].endswith('\n\n📎 2') and staged(customer) == []
    assert chat.do(text=QUIZ) == 1
    data = latest(customer)
    assert data['source_ids'] == [str(notes.id), str(old.id)] and data['options']['category'] == TEST


def test_files_on_the_list_are_held_and_go_with_the_category_chosen(customer, switch):
    chat = opened(customer)
    assert chat.do(uploaded=upload('notes.txt', UZBEK.encode())) == 1
    notes = asset(customer, 'notes.txt')
    text, actions, _, _ = screen(customer)
    assert text.endswith('\n\n📎 1') and UX['en']['ai_cat_choose'] in text
    assert actions[0] == ['ai_tool']
    assert pending(customer) == ('ai_category', {'feature_id': DOCUMENT, 'files': [str(notes.id)]})
    tapped(customer, {'feature_id': DOCUMENT, 'category': TEST})
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST, 'files': [str(notes.id)]})
    assert screen(customer)[0].endswith('\n\n📎 1')
    # Back to the list, and they are still held there.
    tapped(customer, {'feature_id': DOCUMENT})
    assert pending(customer) == ('ai_category', {'feature_id': DOCUMENT, 'files': [str(notes.id)]})


def test_boshqa_after_files_on_the_list_reads_the_pdfs_as_todays_question_does(customer, switch):
    chat = opened(customer)
    chat.do(uploaded=upload('report.pdf', pdf('Hisobot: “Kamalak” maktabi, birinchi chorak natijalari.')))
    chat.do(uploaded=upload('notes.txt', UZBEK.encode()))
    report = asset(customer, 'report.pdf')
    assert chat.tap('ai_tool', feature_id=DOCUMENT, category='other') == 0
    # Today's question exactly, with the PDF where it reads it; the text file was a category's and is not staged.
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    assert staged(customer) == [str(report.id)]
    assert screen(customer)[0].endswith('\n\n📎 1')
    assert chat.do(text='A 2 page summary of the attached report.') == 1
    data = latest(customer)
    assert 'category' not in data['options'] and data['source_ids'] == [str(report.id)]


def test_a_caption_on_the_list_is_a_description_for_boshqa(customer, switch):
    chat = opened(customer)
    assert chat.do(uploaded=upload('report.pdf', pdf('Hisobot: “Kamalak” maktabi, birinchi chorak natijalari.')),
                   caption='A 2 page summary of this report.') == 1
    data = latest(customer)
    assert 'category' not in data['options'] and data['source_ids'] == [str(asset(customer, 'report.pdf').id)]
    assert 'Ready to start' in outbound(customer)


def test_a_photo_in_a_category_is_never_downloaded_and_the_screen_says_what_is_read(customer, switch):
    chat = question(opened(customer))
    assert chat.do(uploaded=upload('photo.png', b'not downloaded')) == 1
    text, _, _, _ = screen(customer)
    assert text.startswith(UX['en']['ai_topic_files_only'] + '\n\n')
    assert not FileAsset.objects.filter(account=customer).exists()
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})
    # With a caption, nothing is made from the words alone: the screen says what is read.
    assert chat.do(uploaded=upload('slides.pptx', b'not downloaded'), caption=QUIZ) == 1
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_the_topic_question_in_a_category_takes_a_file_as_what_was_missing(customer, switch):
    from operations.integrations import save_config
    save_config('ai', {'mode': 'openai', 'model': 'gpt-5.6-luna', 'api_key': 'sk-offline-test-only'})
    chat = question(opened(customer))
    assert chat.do(text='Menga test kerak') == 1
    assert pending(customer)[1]['brief'] == ['Menga test kerak']
    assert chat.do(uploaded=upload('plan.docx', docx('Fotosintez: yorug‘lik, xlorofill, kislorod. 7-sinf biologiya.'))) == 1
    assert 'Ready to start' in outbound(customer)
    assert UX['en']['ai_topic_pdf_only'] not in outbound(customer)
    data = latest(customer)
    assert data['options']['category'] == TEST and data['source_ids'] == [str(asset(customer, 'plan.docx').id)]
    assert data['prompt'] == 'Menga test kerak'


# --- What cannot be read --------------------------------------------------------------------------


def test_a_file_refused_on_upload_is_said_in_the_categorys_words(customer, switch):
    chat = question(opened(customer))
    latin = ('Résumé du café à Genève, très célèbre. ' * 4).encode('latin-1')
    assert chat.do(uploaded=upload('notes.txt', latin)) == 1
    text, _, _, _ = screen(customer)
    assert text.startswith(SOURCE_COPY['en']['unsupported_type'] + '\n\n')
    assert 'PDF, image, DOCX or PPTX' not in text
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})


def test_a_file_with_no_text_is_taken_out_and_said_and_the_question_asked_again(customer, switch):
    chat = question(opened(customer))
    chat.do(uploaded=upload('scan.pdf', SCAN))
    scan = asset(customer, 'scan.pdf')
    assert pending(customer)[1]['files'] == [str(scan.id)]
    assert chat.do(text=QUIZ) == 2, '"Preparing…" becomes the reason, and the question is asked again'
    assert outbound(customer, 1) == SOURCE_COPY['en']['source_unreadable']
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})
    assert '📎' not in screen(customer)[0].split(UX['en']['ai_cat_files'])[-1]
    assert not GenerationDraft.objects.filter(account=customer).exists()
    # Written again, it is made: the file is no longer read.
    assert chat.do(text=QUIZ) == 1 and latest(customer)['source_ids'] == []


def test_a_file_staged_for_the_tools_that_the_category_cannot_read_is_taken_out_too(customer, switch):
    blank = stage_pdf(customer)
    chat = question(opened(customer))
    assert screen(customer)[0].endswith('\n\n📎 1')
    assert chat.do(text=QUIZ) == 2
    assert outbound(customer, 1) == SOURCE_COPY['en']['source_unreadable']
    assert str(blank.id) not in staged(customer)
    assert chat.do(text=QUIZ) == 1 and latest(customer)['source_ids'] == []


def test_a_file_that_could_not_be_read_is_taken_out_and_the_others_kept(customer, switch, monkeypatch):
    from apps.studio import extraction
    real = extraction.read_source

    def broken(path, kind, **kwargs):
        if kind == 'text':
            raise DomainError('source_extraction_failed')
        return real(path, kind, **kwargs)
    monkeypatch.setattr(extraction, 'read_source', broken)
    speak(customer, 'uz')
    chat = question(opened(customer, SLIDES), SLIDES, HIMOYA)
    chat.do(uploaded=upload('thesis.docx', docx(THESIS)))
    chat.do(uploaded=upload('notes.txt', UZBEK.encode()))
    thesis = asset(customer, 'thesis.docx')
    assert chat.do(text=DEFENCE) == 2
    assert outbound(customer, 1) == SOURCE_COPY['uz']['source_extraction_failed']
    assert pending(customer) == ('ai_input', {'feature_id': SLIDES, 'category': HIMOYA, 'files': [str(thesis.id)]})
    assert chat.do(text=DEFENCE) == 1
    assert latest(customer, SLIDES)['source_ids'] == [str(thesis.id)]


def test_too_much_in_the_files_is_said_as_too_much_and_they_are_taken_out(customer, switch, monkeypatch):
    from apps.studio.categories import sources

    def full(account, ids, entry, **kwargs):
        raise DomainError('generation_limit', 400, {'asset_ids': list(ids)})
    monkeypatch.setattr(sources, 'excerpts', full)
    speak(customer, 'ru')
    chat = question(opened(customer))
    chat.do(uploaded=upload('notes.txt', RUSSIAN.encode()))
    assert chat.do(text=QUIZ) == 2
    assert outbound(customer, 1) == SOURCE_COPY['ru']['generation_limit']
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})


def test_an_old_word_file_the_reading_host_cannot_read_is_taken_out_and_the_next_description_made(customer, switch,
                                                                                                  antiword, monkeypatch):
    # Taken on upload where antiword is installed, read where it is missing.
    speak(customer, 'uz')
    chat = question(opened(customer))
    chat.do(uploaded=upload('old.doc', word_doc()))
    old = asset(customer, 'old.doc')
    assert pending(customer)[1]['files'] == [str(old.id)]
    monkeypatch.setenv('DOCMASTER_ANTIWORD_BIN', str(antiword / 'missing'))
    assert chat.do(text=QUIZ) == 2
    assert outbound(customer, 1) == SOURCE_COPY['uz']['conversion_preflight_unavailable']
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    # Written again, it is made without the file rather than refused again.
    assert chat.do(text=QUIZ) == 1
    data = latest(customer)
    assert data['options']['category'] == TEST and data['source_ids'] == []


def test_a_refusal_naming_files_with_no_category_wording_still_takes_them_out(customer, switch, monkeypatch):
    from apps.studio.categories import sources
    real = sources.excerpts

    def unavailable(account, ids, entry, **kwargs):
        if ids:
            raise DomainError('engine_unavailable', 503, {'asset_ids': list(ids)})
        return real(account, ids, entry, **kwargs)
    monkeypatch.setattr(sources, 'excerpts', unavailable)
    blank = stage_pdf(customer)
    chat = question(opened(customer))
    chat.do(uploaded=upload('notes.txt', UZBEK.encode()))
    notes = asset(customer, 'notes.txt')
    assert chat.do(text=QUIZ) == 2
    # The customer learns the files are gone, not a general error to send the same words again after.
    assert outbound(customer, 1) == SOURCE_COPY['en']['source_extraction_failed']
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT, 'category': TEST})
    assert str(blank.id) not in staged(customer) and str(notes.id) not in staged(customer)
    assert chat.do(text=QUIZ) == 1
    assert latest(customer)['source_ids'] == []


def test_the_category_wording_is_only_for_refusals_that_name_files():
    named = DomainError('generation_limit', 400, {'asset_ids': ['a']})
    assert source_error(named, 'uz') == SOURCE_COPY['uz']['generation_limit']
    # A description too long on its own keeps the shared wording.
    assert source_error(DomainError('generation_limit'), 'uz') == ''
    assert source_error(DomainError('unsupported_type'), 'fr') == SOURCE_COPY['en']['unsupported_type']
    assert source_error(DomainError('page_limit', 413, {'limit': 200}), 'en') == ''
    assert SOURCE_COPY['en']['unsupported_file'] != ERRORS['en']['unsupported_file']


# --- Boshqa and today's question ------------------------------------------------------------------


@pytest.mark.parametrize('on', [False, True])
def test_boshqa_with_a_scan_or_a_word_file_is_todays_flow(customer, ready, on):
    """A scanned PDF still makes a draft, silently; a Word file is staged for the tools and not read."""
    turn(on=on)
    chat = opened(customer)
    if on:
        chat.tap('ai_tool', feature_id=DOCUMENT, category='other')
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    assert chat.do(uploaded=upload('scan.pdf', SCAN)) == 1
    assert chat.do(uploaded=upload('plan.docx', docx('Reja: 1. Kirish.'))) == 1
    scan, plan = asset(customer, 'scan.pdf'), asset(customer, 'plan.docx')
    assert staged(customer) == [str(scan.id), str(plan.id)]
    assert pending(customer) == ('ai_input', {'feature_id': DOCUMENT})
    assert screen(customer)[0].endswith('\n\n📎 1')
    assert chat.do(text='A 2 page summary of the attached file.') == 1
    data = latest(customer)
    assert 'category' not in data['options'] and data['source_ids'] == [str(scan.id)]
    assert 'Ready to start' in outbound(customer)


# --- Copy -----------------------------------------------------------------------------------------


def test_the_category_file_words_say_the_same_in_every_language():
    lines = [*SOURCE_MESSAGES.values(), MESSAGES['ai_topic_files_only']]
    for en, uz, ru in lines:
        assert en and uz and ru
        for words in (en, uz):
            assert not re.search('[А-Яа-яЁё]', words), words
        assert "'" not in uz and "'" not in en and "'" not in ru, uz
        assert re.search('[А-Яа-я]', ru)
        # What a category reads is named alike in every language, wherever it is named.
        if 'PDF' in en:
            assert all(kind in words for kind in ('PDF', 'Word', 'TXT') for words in (en, uz, ru)), en
