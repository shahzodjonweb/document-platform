"""A CV made in the chat from the customer's LinkedIn profile or old CV, not only from one message.

The CV service asks first how the CV is made: written about yourself (the one
message it always was, followed in tests/test_bot_cv.py), from the LinkedIn
profile, or from the old CV. The last two are made from files sent on their own
screen: the profile saved with LinkedIn's "Save to PDF" or screenshots of it,
and an old CV as a PDF, a Word file, photos or a scan. Words sent before a
file, with it or just after it are notes on top of it; a photo sent there is a
page to read, never the portrait, which is sent on the review. These tests
follow the files from the chat to the review with files made here as the
server's tests make them (tests/test_cv_sources.py). Everyone in them is
fictional (example.com, example.org and example.net contacts).
"""
import functools
import io
import secrets
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.commerce.models import LocalBotMessage
from apps.core.models import BotCallback, BotConversation, BotInputReceipt, FileAsset, Job
from apps.studio.domain import CV
from apps.studio.models import GenerationDraft
from operations.integrations import save_config
from telegram import generation
from telegram.bot import COPY
from telegram.errors import COPY as ERRORS
from telegram.local import dispatch_local
from telegram.ux_copy import LOCALES, TOOL_NAMES, UX
from tests.test_bot_cv import (FLAGS, PHONE, actions, asks_for, cv, feed_together, file_task_waiting, image, model,  # noqa: F401
                                screen, state)
from tests.test_bot_generation import customer, latest, tap  # noqa: F401
from tests.test_cv_content import BRIEF
from tests.test_cv_sources import (_lines, _pdf, blank_pdf, docx_cv, encrypted_pdf, linkedin_pdf, needs_tesseract,
                                   one_column_pdf, picture)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

EN = UX['en']


def speak(account, locale):
    account.locale = locale
    account.save(update_fields=['locale'])
    BotConversation.objects.filter(pk=account.telegram_user_id).update(locale=locale)


def choose(account, key, locale='en'):
    """The CV service chosen from the menu, then the way button `key` names: that way's screen on show."""
    home = dispatch_local(account, text='/start')
    return tap(account, tap(account, home, TOOL_NAMES[CV][locale]), UX[locale][key])


def upload(name, raw):
    return SimpleUploadedFile(name, raw)


def send(account, name, raw, caption=None, group=None):
    """A file sent in the chat, with its caption and the album it is in."""
    return dispatch_local(account, uploaded=upload(name, raw), caption=caption, media_group_id=group)


def outbound(account):
    return LocalBotMessage.objects.filter(account=account, direction='outbound').count()


def age(account, minutes):
    """The chat's screen as if it had been drawn `minutes` ago."""
    BotConversation.objects.filter(pk=account.telegram_user_id).update(
        updated_at=timezone.now() - timedelta(minutes=minutes))


@functools.lru_cache(maxsize=None)
def shot(index):
    """Page `index` of the LinkedIn export as a phone screenshot of the profile: a PNG."""
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(linkedin_pdf())
    page = document[index]
    bitmap = page.render(scale=2.0)
    raw = io.BytesIO()
    bitmap.to_pil().convert('RGB').save(raw, 'PNG')
    bitmap.close()
    page.close()
    document.close()
    return raw.getvalue()


@functools.lru_cache(maxsize=None)
def nameless_pdf():
    """An old CV that names nobody: how to reach the person and what they did, never who they are."""
    return _pdf(lambda page, _: _lines(page, 60, 780, [
        ('Helvetica', 11, 'Phone: +998 90 123 45 67', 16),
        ('Helvetica', 11, 'Experience: accountant at Example Trade LLC, 2019 - 2024.', 16),
        ('Helvetica', 11, 'Skills: 1C, Excel, IFRS reporting, payroll, tax returns.', 16)]))


@functools.lru_cache(maxsize=None)
def skills_only_pdf():
    """An old CV with next to nothing in it: a line of skills, neither who the person is, nor how to reach them, nor a job."""
    return _pdf(lambda page, _: _lines(page, 60, 780, [
        ('Helvetica', 11, 'Skills: 1C, Excel, IFRS reporting, payroll, tax returns, budgeting, invoicing.', 16),
        ('Helvetica', 11, 'Languages: Uzbek native, Russian fluent, English B1.', 16)]))


@functools.lru_cache(maxsize=None)
def jobless_pdf():
    """An old CV that says who the person is and how to reach them, and nothing they did or studied."""
    return _pdf(lambda page, _: _lines(page, 60, 780, [
        ('Helvetica', 20, 'Dilnoza Karimova', 26),
        ('Helvetica', 11, 'Phone: +998 91 234 56 78', 16),
        ('Helvetica', 11, 'Skills: 1C, Excel, IFRS reporting, payroll, tax returns, budgeting, invoicing.', 16),
        ('Helvetica', 11, 'Languages: Uzbek native, Russian fluent, English B1.', 16)]))


@functools.lru_cache(maxsize=None)
def linkedin_without_contact():
    """A LinkedIn "Save to PDF" export of a profile that shows no contact details: the person and their jobs, not how to reach them."""
    from reportlab.lib.pagesizes import letter

    def draw(page, _):
        page.setFillColorRGB(0.95, 0.95, 0.95)
        page.rect(0, 0, 200, letter[1], stroke=0, fill=1)
        _lines(page, 28, 740, [
            ('Helvetica-Bold', 13, 'Top Skills', 20), ('Helvetica', 10, 'SQL', 13), ('Helvetica', 10, 'Power BI', 26),
            ('Helvetica-Bold', 13, 'Languages', 20), ('Helvetica', 10, 'Uzbek (Native or Bilingual)', 13),
            ('Helvetica', 10, 'English (Professional Working)', 13)])
        _lines(page, 222, 735, [
            ('Helvetica', 26, 'Dilnoza Karimova', 22), ('Helvetica', 12, 'Senior Data Analyst at Example Retail', 16),
            ('Helvetica', 10, 'Tashkent, Uzbekistan', 30), ('Helvetica', 16, 'Experience', 22),
            ('Helvetica-Bold', 12, 'Example Retail', 15), ('Helvetica', 11, 'Senior Data Analyst', 14),
            ('Helvetica', 10, 'March 2022 - Present (2 years 8 months)', 14),
            ('Helvetica', 11, 'Built weekly sales dashboards in Power BI for 40 stores.', 26),
            ('Helvetica-Bold', 12, 'Sample Bank', 15), ('Helvetica', 11, 'Data Analyst', 14),
            ('Helvetica', 10, 'July 2019 - February 2022 (2 years 8 months)', 14)])
    return _pdf(draw, 1, letter)


@pytest.fixture
def word_pages(monkeypatch):
    """A Word file's page count without LibreOffice, which counts it on upload and which tests may not have."""
    from apps.core import services
    from processors.engine import inspect_file
    real = services.engine_inspect

    def inspect(path, password=None, allow_links=False):
        from apps.core.errors import DomainError
        from processors import ProcessorError
        if not str(path).endswith('.docx'):
            return real(path, password=password, allow_links=allow_links)
        try:
            return {**inspect_file(path, office_preflight=False, allow_links=allow_links), 'page_count': 1}
        except ProcessorError as exc:
            raise DomainError(exc.code) from None
    monkeypatch.setattr(services, 'engine_inspect', inspect)


# --- Asked first -------------------------------------------------------------------------------

