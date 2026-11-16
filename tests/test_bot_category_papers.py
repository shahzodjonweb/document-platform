"""The bot's review and file for a category paper (architecture 3.3, 8.1, 8.5; package B4).

A paper's length is its pages, not its sections: its sections are the
template's parts and one facts section, so a one-page ariza has several. The
review of a change to one says the pages it has (its stored length,
categories.skeleton.pages), never "7 → 1" counted from its parts. A deck in a
category keeps one section a slide and is read as today's.

A paper whose length is not a count has no stepper: an ariza is always one
page (`fixed`) and a test as long as its questions need (`derived`), and the
server answers every tap with the same number. A count is offered within the
entry's bounds, and Boshqa's stepper is today's.

A paper whose pages are a ceiling (`length.target: ceiling`, a report, a
letter) is never padded, so it may come out shorter than quoted. Its file then
says so under it, in the category's `shorter` words, else the shared ones,
with the pages quoted and made: a one-page report asked for in four is the
honest result, not a failure.

The paper categories are drafts until stage 2 ships them; these tests mark
them ready, as N2 will, and shape one into a ceiling paper where they need
one. No paper is generated here (the job refuses a paper until its renderer
ships), so a made paper is the draft written as the job would leave it.

The people, organisations and descriptions are invented for these tests.
"""
import asyncio
import copy
import html
import re
import secrets
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest
from django.utils import timezone

from apps.commerce.models import BotDelivery
from apps.core import storage
from apps.core.errors import DomainError
from apps.core.models import Artifact, FileAsset, Job, Quote
from apps.studio import categories
from apps.studio.categories import catalogue
from apps.studio.domain import DOCUMENT, SLIDES, pack, unpack
from apps.studio.models import GenerationDraft
from apps.studio.scripts import CYRILLIC
from telegram import generation as ai
from telegram.delivery import RESULT_COPY, attempt, category_notices, ready_caption, share_link
from telegram.ux_copy import LOCALES, MESSAGES, UX, counted
from tests.test_bot_categories import (APPLICATION, ARIZA, DEFENCE, HIMOYA, QUIZ, TEST, customer, opened,  # noqa: F401
                                       screen, speak, turn)

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.usefixtures('bot_verification_disabled')]

REPORT = 'Choraklik hisobot: “Namuna Savdo” MChJ, III chorak. Savdo 12% ga oshdi, 3 ta yangi do‘kon ochildi. 4 sahifa.'
SHORTER = {
    'uz': 'Siz {asked} sahifa so‘ragan edingiz, yozganlaringiz {pages} sahifaga yetdi: hech narsa o‘ylab topilmadi.',
    'ru': 'Вы просили {asked} стр., написанного хватило на {pages} стр.: ничего не выдумано.',
    'en': 'You asked for {asked} pages; what you wrote fills {pages}: nothing was made up.',
}


def shaped(monkeypatch, change=None):
    """The catalogue with every entry ready, as N1 and N2 mark them, and `change(entries)` applied to its files."""
    entries, templates, index = copy.deepcopy(catalogue.read())
    for raw in entries.values():
        raw['status'] = 'ready'
    if change:
        change(entries)
    made = catalogue.build(entries, templates, index)
    monkeypatch.setattr(catalogue, '_catalogue', lambda: made)
    return made


def as_report(entries, shorter=True):
    """The ariza's file shaped as a report is: up to five pages it may fill, three by default, never padded."""
    raw = entries[ARIZA]
    raw['length'] = {'unit': 'pages', 'mode': 'count', 'target': 'ceiling', 'default': 3, 'min': 1, 'max': 5}
    if shorter:
        raw['bot']['notices']['shorter'] = dict(SHORTER)


@pytest.fixture
def papers(monkeypatch):
    """The switch on with the two paper drafts and a deck ticked."""
    shaped(monkeypatch)
    turn(live=[TEST, ARIZA, HIMOYA])


@pytest.fixture
def reports(monkeypatch):
    """As `papers`, with the ariza's entry a ceiling paper of up to five pages carrying its own `shorter` words."""
    shaped(monkeypatch, as_report)
    turn(live=[TEST, ARIZA, HIMOYA])


