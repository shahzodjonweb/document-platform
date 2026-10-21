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
from telegram.bot import COPY
from telegram.errors import COPY as ERRORS
from telegram.local import dispatch_local
from telegram.ux_copy import LOCALES, TOOL_NAMES, UX
from tests.test_bot_cv import FLAGS, actions, cv, feed_together, file_task_waiting, image, model, screen, state  # noqa: F401
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
    """An old CV that names nobody: what the person did, never who they are."""
    return _pdf(lambda page, _: _lines(page, 60, 780, [
        ('Helvetica', 11, 'Experience: accountant at Example Trade LLC, 2019 - 2024.', 16),
        ('Helvetica', 11, 'Skills: 1C, Excel, IFRS reporting, payroll, tax returns.', 16)]))


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
    assert words.startswith(f'<b>{TOOL_NAMES[CV]["en"]}</b>\n{EN["cv_ask"]}\n<i>{EN["cv_photo_hint"]}</i>'), words
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
    assert made.name == 'Timur Rakhimov CV.pdf' and made.page_count in (1, 2)
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
    assert '📝 Noted: “Lead engineer roles”.' in words and EN['cv_details_question'] in words, words
    assert state(customer)[0] == 'ai_input' and state(customer)[1]['brief'] == ['Lead engineer roles']
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
    assert EN['cv_file_name_question'] in words and '<code>Dilnoza Karimova</code>' in words, words
    assert '📎 From: cv.pdf' in words and '📝 Noted: “Make it one page”.' in words and EN['cv_name_again'] in words
    assert shown == [EN['cv_send_another'], EN['cv_write_instead'], EN['ai_back'], EN['home']]
    assert state(customer) == ('cv_source', {'feature_id': CV, 'cv_source': 'file', 'notes': ['Make it one page'],
                                             'source_ids': [str(nameless.id)], 'ask': 'name'})
    assert not GenerationDraft.objects.filter(account=customer).exists()
    words, _ = screen(dispatch_local(customer, text='Javlon Ergashev'))
    assert '📄 Javlon Ergashev' in words and '📎 From: cv.pdf' in words, words
    data = latest(customer, CV)
    assert data['prompt'] == 'Javlon Ergashev\nMake it one page' and data['source_ids'] == [str(nameless.id)]


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


# --- Reading off the shared thread, and reading each file once ----------------------------------------

def reading(pages=(('Timur Rakhimov', 'Lead engineer at Example Motors since 2020; MSc Mechanical Engineering.'),),
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


def test_the_bot_reads_no_file_and_its_wait_for_the_reader_never_holds_up_another_chat(customer, model, monkeypatch,
                                                                                          settings):
    # A CV's files are read by the reader (apps/studio/cv/reads.py), never in the bot: the bot waits for
    # them off its shared thread (sources.read_entries), and says they are still being read if the reader
    # has not come to them yet. As in production: nothing is read as it is queued.
    from apps.studio import extraction
    from apps.studio.cv import reads, sources
    settings.LOCAL_SYNC_JOBS = False
    monkeypatch.setattr('telegram.bot.ALBUM_SETTLE', 0)
    monkeypatch.setattr(sources, 'WAIT_SECONDS', 2.0)
    monkeypatch.setattr(sources, 'POLL_SECONDS', 0.1)
    calls = []
    monkeypatch.setattr(extraction, 'read_cv', reading(calls=calls))
    other = another_customer()
    choose(customer, 'cv_mode_file')
    cv_done, start_done = feed_two(customer, upload('old-cv.pdf', one_column_pdf()), other, '/start', 0.3)
    # The other chat's menu came while the CV waited for the reader (two seconds), not after it.
    assert start_done < 1.5 < 2.0 < cv_done, (start_done, cv_done)
    assert TOOL_NAMES[CV]['en'] in str(LocalBotMessage.objects.filter(account=other, direction='outbound').latest(
        'created_at').buttons), 'the other chat was shown its menu'
    newest = LocalBotMessage.objects.filter(account=customer, direction='outbound').latest('created_at')
    assert calls == [] and ERRORS['en']['cv_reading_now'] in newest.text, (calls, newest.text)
    # The reader reads it once; the CV is made from what it kept.
    assert reads.next_read() and calls == [('MainThread', 'pdf')]
    again = next(button for row in newest.buttons for button in row if button['label'] == EN['cv_try_again'])
    words, _ = screen(dispatch_local(customer, callback_data=again['callback_data']))
    assert '📄 Timur Rakhimov' in words and calls == [('MainThread', 'pdf')], words
    assert latest(customer, CV)['title'] == 'Timur Rakhimov'


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
        assert EN['cv_file_name_question'] in words, words
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
    assert EN['cv_name_question'] in words, words
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
        ('Dilnoza Karimova', 'Senior Data Analyst at Example Retail since 2022; SQL, Power BI.'),)))
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