@pytest.mark.parametrize('locale', LOCALES)
def test_the_cv_service_asks_first_how_to_make_it(customer, locale):
    speak(customer, locale)
    words, shown = screen(tap(customer, dispatch_local(customer, text='/start'), TOOL_NAMES[CV][locale]))
    copy = UX[locale]
    assert words == f'<b>{TOOL_NAMES[CV][locale]}</b>\n{copy["cv_choose_ask"]}\n\n<i>{copy["cv_choose_hint"]}</i>', words
    assert shown == [copy['cv_mode_text'], copy['cv_mode_linkedin'], copy['cv_mode_file'], copy['ai_back']]
    assert actions(customer) == [['cv_mode'], ['cv_mode'], ['cv_mode'], ['home']]
    assert state(customer) == ('cv_choose', {'feature_id': CV})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    # Each way opens its own screen, and Back on it comes back to this one.
    question = tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_text'])
    assert screen(question)[0].startswith(f'<b>{TOOL_NAMES[CV][locale]}</b>\n{copy["cv_ask"]}')
    assert screen(tap(customer, question, copy['ai_back']))[0].endswith(f'<i>{copy["cv_choose_hint"]}</i>')
    linkedin = tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_linkedin'])
    assert copy['cv_linkedin_computer'] in screen(linkedin)[0] and copy['cv_linkedin_phone'] in screen(linkedin)[0]
    old = tap(customer, dispatch_local(customer, text='/cv'), copy['cv_mode_file'])
    assert copy['cv_file_ask'] in screen(old)[0]
    assert screen(tap(customer, old, copy['ai_back']))[1][:3] == shown[:3]


def test_every_way_into_the_cv_service_asks_first(customer):
    asked = f'{EN["cv_choose_ask"]}\n\n<i>{EN["cv_choose_hint"]}</i>'
    assert asked in screen(dispatch_local(customer, text='/cv'))[0]
    assert asked in screen(tap(customer, dispatch_local(customer, text='/tools'), TOOL_NAMES[CV]['en']))[0]
    assert asked in screen(tap(customer, dispatch_local(customer, text='/examples'), TOOL_NAMES[CV]['en']))[0]
    # "Change the description" under a CV the AI could not finish (notifications.py) carries only the service.
    token = secrets.token_urlsafe(12)
    BotCallback.objects.create(token=token, account=customer, action='ai_tool', payload={'feature_id': CV},
                               expires_at=timezone.now() + timedelta(hours=24))
    LocalBotMessage.objects.create(account=customer, direction='outbound', text='The CV could not be made.',
                                   telegram_message_id=4242, buttons=[[{'label': EN['ai_change_topic'],
                                                                        'callback_data': token, 'url': None}]])
    assert asked in screen(dispatch_local(customer, callback_data=token))[0]


def test_writing_about_yourself_is_the_question_it_always_was(customer, model):
    words, _ = screen(choose(customer, 'cv_mode_text'))
    assert words.startswith(f'<b>{TOOL_NAMES[CV]["en"]}</b>\n{asks_for()}\n\n<i>{EN["cv_photo_hint"]}</i>'), words
    assert state(customer) == ('ai_input', {'feature_id': CV})
    words, _ = screen(dispatch_local(customer, text=BRIEF))
    assert '📄 Dilnoza Karimova' in words and EN['cv_linkedin_title'] not in words and '📎 From' not in words, words
    data = latest(customer, CV)
    assert data['prompt'] == BRIEF and data['source_ids'] == [] and 'cv_source' not in data['options']


def test_words_sent_before_a_way_is_chosen(customer, model):
    dispatch_local(customer, text='/cv')
    words, _ = screen(dispatch_local(customer, text='Assalomu alaykum'))
    assert words.startswith(EN['cv_choose_first']) and EN['cv_choose_ask'] in words, words
    assert state(customer)[0] == 'cv_choose' and not GenerationDraft.objects.filter(account=customer).exists()
    # A whole description is the first way: written about yourself.
    words, _ = screen(dispatch_local(customer, text=BRIEF))
    assert '📄 Dilnoza Karimova' in words and latest(customer, CV)['prompt'] == BRIEF


def test_a_file_sent_before_a_way_is_chosen_is_the_old_cv(customer, model):
    dispatch_local(customer, text='/cv')
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf()))
    assert '📄 Timur Rakhimov' in words and '📎 From: old-cv.pdf' in words, words
    assert latest(customer, CV)['options']['cv_source'] == 'file'


# --- From the LinkedIn profile ------------------------------------------------------------------

def test_a_linkedin_pdf_becomes_a_review_that_says_where_it_came_from(customer, model):
    words, shown = screen(choose(customer, 'cv_mode_linkedin'))
    for key in ('cv_linkedin_title', 'cv_linkedin_ask', 'cv_linkedin_computer', 'cv_linkedin_phone', 'cv_notes_hint'):
        assert EN[key] in words, key
    assert shown == [EN['ai_back'], EN['home']]
    assert state(customer) == ('cv_source', {'feature_id': CV, 'cv_source': 'linkedin', 'notes': [], 'source_ids': [],
                                             'ask': 'file'})
    before = outbound(customer)
    words, shown = screen(send(customer, 'Profile.pdf', linkedin_pdf(), caption='I want a job as a lead data analyst'))
    profile = FileAsset.objects.get(account=customer, name='Profile.pdf')
    # "Preparing…" became the review: one message.
    assert outbound(customer) == before + 1
    assert '📄 Dilnoza Karimova' in words and f'\n{EN["cv_linkedin_title"]}\n' in words, words
    assert '📝 Notes: “I want a job as a lead data analyst”' in words and 'Pages: 1–2' in words
    # The template, the language and the photo, which can be sent now.
    assert EN['cv_photo_none_add'] in words and 'Template: ' in words
    assert shown[0] == '✨ Generate' and EN['cv_template_button'] in shown
    assert FLAGS <= {label.replace('✅ ', '') for label in shown}, shown
    data = latest(customer, CV)
    assert data['options']['cv_source'] == 'linkedin' and data['source_ids'] == [str(profile.id)]
    assert data['prompt'] == 'I want a job as a lead data analyst' and 'portrait_asset_id' not in data['options']
    assert state(customer)[0] == 'cv_review' and state(customer)[1]['draft_id'] == str(cv(customer).id)
    # The file is the CV's, never a file task: the menu offers none to continue.
    assert BotInputReceipt.objects.filter(account=customer, asset=profile).count() == 1
    assert not file_task_waiting(customer)
    assert EN['continue_task'] not in screen(dispatch_local(customer, text='/start'))[1]


@pytest.mark.parametrize('where', ['linkedin', 'file', 'text', 'choose'])
def test_a_linkedin_link_is_answered_with_the_way_to_save_the_profile(customer, model, where):
    if where == 'choose':
        dispatch_local(customer, text='/cv')
    else:
        choose(customer, f'cv_mode_{where}')
    words, _ = screen(dispatch_local(customer, text='https://www.linkedin.com/in/dilnoza-karimova-a1b2c3'))
    for key in ('cv_linkedin_link_sent', 'cv_linkedin_computer', 'cv_linkedin_phone'):
        assert EN[key] in words, (key, words)
    assert EN['cv_linkedin_ask'] not in words
    assert state(customer)[0] == 'cv_source' and state(customer)[1]['cv_source'] == 'linkedin'
    # Nothing is opened or stored: the link is no file.
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert not FileAsset.objects.filter(account=customer).exists()


@needs_tesseract
def test_screenshots_sent_as_an_album_make_one_cv_from_all_of_them(customer, model, monkeypatch):
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0.3)
    choose(customer, 'cv_mode_linkedin')
    group = secrets.token_hex(6)
    feed_together(customer, [(upload('top.png', shot(0)), 'Lead data analyst roles, please', group),
                             (upload('education.png', shot(1)), '', group)], 0.02)
    top, education = (FileAsset.objects.get(account=customer, name=name) for name in ('top.png', 'education.png'))
    assert GenerationDraft.objects.filter(account=customer).count() == 1
    data = latest(customer, CV)
    assert data['source_ids'] == [str(top.id), str(education.id)] and data['options']['cv_source'] == 'linkedin'
    assert data['prompt'] == 'Lead data analyst roles, please' and 'portrait_asset_id' not in data['options']
    assert data['title'] == 'Dilnoza Karimova' and all(excerpt.get('ocr') for excerpt in data['excerpts'])
    newest = LocalBotMessage.objects.filter(account=customer, direction='outbound').order_by('-created_at').first()
    assert '📄 Dilnoza Karimova' in newest.text and EN['cv_linkedin_title'] in newest.text, newest.text
    assert not file_task_waiting(customer)