def described(account, text, category, service=DOCUMENT):
    """The review of `text`, written in `category`'s question, reached through its group when it sits in one."""
    chat = opened(account, service)
    group = categories.get(category).raw.get('parent')
    if group:
        assert chat.tap('ai_tool', feature_id=service, category=group) == 0
    assert chat.tap('ai_tool', feature_id=service, category=category) == 0
    assert chat.do(text=text) == 1, '"Preparing…" becomes the review'
    return chat


def flat(rows):
    return [action for row in rows for action in row]


def made(draft, questions=0):
    """The draft as the job leaves a generated paper: every part written (what revision_source looks for)."""
    data = unpack(draft.encrypted_data)
    data['content']['sections'] = [{**s, 'body': s['body'] or f'{s["id"]} matni.'} for s in data['content']['sections']]
    data['content']['questions'] = [{'id': f'q{n}', 'stem': f'Savol {n}?', 'options': ['Ha', 'Yo‘q'], 'answer': 'Ha',
                                     'explanation': '', 'topic': 'Fotosintez', 'marks': 1}
                                    for n in range(1, questions + 1)]
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    draft.refresh_from_db()
    return draft


def review_of(account, draft):
    from telegram.bot import review_screen
    _, quote = ai.quote(account, draft.id)
    return asyncio.run(review_screen(account, draft, quote))


# --- The stepper ---------------------------------------------------------------------------------


@pytest.mark.parametrize('locale', LOCALES)
def test_a_paper_whose_length_is_not_a_count_has_no_stepper(customer, papers, locale):
    speak(customer, locale)
    for category, text in ((ARIZA, APPLICATION), (TEST, QUIZ)):
        described(customer, text, category)
        body, actions, _, _ = screen(customer)
        assert 'ai_count' not in flat(actions) and 'ai_length' not in flat(actions), category
        # Its pages are still said, and the language row and the reword button are still there.
        entry = categories.get(category)
        assert f'\n{UX[locale]["ai_pages"]}: ' in body
        assert actions[0] == ['ai_run'] and actions[-1] == ['ai_tool', 'home']
        assert ['ai_locale'] * len(LOCALES) in actions
        assert entry.length['mode'] in ('fixed', 'derived')


def test_a_count_paper_steps_within_its_bounds_and_boshqa_as_today(customer, reports):
    described(customer, REPORT.replace('4 sahifa', '5 sahifa'), ARIZA)
    _, actions, payloads, labels = screen(customer)
    row = next(index for index, row in enumerate(actions) if 'ai_count' in row)
    assert actions[row] == ['ai_length', 'ai_count'], 'five is the most a report is: no ➕'
    assert payloads[row][0]['pages'] == 4 and labels[row][1] == counted('en', 5, 'page')

    # Boshqa's PDF at the same count steps either way, as today.
    chat = opened(customer)
    chat.tap('ai_tool', feature_id=DOCUMENT, category='other')
    chat.do(text='Fotosintez haqida 5 sahifa')
    _, actions, _, _ = screen(customer)
    assert ['ai_length', 'ai_count', 'ai_length'] in actions


def test_the_category_review_says_no_bounds_for_a_paper_that_is_not_counted(customer, papers):
    assert ai.category_review(ai.build(customer, DOCUMENT, APPLICATION, category=ARIZA))['bounds'] is None
    assert ai.category_review(ai.build(customer, DOCUMENT, QUIZ, category=TEST))['bounds'] is None
    himoya = categories.get(HIMOYA).length
    assert ai.category_review(ai.build(customer, SLIDES, DEFENCE, category=HIMOYA))['bounds'] == (himoya['min'], himoya['max'])


# --- The pages before a change -------------------------------------------------------------------


def test_a_change_to_a_paper_reads_its_pages_not_its_parts(customer, papers):
    source = made(ai.build(customer, DOCUMENT, APPLICATION, category=ARIZA))
    parts = len(unpack(source.encrypted_data)['content']['sections'])
    assert parts > 1, 'the ariza has several parts on its one page'
    change = ai.revise(customer, source.id, 'Imlo xatolarini tuzating')
    assert unpack(change.encrypted_data)['options']['category'] == ARIZA
    assert ai.length_before(change) == 1 and ai.summary(change)[0] == 1
    body, _ = review_of(customer, change)
    assert f'\n{UX["en"]["ai_pages"]}: 1\n' in body and '→' not in body, f'no false "{parts} → 1"'