@needs_tesseract
def test_the_end_of_an_album_that_came_late_joins_its_cv_and_a_photo_after_the_review_is_asked_about(
        customer, model, monkeypatch):
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0)
    choose(customer, 'cv_mode_linkedin')
    group = secrets.token_hex(6)
    send(customer, 'top.png', shot(0), group=group)
    draft = cv(customer)
    before = outbound(customer)
    # Telegram delivered the album's last screenshot after its review was drawn.
    words, _ = screen(send(customer, 'education.png', shot(1), group=group))
    top, education = (FileAsset.objects.get(account=customer, name=name) for name in ('top.png', 'education.png'))
    assert words.startswith(EN['cv_files_added']) and EN['cv_linkedin_title'] in words, words
    assert outbound(customer) == before, 'the review is changed in place'
    assert GenerationDraft.objects.filter(account=customer).count() == 1 and cv(customer).id == draft.id
    assert latest(customer, CV)['source_ids'] == [str(top.id), str(education.id)]
    # Made from screenshots, the review says how more of them are sent; a photo
    # sent on its own once it is on screen may be the portrait or one more page: asked.
    assert EN['cv_photo_none_add_pages'] in words, words
    question = dispatch_local(customer, uploaded=image())
    words, shown = screen(question)
    me = FileAsset.objects.get(account=customer, name='me.jpg')
    assert words == EN['cv_photo_or_page'] and shown == [EN['cv_photo_is_portrait'], EN['cv_photo_is_page']], words
    assert 'portrait_asset_id' not in latest(customer, CV)['options']
    words, _ = screen(tap(customer, question, EN['cv_photo_is_portrait']))
    data = latest(customer, CV)
    assert EN['cv_photo_line'] in words and data['options']['portrait_asset_id'] == str(me.id), words
    assert data['source_ids'] == [str(top.id), str(education.id)]
    assert not file_task_waiting(customer)


def test_a_word_file_is_no_linkedin_profile(customer, model, word_pages):
    choose(customer, 'cv_mode_linkedin')
    words, shown = screen(send(customer, 'old-cv.docx', docx_cv()))
    assert ERRORS['en']['cv_file_kind'] in words, words
    assert shown == [EN['cv_send_another'], EN['cv_write_instead'], EN['home']]
    assert not FileAsset.objects.filter(account=customer).exists()
    # A kind no CV is made from is never even downloaded.
    words, _ = screen(send(customer, 'table.xlsx', b'PK\x03\x04 not a workbook'))
    assert ERRORS['en']['cv_file_kind'] in words and not FileAsset.objects.filter(account=customer).exists()
    assert state(customer)[0] == 'cv_source' and not file_task_waiting(customer)


# --- From the old CV ---------------------------------------------------------------------------

def test_an_old_cv_pdf_becomes_a_review_and_then_the_cv(customer):
    save_config('ai', {'mode': 'local_fixture'})
    words, shown = screen(choose(customer, 'cv_mode_file'))
    assert EN['cv_file_title'] in words and EN['cv_file_ask'] in words and EN['cv_notes_hint'] in words, words
    review = send(customer, 'old-cv.pdf', one_column_pdf(), caption='Looking for a lead engineer role')
    words, shown = screen(review)
    old = FileAsset.objects.get(account=customer, name='old-cv.pdf')
    assert '📄 Timur Rakhimov' in words and '\n📎 From: old-cv.pdf\n' in words, words
    assert '📝 Notes: “Looking for a lead engineer role”' in words and EN['cv_photo_none_add'] in words
    data = latest(customer, CV)
    assert data['options']['cv_source'] == 'file' and data['source_ids'] == [str(old.id)]
    assert data['prompt'] == 'Looking for a lead engineer role'
    delivered = tap(customer, review, 'Generate')
    job = Job.objects.get(account=customer, feature_id=CV)
    assert job.status == 'succeeded', job.error_code
    made = job.artifacts.get().file
    assert made.name == f'Timur-Rakhimov-CV-{job.id.hex[:6]}.pdf' and made.page_count in (1, 2)
    assert LocalBotMessage.objects.filter(account=customer, direction='outbound', asset=made).exists()
    assert '✏️ Make changes' in [button['label'] for message in delivered['messages'] for row in message['buttons']
                                for button in row]
    assert not file_task_waiting(customer)


def test_an_old_cv_in_word_becomes_a_review(customer, model, word_pages):
    choose(customer, 'cv_mode_file')
    words, _ = screen(send(customer, 'old-cv.docx', docx_cv()))
    word = FileAsset.objects.get(account=customer, name='old-cv.docx')
    assert '📄 Javlon Ergashev' in words and '📎 From: old-cv.docx' in words and '📝 Notes' not in words, words
    data = latest(customer, CV)
    assert data['options']['cv_source'] == 'file' and data['source_ids'] == [str(word.id)] and data['prompt'] == ''


@needs_tesseract
def test_a_photo_on_the_old_cv_screen_is_a_page_to_read_not_the_portrait(customer, model):
    choose(customer, 'cv_mode_file')
    words, _ = screen(send(customer, 'page.jpg', picture(one_column_pdf(), 2.0, 'JPEG')))
    page = FileAsset.objects.get(account=customer, name='page.jpg')
    data = latest(customer, CV)
    assert data['source_ids'] == [str(page.id)] and 'portrait_asset_id' not in data['options']
    assert data['excerpts'][0]['ocr'] is True
    assert '📄 Timur Rakhimov' in words and '📎 From: page.jpg' in words and EN['cv_photo_none_add'] in words, words


def test_notes_written_before_the_file_wait_for_it(customer, model):
    choose(customer, 'cv_mode_file')
    notes = 'I want a lead engineer job now; leave out the address'
    words, _ = screen(dispatch_local(customer, text=notes))
    assert f'📝 Noted: “{notes}”.\n{EN["cv_send_file_now"]}' in words and EN['cv_file_ask'] in words, words
    assert state(customer)[1]['notes'] == [notes]
    assert not GenerationDraft.objects.filter(account=customer).exists()
    # The caption is more of the notes, and the file's facts are the CV's.
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf(), caption='Add my driving licence (B)'))
    assert latest(customer, CV)['prompt'] == f'{notes}\nAdd my driving licence (B)'
    assert f'📝 Notes: “{notes} · Add my driving licence (B)”' in words and '📄 Timur Rakhimov' in words, words
    # Notes sent just after the file are its notes too.
    draft = cv(customer)
    words, _ = screen(dispatch_local(customer, text='Target employer: Example Motors'))
    assert words.startswith(EN['cv_notes_added']) and cv(customer).id == draft.id, words
    assert latest(customer, CV)['prompt'] == f'{notes}\nAdd my driving licence (B)\nTarget employer: Example Motors'


@pytest.mark.parametrize('name,raw', [('blank.pdf', blank_pdf), ('locked.pdf', encrypted_pdf)])
def test_a_file_with_nothing_to_read_offers_another_file_or_writing_instead(customer, model, name, raw):
    choose(customer, 'cv_mode_file')
    dispatch_local(customer, text='Lead engineer roles')
    words, shown = screen(send(customer, name, raw()))
    assert ERRORS['en']['cv_file_unreadable'] in words, words
    assert shown == [EN['cv_send_another'], EN['cv_write_instead'], EN['home']]
    assert actions(customer) == [['cv_mode'], ['cv_mode'], ['home']]
    assert not GenerationDraft.objects.filter(account=customer).exists()
    assert state(customer)[0] == 'cv_source' and state(customer)[1]['notes'] == ['Lead engineer roles']
    # Another file is read at once, with the notes still on it.
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf()))
    assert '📄 Timur Rakhimov' in words and latest(customer, CV)['prompt'] == 'Lead engineer roles', words


def test_the_ways_on_from_a_file_that_could_not_be_used(customer, model):
    choose(customer, 'cv_mode_file')
    dispatch_local(customer, text='Lead engineer roles')
    words, _ = screen(tap(customer, send(customer, 'blank.pdf', blank_pdf()), EN['cv_send_another']))
    assert EN['cv_file_ask'] in words and '📝 Noted: “Lead engineer roles”.' in words, words
    assert state(customer)[1]['notes'] == ['Lead engineer roles']
    # Writing about yourself instead keeps the notes as the start of the description, and asks for the rest.
    words, _ = screen(tap(customer, send(customer, 'blank.pdf', blank_pdf()), EN['cv_write_instead']))
    assert '📝 Noted: “Lead engineer roles”.' in words and EN['cv_missing_title'] in words, words
    for fact in ('name', 'contact', 'background'):
        assert f'• {EN["cv_fact_" + fact]} — e.g.' in words, (fact, words)
    assert state(customer) == ('ai_input', {'feature_id': CV, 'brief': ['Lead engineer roles'], 'ask': 'missing',
                                            'missing': ['name', 'contact', 'background']})
    # With nothing written, it is the question about yourself as it always was.
    choose(customer, 'cv_mode_file')
    words, _ = screen(tap(customer, send(customer, 'blank.pdf', blank_pdf()), EN['cv_write_instead']))
    assert words.startswith(f'<b>{TOOL_NAMES[CV]["en"]}</b>\n{EN["cv_ask"]}') and state(customer)[0] == 'ai_input'


def test_too_many_files_for_one_cv_are_said_with_how_many_it_takes(customer, model, monkeypatch):
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0.3)
    monkeypatch.setattr('apps.studio.cv.sources.MAX_FILES', 1)
    choose(customer, 'cv_mode_file')
    group = secrets.token_hex(6)
    feed_together(customer, [(upload('page-1.pdf', one_column_pdf()), '', group),
                             (upload('page-2.pdf', nameless_pdf()), '', group)], 0.02)
    newest = LocalBotMessage.objects.filter(account=customer, direction='outbound').order_by('-created_at').first()
    assert '📎 That’s too much for one CV: at most 1 file, 30 pages in all.' in newest.text, newest.text
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_file_that_names_nobody_asks_for_the_name_and_keeps_the_file_and_the_notes(customer, model):
    choose(customer, 'cv_mode_file')
    dispatch_local(customer, text='Make it one page')
    words, shown = screen(send(customer, 'cv.pdf', nameless_pdf()))
    nameless = FileAsset.objects.get(account=customer, name='cv.pdf')
    # The file gives a phone and a job: only the name is asked for, and what is there is said.
    assert EN['cv_file_missing_question'] in words and EN['cv_missing_title'] in words, words
    assert f'• {EN["cv_fact_name"]} — e.g. <code>Dilnoza Rahimova</code>' in words, words
    assert EN['cv_got'].format(facts=f'{EN["cv_fact_contact"]} · {EN["cv_fact_background"]}') in words, words
    assert '<code>+998 90 123 45 67</code>' not in words and 'Bahor Foods' not in words
    assert '📎 From: cv.pdf' in words and '📝 Noted: “Make it one page”.' in words
    # What is sent is added to the file; the customer wrote notes, so the way past an unseen name is said.
    assert EN['cv_missing_send_file'] in words and EN['cv_missing_send'] not in words
    assert words.endswith(EN['cv_name_again']) and EN['cv_missing_again'] not in words
    assert shown == [EN['cv_send_another'], EN['cv_write_instead'], EN['ai_back'], EN['home']]
    assert state(customer) == ('cv_source', {'feature_id': CV, 'cv_source': 'file', 'notes': ['Make it one page'],
                                             'source_ids': [str(nameless.id)], 'ask': 'missing', 'missing': ['name']})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    words, _ = screen(dispatch_local(customer, text='Javlon Ergashev'))
    assert '📄 Javlon Ergashev' in words and '📎 From: cv.pdf' in words, words
    data = latest(customer, CV)
    assert data['prompt'] == 'Javlon Ergashev\nMake it one page' and data['source_ids'] == [str(nameless.id)]


def facts_listed(words):
    """The required facts a screen lists as missing, in the order it lists them."""
    return [fact for fact in ('name', 'contact', 'background') if f'• {EN["cv_fact_" + fact]} — ' in words]


def test_a_file_that_gives_no_contact_asks_for_it_and_is_read_once(customer, model, monkeypatch):
    from django.core.cache import cache
    from apps.studio import extraction
    calls = []
    real = extraction.read_cv
    monkeypatch.setattr(extraction, 'read_cv', lambda *args, **kwargs: calls.append(args[1]) or real(*args, **kwargs))
    choose(customer, 'cv_mode_linkedin')
    words, shown = screen(send(customer, 'Profile.pdf', linkedin_without_contact()))
    profile = FileAsset.objects.get(account=customer, name='Profile.pdf')
    # Its name and its jobs are in the file: only how to reach the person is asked for.
    assert facts_listed(words) == ['contact'] and EN['cv_file_missing_question'] in words, words
    assert EN['cv_got'].format(facts=f'{EN["cv_fact_name"]} · {EN["cv_fact_background"]}') in words
    # Nothing written, only the file: no line says the customer wrote something; how to go on without a contact is said.
    assert words.endswith(f'{EN["cv_missing_send_file"]}\n{EN["cv_missing_twice_contact"]}'), words
    assert EN['cv_name_again'] not in words and EN['cv_missing_again'] not in words and 'you wrote' not in words
    assert '📎 From: Profile.pdf' in words and EN['cv_linkedin_title'] in words
    assert shown == [EN['cv_send_another'], EN['cv_write_instead'], EN['ai_back'], EN['home']]
    assert state(customer) == ('cv_source', {'feature_id': CV, 'cv_source': 'linkedin', 'notes': [],
                                             'source_ids': [str(profile.id)], 'ask': 'missing', 'missing': ['contact']})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    # The phone is the answer: the file is not read again, and the review follows at once.
    words, _ = screen(dispatch_local(customer, text=PHONE))
    assert '📄 Dilnoza Karimova' in words and EN['cv_linkedin_title'] in words and EN['cv_missing_title'] not in words, words
    data = latest(customer, CV)
    assert data['prompt'] == PHONE and data['source_ids'] == [str(profile.id)]
    assert calls == ['pdf'] and cache.get(f'rate:bot_generation:{customer.pk}') == 2
    assert generation.facts_of(cv(customer))['missing'] == []


def test_what_a_file_and_its_notes_do_not_give_is_asked_for_together_and_answered_in_pieces(customer, model):
    choose(customer, 'cv_mode_file')
    words, _ = screen(send(customer, 'skills.pdf', skills_only_pdf()))
    assert facts_listed(words) == ['name', 'contact', 'background'], words
    # Nothing written, and no work or studies in the file: nothing sent again could make it, so more is asked for.
    assert words.endswith(f'{EN["cv_missing_send_file"]}\n{EN["cv_missing_more"]}'), words
    assert EN['cv_got'].split('{')[0] not in words
    words, _ = screen(dispatch_local(customer, text='Dilnoza Karimova'))
    assert facts_listed(words) == ['contact', 'background'] and EN['cv_got'].format(facts=EN['cv_fact_name']) in words, words
    assert state(customer)[1]['notes'] == ['Dilnoza Karimova'] and state(customer)[1]['asked'] == 1
    words, _ = screen(dispatch_local(customer, text=PHONE))
    assert facts_listed(words) == ['background'], words
    assert state(customer)[1]['notes'] == [PHONE, 'Dilnoza Karimova'] and state(customer)[1]['asked'] == 2
    # A name and a phone sent again would make no CV: the screen asks for the work or studies instead.
    assert state(customer)[1]['missing'] == ['background'] and words.endswith(EN['cv_missing_more']), words
    assert EN['cv_missing_again'] not in words
    words, _ = screen(dispatch_local(customer, text='Accountant, Example Trade LLC, 2019-2024'))
    assert '📄 Dilnoza Karimova' in words and '📎 From: skills.pdf' in words, words
    assert latest(customer, CV)['prompt'] == f'Accountant, Example Trade LLC, 2019-2024\n{PHONE}\nDilnoza Karimova'