def test_a_change_to_a_test_says_its_pages_before_and_after(customer, papers):
    source = made(ai.build(customer, DOCUMENT, QUIZ, category=TEST), questions=20)
    assert ai.length_before(ai.revise(customer, source.id, 'Imlo xatolarini tuzating')) == 4, 'twenty questions on four pages'
    change = ai.revise(customer, source.id, "Yana 10 ta savol qo'sh")
    body, _ = review_of(customer, change)
    assert f'\n{UX["en"]["ai_pages"]}: 4 → 5\n' in body, 'thirty questions take a page more'


def test_a_change_to_a_category_deck_counts_its_slides_as_today(customer, papers):
    source = made(ai.build(customer, SLIDES, DEFENCE, category=HIMOYA))
    slides = len(unpack(source.encrypted_data)['content']['sections'])
    data = unpack(source.encrypted_data)
    # A slide added in the editor is a slide of the deck, whatever the stored count says.
    data['content']['sections'].append({**data['content']['sections'][-1], 'id': f's{slides + 1}'})
    GenerationDraft.objects.filter(pk=source.pk).update(encrypted_data=pack(data))
    assert ai.length_before(ai.revise(customer, source.id, 'Imlo xatolarini tuzating')) == slides + 1


def test_a_paper_whose_pages_cannot_be_read_says_none_before(customer, papers, monkeypatch):
    source = made(ai.build(customer, DOCUMENT, APPLICATION, category=ARIZA))
    change = ai.revise(customer, source.id, 'Imlo xatolarini tuzating')

    def unknown(data):
        raise DomainError('category_unknown', 500)
    monkeypatch.setattr('apps.studio.categories.skeleton.pages', unknown)
    assert ai.length_before(change) is None, 'nothing is said rather than a count of its parts'


# --- Shorter than quoted -------------------------------------------------------------------------


def generated(account, draft, pages):
    """A paper's job as settle_job leaves it: its quote's parameters and its file of `pages` pages."""
    quote = Quote.objects.create(account=account, feature_id=draft.feature_id, expires_at=timezone.now())
    job = Job.objects.create(account=account, quote=quote, feature_id=draft.feature_id, status='succeeded',
                             origin_channel='bot', idempotency_key=str(quote.id), request_hash='x',
                             parameters={'generation_draft_id': str(draft.id), 'draft_version': draft.version,
                                         'category': unpack(draft.encrypted_data)['options']['category']})
    key = f'tests/papers/{uuid.uuid4()}.pdf'
    storage.write(key, b'%PDF-1.4\n%invented\n', 'application/pdf')
    asset = FileAsset.objects.create(account=account, name='hisobot.pdf', object_key=key, mime_type='application/pdf',
                                     sha256='0' * 64, size_bytes=20, page_count=pages, metadata={'kind': 'pdf'},
                                     expires_at=timezone.now() + timedelta(hours=24))
    artifact = Artifact.objects.create(account=account, job=job, file=asset)
    return job, artifact


def report(account, pages=4):
    draft = ai.build(account, DOCUMENT, REPORT, category=ARIZA)
    assert unpack(draft.encrypted_data)['options']['length'] == pages, 'the four pages the report asks for'
    return draft


@pytest.mark.parametrize('locale', LOCALES)
def test_a_ceiling_paper_that_came_out_shorter_says_so_under_its_file(customer, reports, locale):
    speak(customer, locale)
    job, artifact = generated(customer, report(customer), 1)
    notices = categories.get(ARIZA).raw['bot']['notices']
    shorter = SHORTER[locale].replace('{asked}', '4').replace('{pages}', '1')
    assert category_notices(job, locale) == [notices['finished'][locale], shorter]

    # On the file itself, under the line every file has.
    delivery = BotDelivery.objects.create(account=customer, artifact=artifact, idempotency_key=secrets.token_hex(8))
    bot = Mock(send_document=AsyncMock(return_value=Mock(message_id=411)))
    asyncio.run(attempt(delivery.id, bot))
    caption = bot.send_document.await_args.kwargs['caption']
    line = ready_caption(RESULT_COPY[locale], *share_link(customer, 'fixture_bot'))
    assert caption == f'{line}\n\n{html.escape(notices["finished"][locale])}\n\n{html.escape(shorter)}'