@pytest.mark.parametrize('locale', LOCALES)
def test_a_file_alone_is_never_said_to_be_something_the_customer_wrote(customer, model, locale):
    copy = UX[locale]
    speak(customer, locale)
    choose(customer, 'cv_mode_file', locale)
    words, _ = screen(send(customer, 'skills.pdf', skills_only_pdf()))
    assert [fact for fact in ('name', 'contact', 'background') if f'• {copy["cv_fact_" + fact]} — ' in words] == [
        'name', 'contact', 'background'], words
    # It asks for the work or studies the file lacks, never for something written again.
    assert copy['cv_file_missing_question'] in words, words
    assert words.endswith(f'{copy["cv_missing_send_file"]}\n{copy["cv_missing_more"]}'), words
    for key in ('cv_missing_send', 'cv_name_again', 'cv_missing_again', 'cv_missing_again_contact'):
        assert copy[key] not in words, key
    assert len(words) < 4096


def test_a_sample_sent_back_on_the_file_screen_is_answered_as_ours_and_not_counted(customer, model):
    from django.core.cache import cache
    choose(customer, 'cv_mode_linkedin')
    send(customer, 'Profile.pdf', linkedin_without_contact())
    builds = cache.get(f'rate:bot_generation:{customer.pk}')
    # The sample number and address, tapped and sent: the same screen, saying so; nothing kept, read or counted.
    for sample in ('+998 90 123 45 67', 'dilnoza@example.com\n+998 90 123 45 67'):
        words, _ = screen(dispatch_local(customer, text=sample))
        assert words.startswith(EN['cv_example_copied']) and facts_listed(words) == ['contact'], words
        assert state(customer)[1]['notes'] == [] and 'asked' not in state(customer)[1]
    assert cache.get(f'rate:bot_generation:{customer.pk}') == builds and not GenerationDraft.objects.filter(account=customer).exists()
    # The customer's own number makes the CV.
    words, _ = screen(dispatch_local(customer, text=PHONE))
    assert '📄 Dilnoza Karimova' in words and latest(customer, CV)['prompt'] == PHONE, words


def test_the_missing_screens_own_lines_copied_back_on_the_file_screen_are_answered_as_ours(customer, model):
    import html
    import re
    from django.core.cache import cache
    choose(customer, 'cv_mode_file')
    shown = html.unescape(re.sub(r'<[^>]+>', '', screen(send(customer, 'skills.pdf', skills_only_pdf()))[0]))
    bullets = '\n'.join(line for line in shown.split('\n') if line.startswith('• '))
    builds = cache.get(f'rate:bot_generation:{customer.pk}')
    for value in (bullets, shown):
        words, _ = screen(dispatch_local(customer, text=value))
        assert words.startswith(EN['cv_example_copied']), words
        assert facts_listed(words) == ['name', 'contact', 'background'], words
        assert state(customer)[1]['notes'] == [] and 'asked' not in state(customer)[1]
    assert cache.get(f'rate:bot_generation:{customer.pk}') == builds
    assert not GenerationDraft.objects.filter(account=customer).exists()


@pytest.mark.parametrize('locale,name', [('en', 'Aziz Karimov'), ('uz', 'Aziz Karimov'), ('ru', 'Азиз Каримов')], ids=LOCALES)
def test_the_copied_list_or_a_sample_phone_sent_again_on_the_file_screen_is_never_kept(customer, model, locale, name):
    from django.core.cache import cache
    from tests.test_bot_cv import OWN_IN_FORMAT, SAMPLE_PHONE, copied_list
    copy = UX[locale]
    speak(customer, locale)
    choose(customer, 'cv_mode_file', locale)
    bullets = copied_list(screen(send(customer, 'skills.pdf', skills_only_pdf()))[0])
    assert bullets.count('• ') == 3, bullets
    builds = cache.get(f'rate:bot_generation:{customer.pk}')

    def listed(words):
        return [fact for fact in ('name', 'contact', 'background') if f'• {copy["cv_fact_" + fact]} — ' in words]
    # The list copied back, a name with the sample's number, or the list's labels with the customer's own details:
    # our example however often it is sent; nothing kept, read or counted.
    for value in (bullets, SAMPLE_PHONE[locale], OWN_IN_FORMAT[locale]):
        for _ in range(3):
            words, _ = screen(dispatch_local(customer, text=value))
            assert words.startswith(copy['cv_example_copied']) and listed(words) == ['name', 'contact', 'background'], words
            assert state(customer)[1]['notes'] == [] and 'asked' not in state(customer)[1], value
    assert cache.get(f'rate:bot_generation:{customer.pk}') == builds
    # The customer's own name after it: the phone and the work are still asked for, and no CV is made of our example.
    cache.delete(f'rate:bot_generation:{customer.pk}')
    words, _ = screen(dispatch_local(customer, text=name))
    assert listed(words) == ['contact', 'background'] and copy['cv_example_copied'] not in words, words
    assert state(customer)[1]['notes'] == [name]
    assert not GenerationDraft.objects.filter(account=customer).exists()


@pytest.mark.parametrize('locale,greeting', [('en', 'Good morning'), ('uz', 'Hayrli kun'), ('ru', 'Добрый день')],
                         ids=LOCALES)
def test_a_greeting_sent_again_on_the_file_screen_never_makes_a_cv(customer, model, locale, greeting):
    from django.core.cache import cache
    copy = UX[locale]
    speak(customer, locale)
    # A file with a name and a phone but nothing done: the name is there, so only the work or studies decide.
    choose(customer, 'cv_mode_file', locale)
    words, _ = screen(send(customer, 'cv.pdf', jobless_pdf()))
    listed = [fact for fact in ('name', 'contact', 'background') if f'• {copy["cv_fact_" + fact]} — ' in words]
    assert listed == ['background'], words
    for _ in range(3):
        cache.delete(f'rate:bot_generation:{customer.pk}')
        words, _ = screen(dispatch_local(customer, text=greeting))
        assert not GenerationDraft.objects.filter(account=customer).exists(), words
        assert copy['cv_file_missing_question'] in words, words
    assert state(customer)[1]['notes'] == [greeting], 'the same words are kept once'
    # Sending it again cannot make the CV, so the screen never says to: it asks for the work or studies.
    assert words.endswith(copy['cv_missing_more']) and copy['cv_missing_again'] not in words, words
    # A file that gives nothing but skills, and the greeting sent again: all three are still missing, and no CV.
    choose(customer, 'cv_mode_file', locale)
    send(customer, 'skills.pdf', skills_only_pdf())
    for _ in range(2):
        cache.delete(f'rate:bot_generation:{customer.pk}')
        words, _ = screen(dispatch_local(customer, text=greeting))
    assert [fact for fact in ('name', 'contact', 'background') if f'• {copy["cv_fact_" + fact]} — ' in words] == [
        'name', 'contact', 'background'], words
    assert not GenerationDraft.objects.filter(account=customer).exists()


def test_a_description_the_check_missed_is_made_from_the_file_when_sent_again(customer, model):
    from django.core.cache import cache
    choose(customer, 'cv_mode_file')
    send(customer, 'cv.pdf', jobless_pdf())
    bio = 'I keep the books for a family bakery and sell bread at the counter on weekends'
    words, _ = screen(dispatch_local(customer, text=bio))
    # It says more than a name, a phone and an email: the screen offers the same again, and that makes the CV.
    assert facts_listed(words) == ['background'] and words.endswith(EN['cv_missing_again']), words
    cache.delete(f'rate:bot_generation:{customer.pk}')
    words, shown = screen(dispatch_local(customer, text=bio))
    assert '📄 Dilnoza Karimova' in words and shown[0] == '✨ Generate', words
    assert latest(customer, CV)['prompt'] == bio and generation.facts_of(cv(customer))['missing'] == ['background']