def test_a_ceiling_paper_that_fills_its_pages_says_nothing_more(customer, reports):
    draft = report(customer)
    finished = categories.get(ARIZA).raw['bot']['notices']['finished']['en']
    for pages in (4, 5, 0):  # as quoted, a page over (longer_than_quoted says that), unknown
        job, _ = generated(customer, draft, pages)
        assert category_notices(job, 'en') == [finished], pages


def test_blanks_come_before_shorter(customer, reports):
    job, _ = generated(customer, report(customer), 2)
    Job.objects.filter(pk=job.pk).update(warnings=['facts_blanked'])
    job.refresh_from_db()
    notices = categories.get(ARIZA).raw['bot']['notices']
    assert category_notices(job, 'en')[1:] == [UX['en']['facts_blanked'] if 'blanks' not in notices else notices['blanks']['en'],
                                               SHORTER['en'].replace('{asked}', '4').replace('{pages}', '2')]


@pytest.mark.parametrize('locale', LOCALES)
def test_a_ceiling_paper_without_its_own_words_uses_the_shared_ones(customer, monkeypatch, locale):
    shaped(monkeypatch, lambda entries: as_report(entries, shorter=False))
    turn(live=[ARIZA])
    job, _ = generated(customer, report(customer), 2)
    expected = UX[locale]['paper_shorter'].format(asked=4, pages=2)
    assert category_notices(job, locale)[-1] == expected


def test_a_paper_whose_pages_are_a_count_is_never_called_shorter(customer, papers):
    # A test is as long as its questions, filled to its number: a file with fewer pages is not "shorter than asked".
    draft = ai.build(customer, DOCUMENT, QUIZ, category=TEST)
    assert categories.get(TEST).length['target'] == 'count' and ai.summary(draft)[0] > 1
    job, _ = generated(customer, draft, 1)
    finished = (categories.get(TEST).raw['bot']['notices'].get('finished') or {}).get('en')
    assert category_notices(job, 'en') == ([finished] if finished else [])


def test_a_shorter_notice_that_cannot_be_read_loses_only_itself(customer, reports, monkeypatch):
    job, _ = generated(customer, report(customer), 1)
    monkeypatch.setattr('telegram.delivery._shorter', Mock(side_effect=KeyError('length')))
    assert category_notices(job, 'en') == [categories.get(ARIZA).raw['bot']['notices']['finished']['en']]


def test_a_document_without_a_category_is_never_called_shorter(customer, papers):
    draft = ai.build(customer, DOCUMENT, 'Fotosintez haqida 4 sahifa')
    quote = Quote.objects.create(account=customer, feature_id=DOCUMENT, expires_at=timezone.now())
    job = Job.objects.create(account=customer, quote=quote, feature_id=DOCUMENT, status='succeeded',
                             idempotency_key=str(quote.id), request_hash='x',
                             parameters={'generation_draft_id': str(draft.id)})
    assert category_notices(job, 'en') == []


# --- Copy ----------------------------------------------------------------------------------------


def slots(text):
    return sorted(re.findall(r'\{(\w+)\}', text))


def test_the_shared_shorter_words_say_the_same_in_every_language():
    texts = dict(zip(LOCALES, MESSAGES['paper_shorter']))
    assert {locale: slots(text) for locale, text in texts.items()} == {locale: ['asked', 'pages'] for locale in LOCALES}
    for locale in ('uz', 'en'):
        assert not CYRILLIC.search(texts[locale])
    assert "'" not in texts['uz'], 'Uzbek is written with ‘ and ’, never an ASCII apostrophe'


def test_every_categorys_shorter_words_are_for_a_ceiling_paper_and_name_only_the_two_numbers():
    """The contract the paper entries are written to: the bot fills {asked} and {pages} and nothing else."""
    for entry in catalogue._catalogue().entries.values():
        shorter = (entry.raw['bot'].get('notices') or {}).get('shorter')
        if not shorter:
            continue
        assert entry.service == 'pdf' and entry.length['target'] == 'ceiling', f'{entry.id}: shown only on a ceiling paper'
        found = {locale: slots(text) for locale, text in shorter.items()}
        assert len({tuple(value) for value in found.values()}) == 1, entry.id
        assert set(next(iter(found.values()))) <= {'asked', 'pages'}, entry.id