def test_the_newest_answers_on_the_file_screen_are_never_pushed_out_by_older_notes(customer, model):
    from django.core.cache import cache
    choose(customer, 'cv_mode_file')
    send(customer, 'skills.pdf', skills_only_pdf())

    def answer(value):
        # Answers spread over a few minutes, as a person types them: never the minute's limit.
        cache.delete(f'rate:bot_generation:{customer.pk}')
        return screen(dispatch_local(customer, text=value))[0]
    for number in range(11):
        answer(f'filler {number}')
    words = answer(f'Dilnoza Karimova, {PHONE}')
    assert facts_listed(words) == ['background'], words
    # Twelve kept already: one more answer drops an old filler, never the name and the phone.
    words = answer('ok thanks')
    assert facts_listed(words) == ['background'], words
    notes = state(customer)[1]['notes']
    assert len(notes) == 12 and notes[:2] == ['ok thanks', f'Dilnoza Karimova, {PHONE}'] and notes[-1] == 'filler 0', notes
    # Facts answered one by one still add up.
    words = answer('Accountant, Example Trade LLC, 2019-2024')
    assert '📄 Dilnoza Karimova' in words, words
    prompt = latest(customer, CV)['prompt'].split('\n')
    assert prompt[:3] == ['Accountant, Example Trade LLC, 2019-2024', 'ok thanks', f'Dilnoza Karimova, {PHONE}'], prompt
    assert len(prompt) == 12 and prompt[-1] == 'filler 0'


def test_long_notes_on_the_file_screen_make_room_for_the_newest_not_the_oldest(customer, model):
    from telegram.bot import CV_BRIEF_CHARS
    choose(customer, 'cv_mode_file')
    send(customer, 'skills.pdf', skills_only_pdf())
    # Three long answers that give nothing, as long as Telegram sends at once: together they nearly fill the CV's room.
    first, second, third = (' '.join([word] + ['filler'] * 700)[:3999] + 'x' for word in ('first', 'second', 'third'))
    assert len(first) == len(second) == len(third) == 4000
    for value in (first, second, third):
        screen(dispatch_local(customer, text=value))
    assert state(customer)[1]['notes'] == [third, second, first]
    answer = f'Dilnoza Karimova, {PHONE}'
    assert len(answer) + len(first) + len(second) + len(third) > CV_BRIEF_CHARS
    words, _ = screen(dispatch_local(customer, text=answer))
    # The answer and the newest note are kept, and the first note; the one between makes room.
    assert facts_listed(words) == ['background'], words
    assert state(customer)[1]['notes'] == [answer, third, first]
    assert sum(map(len, state(customer)[1]['notes'])) <= CV_BRIEF_CHARS


def test_the_same_answer_sent_again_makes_the_cv_from_the_file_with_its_contact_missing(customer, model):
    from django.core.cache import cache
    choose(customer, 'cv_mode_linkedin')
    send(customer, 'Profile.pdf', linkedin_without_contact())
    words, _ = screen(dispatch_local(customer, text='Please write to me after six'))
    assert facts_listed(words) == ['contact'] and not GenerationDraft.objects.filter(account=customer).exists(), words
    # The same words again are taken as they are: made, once, with the lack said on the review.
    words, shown = screen(dispatch_local(customer, text='please write to me after six'))
    assert '📄 Dilnoza Karimova' in words and shown[0] == '✨ Generate', words
    assert latest(customer, CV)['prompt'] == 'Please write to me after six'
    assert '💡 You can still add: phone or email' in words and generation.facts_of(cv(customer))['missing'] == ['contact']
    assert GenerationDraft.objects.filter(account=customer).count() == 1
    assert cache.get(f'rate:bot_generation:{customer.pk}') == 3, 'each answer is a build of the minute'


def test_a_name_missing_from_a_file_is_taken_when_sent_again_only_if_it_looks_like_one(customer, model):
    choose(customer, 'cv_mode_file')
    send(customer, 'cv.pdf', nameless_pdf())
    words, _ = screen(dispatch_local(customer, text='what do you mean'))
    assert facts_listed(words) == ['name'], words
    words, _ = screen(dispatch_local(customer, text='what do you mean'))
    assert facts_listed(words) == ['name'] and not GenerationDraft.objects.filter(account=customer).exists(), words
    dispatch_local(customer, text='dilnoza karimova')
    words, _ = screen(dispatch_local(customer, text='dilnoza karimova'))
    assert '📄 dilnoza karimova' in words and 'full name' in words, words
    assert latest(customer, CV)['prompt'] == 'dilnoza karimova\nwhat do you mean'


def test_a_question_kept_before_the_facts_were_listed_is_answered_for_the_file_too(customer, model):
    choose(customer, 'cv_mode_file')
    send(customer, 'cv.pdf', nameless_pdf())
    nameless = FileAsset.objects.get(account=customer, name='cv.pdf')
    # The screen as an earlier release kept it: asking for the name, with no list.
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(
        prompt={'feature_id': CV, 'cv_source': 'file', 'notes': [], 'source_ids': [str(nameless.id)], 'ask': 'name'})
    words, _ = screen(dispatch_local(customer, text='Javlon Ergashev'))
    assert '📄 Javlon Ergashev' in words and latest(customer, CV)['source_ids'] == [str(nameless.id)], words
    BotConversation.objects.filter(pk=customer.telegram_user_id).update(
        state='cv_source', prompt={'feature_id': CV, 'cv_source': 'file', 'notes': [], 'source_ids': [str(nameless.id)],
                                   'ask': 'name'}, updated_at=timezone.now())
    words, _ = screen(send(customer, 'more.pdf', one_column_pdf()))
    # A file sent on that screen is read beside the first, and the answer is no longer asked for.
    assert '📎 From: cv.pdf, more.pdf' in words and EN['cv_missing_title'] not in words, words


def test_change_the_description_goes_back_to_the_file_the_cv_was_made_from(customer, model):
    choose(customer, 'cv_mode_file')
    review = send(customer, 'old-cv.pdf', one_column_pdf(), caption='Lead engineer roles')
    old = FileAsset.objects.get(account=customer, name='old-cv.pdf')
    words, shown = screen(tap(customer, review, 'Change the description'))
    assert EN['cv_file_title'] in words and '📎 From: old-cv.pdf' in words and EN['cv_files_kept'] in words, words
    assert '📝 Noted: “Lead engineer roles”.' in words
    assert state(customer) == ('cv_source', {'feature_id': CV, 'cv_source': 'file', 'notes': ['Lead engineer roles'],
                                             'source_ids': [str(old.id)], 'ask': 'again'})
    words, _ = screen(dispatch_local(customer, text='Senior engineer roles in Tashkent'))
    data = latest(customer, CV)
    assert data['source_ids'] == [str(old.id)] and data['prompt'] == 'Senior engineer roles in Tashkent'
    assert '📝 Notes: “Senior engineer roles in Tashkent”' in words and '📄 Timur Rakhimov' in words, words
    assert GenerationDraft.objects.filter(account=customer).count() == 2
    assert FileAsset.objects.filter(account=customer).count() == 1, 'the file was not sent again'


# --- Kept as long as a question ----------------------------------------------------------------

def test_the_cv_screens_are_kept_as_long_as_a_question(customer, model):
    choose(customer, 'cv_mode_file')
    dispatch_local(customer, text='Lead engineer roles')
    age(customer, 29)
    send(customer, 'old-cv.pdf', one_column_pdf())
    assert latest(customer, CV)['prompt'] == 'Lead engineer roles'
    # Half an hour on, what was written is the menu's, as an old question's answer is.
    choose(customer, 'cv_mode_linkedin')
    age(customer, 31)
    words, _ = screen(dispatch_local(customer, text='Lead data analyst roles'))
    assert words.startswith(COPY['en']['stale_reply']) and state(customer) == ('', {}), words
    # And a file is an ordinary file, never a CV made from what someone sent much later.
    choose(customer, 'cv_mode_file')
    age(customer, 31)
    drafts = GenerationDraft.objects.filter(account=customer).count()
    send(customer, 'report.pdf', one_column_pdf())
    assert GenerationDraft.objects.filter(account=customer).count() == drafts and file_task_waiting(customer)


def test_the_first_screens_buttons_work_however_old(customer, model):
    first = dispatch_local(customer, text='/cv')
    BotCallback.objects.filter(account=customer, action='cv_mode').update(expires_at=timezone.now() - timedelta(days=1))
    dispatch_local(customer, text='/start')
    tap(customer, first, EN['cv_mode_file'])
    # The old screen becomes the old-CV screen, in place.
    assert EN['cv_file_ask'] in LocalBotMessage.objects.get(pk=first['messages'][-1]['id']).text
    assert state(customer)[0] == 'cv_source' and state(customer)[1]['cv_source'] == 'file'


def test_the_same_file_delivered_twice_is_one_file(customer, model, monkeypatch):
    choose(customer, 'cv_mode_file')
    # Telegram sends the same update again: the same message id.
    monkeypatch.setattr('telegram.local.secrets.randbelow', lambda limit: 77)
    send(customer, 'old-cv.pdf', one_column_pdf())
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf()))
    assert '📄 Timur Rakhimov' in words and '📎 From: old-cv.pdf' in words, words
    assert FileAsset.objects.filter(account=customer).count() == 1
    assert GenerationDraft.objects.filter(account=customer).count() == 1


def test_the_same_file_delivered_twice_draws_the_same_question_for_what_it_lacks(customer, model, monkeypatch):
    choose(customer, 'cv_mode_file')
    monkeypatch.setattr('telegram.local.secrets.randbelow', lambda limit: 78)
    first = screen(send(customer, 'skills.pdf', skills_only_pdf()))
    again = screen(send(customer, 'skills.pdf', skills_only_pdf()))
    assert facts_listed(first[0]) == facts_listed(again[0]) == ['name', 'contact', 'background']
    assert state(customer)[1]['missing'] == ['name', 'contact', 'background']
    assert FileAsset.objects.filter(account=customer).count() == 1


@pytest.mark.parametrize('locale', LOCALES)
def test_the_review_says_where_the_cv_came_from_in_every_language(customer, model, locale):
    speak(customer, locale)
    choose(customer, 'cv_mode_file', locale)
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf(), caption='Lead engineer roles'))
    assert UX[locale]['cv_from_files'].format(files='old-cv.pdf') in words, words
    assert UX[locale]['cv_notes_line'].format(notes='Lead engineer roles') in words
    choose(customer, 'cv_mode_linkedin', locale)
    words, _ = screen(send(customer, 'Profile.pdf', linkedin_pdf()))
    assert f'\n{UX[locale]["cv_linkedin_title"]}\n' in words, words


# --- Reading each file once (the reader's queue in the chat: tests/test_bot_cv_read_queue.py) -----------

def reading(pages=(('Timur Rakhimov', '+998 90 123 45 67. Lead engineer at Example Motors since 2020; MSc Mechanical Engineering.'),),
            seconds=0.0, calls=None, ocr=False):
    """extraction.read_cv as a fake: every file reads as `pages` (name, text) after `seconds`, noting the thread it ran on."""
    import threading
    import time

    def read_cv(path, kind, *, ocr_pages, seconds=None, **_):
        if calls is not None:
            calls.append((threading.current_thread().name, kind))
        time.sleep(reading_seconds)
        return {'pages': [{'page': number, 'text': f'{name}\n{text}', **({'ocr': True} if ocr else {})}
                          for number, (name, text) in enumerate(pages, 1)],
                'names': [pages[0][0]], 'ocr_pages': len(pages) if ocr else 0, 'ocr_skipped': 0}
    reading_seconds = seconds
    return read_cv


def another_customer():
    from apps.core.identity import resolve_account
    from tests.test_manual_payments import paid
    other = resolve_account({'id': 980412, 'first_name': 'Another chat'}, is_test=True)
    BotConversation.objects.create(telegram_user_id=other.telegram_user_id, locale='en',
                                   language_selected_at=timezone.now())
    paid(other, 'premium')
    return other


def feed_two(first, upload, second, text, delay):
    """A file from one chat and, `delay` seconds later, a message from another, fed to one dispatcher as polling feeds
    them (handle_as_tasks): how long after the start each was answered."""
    import asyncio
    import time
    from datetime import datetime, timezone as tz
    from aiogram import Bot
    from aiogram.types import Chat, Document, Message, Update, User
    from asgiref.sync import async_to_sync
    from telegram.local import LocalTelegramSession

    def update(account, number, **fields):
        LocalBotMessage.objects.create(account=account, direction='inbound', text='sample', telegram_message_id=number)
        return Update(update_id=number, message=Message(
            message_id=number, date=datetime.now(tz.utc), chat=Chat(id=account.telegram_user_id, type='private'),
            from_user=User(id=account.telegram_user_id, is_bot=False, first_name='Sample', language_code='en'), **fields))
    sessions = {first.pk: LocalTelegramSession(first), second.pk: LocalTelegramSession(second)}
    sessions[first.pk].files['f' * 24] = upload.read()
    updates = [(first, update(first, 7001, document=Document(file_id='f' * 24, file_unique_id='f' * 24,
                                                               file_name=upload.name, file_size=upload.size))),
               (second, update(second, 7002, text=text, entities=[{'type': 'bot_command', 'offset': 0,
                                                                  'length': len(text)}]))]
    answered = {}

    async def run():
        from telegram.bot import build_dispatcher
        bots = {pk: Bot('123456:LOCAL_SIMULATOR_NO_NETWORK', session=session) for pk, session in sessions.items()}
        dispatcher = build_dispatcher()
        begun = time.monotonic()

        async def one(account, item, wait):
            await asyncio.sleep(wait)
            await dispatcher.feed_update(bots[account.pk], item)
            answered[account.pk] = time.monotonic() - begun
        try:
            await asyncio.gather(one(*updates[0], 0), one(*updates[1], delay))
        finally:
            for bot in bots.values():
                await bot.session.close()
    async_to_sync(run)()
    return answered[first.pk], answered[second.pk]


def test_a_file_that_names_nobody_is_read_once_however_the_name_is_answered(customer, model, monkeypatch):
    from django.core.cache import cache
    from apps.studio import extraction
    calls = []
    real = extraction.read_cv
    monkeypatch.setattr(extraction, 'read_cv', lambda *args, **kwargs: calls.append(args[1]) or real(*args, **kwargs))
    choose(customer, 'cv_mode_file')
    send(customer, 'cv.pdf', nameless_pdf())
    for answer in ('hello there', 'what do you mean'):
        words, _ = screen(dispatch_local(customer, text=answer))
        assert EN['cv_file_missing_question'] in words and f'• {EN["cv_fact_name"]} — e.g.' in words, words
    assert calls == ['pdf']
    # Each answer is a build of the minute's ten: answers that name nobody cannot go on for ever.
    assert cache.get(f'rate:bot_generation:{customer.pk}') == 3
    words, _ = screen(dispatch_local(customer, text='Javlon Ergashev'))
    assert '📄 Javlon Ergashev' in words and calls == ['pdf'], words


def test_a_refusal_that_passes_keeps_the_files_to_try_again(customer, model):
    from django.core.cache import cache
    choose(customer, 'cv_mode_file')
    cache.set(f'rate:bot_generation:{customer.pk}', 10, 60)
    refused = send(customer, 'old-cv.pdf', one_column_pdf(), caption='Lead engineer roles')
    words, shown = screen(refused)
    old = FileAsset.objects.get(account=customer, name='old-cv.pdf')
    assert words.startswith(ERRORS['en']['rate_limited']) and '📎 From: old-cv.pdf' in words, words
    assert shown[0] == EN['cv_try_again']
    assert state(customer) == ('cv_source', {'feature_id': CV, 'cv_source': 'file', 'notes': ['Lead engineer roles'],
                                             'source_ids': [str(old.id)], 'ask': 'again'})
    cache.delete(f'rate:bot_generation:{customer.pk}')
    words, _ = screen(tap(customer, refused, EN['cv_try_again']))
    assert '📄 Timur Rakhimov' in words and '📝 Notes: “Lead engineer roles”' in words, words
    assert latest(customer, CV)['source_ids'] == [str(old.id)] and FileAsset.objects.filter(account=customer).count() == 1


def test_a_pdf_sent_on_the_question_about_yourself_leads_to_the_old_cv_screen(customer, model):
    choose(customer, 'cv_mode_text')
    nameless = 'Data analyst with five years in retail; SQL and Power BI; English and Russian.'
    words, _ = screen(dispatch_local(customer, text=nameless))
    assert EN['cv_missing_title'] in words and f'• {EN["cv_fact_name"]} — e.g.' in words, words
    offered = send(customer, 'old-cv.pdf', one_column_pdf())
    words, shown = screen(offered)
    assert EN['cv_photo_only'] in words and EN['cv_mode_file'] in shown, (words, shown)
    assert shown[-1] == EN['ai_back']
    # The old-CV screen keeps what was written, as notes on top of the file.
    words, _ = screen(tap(customer, offered, EN['cv_mode_file']))
    assert EN['cv_file_ask'] in words and f'📝 Noted: “{nameless}”.' in words, words
    assert state(customer)[1]['notes'] == [nameless] and state(customer)[1]['cv_source'] == 'file'
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf()))
    assert '📄 Timur Rakhimov' in words and latest(customer, CV)['prompt'] == nameless, words


def test_a_photo_with_nothing_to_read_on_the_first_screen_is_the_cvs_photo(customer, model):
    from tests.test_cv_content import BRIEF
    dispatch_local(customer, text='/cv')
    # With a description as its caption: the CV written from it, with the photo, as the question about yourself takes it.
    words, _ = screen(dispatch_local(customer, uploaded=image(), caption=BRIEF))
    me = FileAsset.objects.get(account=customer, name='me.jpg')
    data = latest(customer, CV)
    assert '📄 Dilnoza Karimova' in words and EN['cv_photo_line'] in words and '📎 From' not in words, words
    assert data['options']['portrait_asset_id'] == str(me.id) and 'cv_source' not in data['options']
    assert data['prompt'] == BRIEF and data['source_ids'] == []
    # Without one: the first screen again, keeping the photo, saying how to send an old CV instead.
    dispatch_local(customer, text='/cv')
    kept = dispatch_local(customer, uploaded=image('portrait.jpg'))
    words, _ = screen(kept)
    portrait = FileAsset.objects.get(account=customer, name='portrait.jpg')
    assert words.startswith(EN['cv_photo_kept_choose']) and EN['cv_choose_ask'] in words, words
    assert state(customer) == ('cv_choose', {'feature_id': CV, 'portrait_asset_id': str(portrait.id)})
    words, _ = screen(tap(customer, kept, EN['cv_mode_text']))
    assert EN['cv_photo_attached'] in words and state(customer)[1]['portrait_asset_id'] == str(portrait.id), words


def test_more_screenshots_after_the_review_are_more_of_its_pages(customer, model, monkeypatch):
    from apps.studio import extraction
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0.3)
    calls = []
    monkeypatch.setattr(extraction, 'read_cv', reading(calls=calls, ocr=True, pages=(
        ('Dilnoza Karimova', '+998 90 123 45 67. Senior Data Analyst at Example Retail since 2022; SQL, Power BI.'),)))
    choose(customer, 'cv_mode_linkedin')
    send(customer, 'top.png', shot(0))
    first = FileAsset.objects.get(account=customer, name='top.png')
    # A second album sent once the review is on screen: never a portrait, more of the profile.
    group = secrets.token_hex(6)
    feed_together(customer, [(upload('more-1.png', shot(1)), '', group), (upload('more-2.png', shot(0)), '', group)], 0.02)
    more = [FileAsset.objects.get(account=customer, name=name) for name in ('more-1.png', 'more-2.png')]
    data = latest(customer, CV)
    assert data['source_ids'] == [str(first.id), *[str(asset.id) for asset in more]]
    assert 'portrait_asset_id' not in data['options'] and GenerationDraft.objects.filter(account=customer).count() == 1
    # Each file was read once, by the reader (here as it was queued: settings.LOCAL_SYNC_JOBS).
    assert len(calls) == 3, calls
    # One photo on its own: asked about, and as a page it is read with the others.
    question = dispatch_local(customer, uploaded=image('page-4.jpg'))
    assert screen(question)[0] == EN['cv_photo_or_page']
    words, _ = screen(tap(customer, question, EN['cv_photo_is_page']))
    page = FileAsset.objects.get(account=customer, name='page-4.jpg')
    data = latest(customer, CV)
    assert words.startswith(EN['cv_files_added']) and EN['cv_photo_none_add_pages'] in words, words
    assert data['source_ids'][-1] == str(page.id) and 'portrait_asset_id' not in data['options']
    assert len(calls) == 4
    assert not file_task_waiting(customer)


def test_a_cv_made_from_a_pdf_still_takes_a_photo_after_the_review_as_its_portrait(customer, model):
    choose(customer, 'cv_mode_file')
    words, _ = screen(send(customer, 'old-cv.pdf', one_column_pdf()))
    assert EN['cv_photo_none_add'] in words and EN['cv_photo_none_add_pages'] not in words, words
    words, _ = screen(dispatch_local(customer, uploaded=image()))
    me = FileAsset.objects.get(account=customer, name='me.jpg')
    assert EN['cv_photo_line'] in words and latest(customer, CV)['options']['portrait_asset_id'] == str(me.id), words


@pytest.mark.parametrize('locale', LOCALES)
def test_the_review_says_what_of_the_files_could_not_be_read(customer, model, monkeypatch, locale):
    from tests.test_cv_sources import scanned_pdf
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0.3)
    monkeypatch.setattr('apps.studio.cv.sources.MAX_OCR_PAGES', 0)
    speak(customer, locale)
    choose(customer, 'cv_mode_file', locale)
    group = secrets.token_hex(6)
    feed_together(customer, [(upload('old-cv.pdf', one_column_pdf()), '', group),
                             (upload('scan.pdf', scanned_pdf()), '', group)], 0.02)
    newest = LocalBotMessage.objects.filter(account=customer, direction='outbound').order_by('-created_at').first()
    from telegram.ux_copy import counted
    said = UX[locale]['cv_unread'].format(what=counted(locale, 1, 'page'))
    assert said in newest.text and '📄 Timur Rakhimov' in newest.text, newest.text
    assert latest(customer, CV)['cv_unread'] == [{'asset_id': str(FileAsset.objects.get(account=customer, name='scan.pdf').id),
                                                  'pages': 1}]


def test_files_said_puts_how_many_more_beside_the_files_it_names(customer):
    from telegram.bot import files_said, unread_said
    assert files_said(customer, ['a.pdf', 'b.pdf', 'c.pdf', 'photo.jpg', 'photo.jpg']) == 'a.pdf, b.pdf +1, 2 photos'
    assert files_said(customer, ['a.pdf', 'b.pdf']) == 'a.pdf, b.pdf'
    assert files_said(customer, ['photo.jpg']) == '1 photo'
    assert files_said(customer, ['', '']) == '2 files'
    assert unread_said(customer, 0, 0) == ''
    assert unread_said(customer, 1, 2) == EN['cv_unread'].format(what='1 file and 2 pages')


def test_a_word_cv_with_its_email_as_a_link_is_read_and_still_no_file_tools_file(customer, model, word_pages):
    from tests.test_cv_sources import docx_with_links
    choose(customer, 'cv_mode_file')
    words, _ = screen(send(customer, 'old-cv.docx', docx_with_links()))
    assert '📄 Kamola Nazarova' in words and '📎 From: old-cv.docx' in words, words
    assert 'kamola.nazarova@example.com' in latest(customer, CV)['excerpts'][0]['text']
    # Sent for the file tools, the same file is refused as it always was.
    dispatch_local(customer, text='/start')
    words, _ = screen(send(customer, 'report.docx', docx_with_links()))
    assert words == ERRORS['en']['external_content_unsupported'], words
    assert not FileAsset.objects.filter(account=customer, name='report.docx').exists()
