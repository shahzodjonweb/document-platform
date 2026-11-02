"""A generated deck sent again from its draft: the same slides, no call to anything, and no word lost unseen.

LibreOffice is stood in for by a small script where a test only needs its PDF
(`office`), through the real child process and engine; the one real conversion
is marked REQUIRES_OFFICE. Conftest fails any test that reaches Pixabay.
"""
import copy
import hashlib
import itertools
import json
import logging
import re
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from pypdf import PdfReader, PdfWriter

from apps.commerce.models import BotDelivery
from apps.core import allowance, services, storage
from apps.core.errors import DomainError, error_data
from apps.core.models import AnalyticsEvent, BotCallback, BotDraft, FileAsset, Job, OutboxEvent, Quote
from apps.core.policy import catalog
from apps.core.serializers import job_data, quote_data
from apps.core.services import cancel_job, cleanup_expired, execute_job, submit_job
from apps.studio import batches, execution, photos as stock, quality, render_export, slide_fit, title_lines, variants
from apps.studio.deck_designs import DESIGNS
from apps.studio.domain import CV, DOCUMENT, EXPORT, RENDER_IDS, SLIDES, create_draft, draft_jobs, generation_quote, pack, require, unpack, update_draft
from apps.studio.models import GenerationDraft, ProviderUsage
from apps.studio.render_export import export_quote, fit_section, quote_summary
from apps.studio.scripts import WORD, artifact_text, artifact_violations
from apps.studio.slide_fit import left_out, measure_deck
from apps.studio.slides import render_pptx
from apps.studio.variants import fixtures
from processors import ProcessorError
from processors import engine, sandbox
from processors.engine import office_runtime
from telegram import generation as ai
from telegram.delivery import enqueue, result_controls, revisable_draft
from telegram.ux_copy import TOOL_NAMES, UX
from tests.test_bot_edit_review import change, made, screen
from tests.test_bot_generation import customer as chatting  # noqa: F401
from tests.test_deck_pins import (CARDS, COVER, DESIGN, LIST, PHOTO, TITLE, clock, customer, deck_draft, deck_sections, delivered, edit_section,  # noqa: F401
                                  generate, kept_pictures, media, picture, pins_of, run, slide_xml, stock_photos)
from tests.test_object_storage import bucket  # noqa: F401
from tests.test_photos import _run as run_paid_deck, hit, model, paid_deck, pixabay  # noqa: F401
from tests.test_platform import account, login_client, upload
from tests.test_studio import paid
from tests.test_studio_branding import logo

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def deck_editor_on(monkeypatch):
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')

REQUIRES_OFFICE = pytest.mark.skipif(not office_runtime()['available'], reason='No working configured LibreOffice runtime')
PPTX_MIME = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
# Words that are in the deck and nowhere else, to look for where they must not be.
PRIVATE = 'Zanzibarmarker'
# Brutalist sets a cover's title in capitals: the words as drawn are no longer the words as typed.
CAPITALS = next(key for key, design in DESIGNS.items() if design.get('composition') == 'brutalist')
ONE_OF_EACH_COMPOSITION = sorted({design.get('composition'): key for key, design in DESIGNS.items()}.values())


def quoted(customer, draft, fmt='pptx', deliver='download'):  # noqa: F811
    draft.refresh_from_db()
    return export_quote(customer, draft.id, draft.version, fmt, deliver)


def send(customer, draft, fmt='pptx', origin='web'):  # noqa: F811
    """A send as the Review sheet makes one: quoted, confirmed and drawn."""
    quote = quoted(customer, draft, fmt)
    job, created = submit_job(customer, quote.id, f'send-{quote.id}', origin=origin)
    assert created
    return execute_job(job.id)


def resend(customer, draft, origin='web'):  # noqa: F811
    """The same draft sent again: nothing has changed, so the send is answered with the job that made its file."""
    quote = quoted(customer, draft)
    job, created = submit_job(customer, quote.id, f'send-{quote.id}', origin=origin)
    assert not created
    return job


def drawn_again(customer, draft):  # noqa: F811
    """A new drawing of the same draft, as when the earlier file has gone: what comes out is what a send would make."""
    Job.objects.filter(account=customer, feature_id=EXPORT, status='succeeded').update(status='failed')
    return send(customer, draft)


def ticking(monkeypatch):
    """The measure's clock, a second on each time it is read: it stops at the same slide on any machine."""
    ticks = itertools.count()
    monkeypatch.setattr(slide_fit, 'time', SimpleNamespace(monotonic=lambda: next(ticks)))


def files(job):
    return list(job.artifacts.select_related('file').order_by('file__name'))


def pinned_assets(draft):
    return {section_id: photo['asset_id'] for section_id, photo in pins_of(draft)['photos'].items() if photo['asset_id']}


def api_post(customer, path, **body):  # noqa: F811
    return login_client(customer).post(f'/api/v1/generation/drafts/{path}', json.dumps(body), content_type='application/json')


@pytest.fixture
def office(tmp_path, monkeypatch):
    """A stand-in LibreOffice for the real child process and engine: it answers --version and leaves a PDF of three pages."""
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=960, height=540)
    made = tmp_path / 'made.pdf'
    writer.write(made)
    binary = tmp_path / 'soffice'
    binary.write_text(f'''#!/bin/sh
if [ "$1" = "--version" ]; then echo "LibreOffice 24.2.0"; exit 0; fi
while [ $# -gt 1 ]; do
  if [ "$1" = "--outdir" ]; then folder="$2"; fi
  shift
done
echo "${{FONTCONFIG_FILE:-none}}" >> "{tmp_path}/fontconfig.log"
cp "{made}" "$folder/input.pdf"
''')
    binary.chmod(0o755)
    monkeypatch.setenv('PDFMASTER_SOFFICE_BIN', str(binary))
    office_runtime.cache_clear()
    yield
    monkeypatch.delenv('PDFMASTER_SOFFICE_BIN')
    office_runtime.cache_clear()


# ---------------------------------------------------------------- what comes out


def test_a_sent_deck_is_the_delivered_deck_but_for_the_slide_that_was_edited(customer, stock_photos):  # noqa: F811
    draft, first = generate(customer)
    edited = edit_section(customer, draft, CARDS, heading='Reworded by hand')
    held = bytes(edited.encrypted_data)

    job = send(customer, edited)
    assert job.status == 'succeeded', job.error_code
    assert job.feature_id == EXPORT and job.warnings == [] and job.engine == 'deck-render'
    artifact = job.artifacts.get().file
    assert artifact.mime_type == PPTX_MIME and artifact.page_count == 10

    before, after = slide_xml(delivered(first)), slide_xml(delivered(job))
    assert {number for number in before if before[number] != after[number]} == {2}, 'only the second slide'
    assert media(delivered(job)) == media(delivered(first)), 'every picture, to the byte'
    assert 'Reworded by hand' in artifact_text(delivered(job))

    # The draft is the draft: not a byte of it moved, its version included.
    edited.refresh_from_db()
    assert bytes(edited.encrypted_data) == held and edited.version == GenerationDraft.objects.get(pk=draft.pk).version


def test_over_the_api_a_send_is_quoted_confirmed_and_downloaded_and_a_retry_is_the_same_send(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    client = login_client(customer)
    quote = api_post(customer, f'{draft.id}/export-quote', version=draft.version, format='pptx', deliver='download').json()
    answer = client.post('/api/v1/jobs', json.dumps({'quote_id': quote['id']}), content_type='application/json', headers={'Idempotency-Key': 'send-over-the-api'})
    assert answer.status_code == 201, answer.content
    job = answer.json()
    assert job['status'] == 'succeeded' and job['feature_id'] == EXPORT and job['input_files'] == [] and len(job['artifacts']) == 1
    assert job['artifacts'][0]['name'].endswith('.pptx') and client.get(job['artifacts'][0]['download_url']).status_code == 200
    again = client.post('/api/v1/jobs', json.dumps({'quote_id': quote['id']}), content_type='application/json', headers={'Idempotency-Key': 'send-over-the-api'})
    assert again.status_code == 200 and again.json()['id'] == job['id'] and allowance.file_jobs_this_week(customer) == 1


@pytest.mark.parametrize('kept', [{}, {'design': None}, {'sections': deck_sections()[:1], 'asked': []}], ids=['designed', 'no_design', 'one_slide'])
def test_a_deck_with_no_edit_comes_out_as_it_was_delivered(customer, stock_photos, kept):  # noqa: F811
    draft, first = generate(customer, **copy.deepcopy(kept))
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert slide_xml(delivered(job)) == slide_xml(delivered(first)) and media(delivered(job)) == media(delivered(first))


def test_a_slide_added_since_is_drawn_and_comes_out_the_same_again(customer, stock_photos):  # noqa: F811
    draft, first = generate(customer)
    content = copy.deepcopy(unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)['content'])
    content['sections'].append({**fixtures.light('cards', 3), 'id': 'added-later'})
    draft.refresh_from_db()
    added = update_draft(customer, draft.id, {'version': draft.version, 'content': content})
    held = bytes(added.encrypted_data)
    one = send(customer, added)
    assert one.status == 'succeeded', one.error_code
    two = drawn_again(customer, added)
    assert slide_xml(delivered(one)) == slide_xml(delivered(two))
    assert 'added-later' not in pins_of(added)['variants'] and bytes(GenerationDraft.objects.get(pk=draft.pk).encrypted_data) == held, 'no pin it did not need'
    # Every other slide holds to its variant; each says one more in its '03 / 11', and nothing else moved.
    metadata = one.artifacts.get().file.metadata
    assert metadata['repinned'] == [] and metadata['variants'][8].startswith('cards.')
    assert metadata['variants'][:8] == first.artifacts.get().file.metadata['variants'][:8]


def test_a_send_cancelled_while_it_waits_leaves_everything_as_it_was(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    pictures = {picture_.pk: picture_.expires_at for picture_ in kept_pictures(customer)}
    job, _ = submit_job(customer, quoted(customer, draft).id, 'a-send-called-off')
    assert cancel_job(customer, job.id).status == 'canceled' and allowance.file_jobs_this_week(customer) == 0
    assert {picture_.pk: picture_.expires_at for picture_ in kept_pictures(customer)} == pictures


def test_a_send_calls_nothing_and_counts_one_file_task(paid_deck, model, pixabay, monkeypatch):  # noqa: F811
    pixabay.hits = [hit(n, tags='modern, office, team, meeting') for n in range(1, 7)]
    model.picks = [{'slide': 's2', 'photo': 2}, {'slide': 's3', 'photo': 3}]
    _, made = run_paid_deck(paid_deck)
    assert made.status == 'succeeded', made.error_code
    draft = GenerationDraft.objects.get(pk=made.parameters['generation_draft_id'])
    documents, edits, usage = allowance.ai_documents_this_week(paid_deck), allowance.edits_of(paid_deck, str(draft.id)), ProviderUsage.objects.count()
    calls, asked = len(pixabay.calls), len(model.requests)

    entered = []

    def never(name):
        def refuse(*args, **kwargs):
            entered.append(name)
            raise AssertionError(name)
        return refuse
    from apps.studio import filling, provider
    for owner, name in ((provider, 'generate'), (provider, 'largest_body'), (quality, 'finish'), (quality, 'normalise'), (title_lines, 'apply'),
                        (stock, 'fetch_for_deck'), (execution, '_photos'), (execution, '_deck_pins'), (filling, 'top_up')):
        monkeypatch.setattr(owner, name, never(name))
    job = send(paid_deck, draft)
    assert job.status == 'succeeded', job.error_code
    assert entered == [] and (len(pixabay.calls), len(model.requests)) == (calls, asked)
    assert slide_xml(delivered(job)) == slide_xml(delivered(made))
    assert ProviderUsage.objects.count() == usage
    assert allowance.ai_documents_this_week(paid_deck) == documents and allowance.edits_of(paid_deck, str(draft.id)) == edits
    assert allowance.file_jobs_this_week(paid_deck) == 1


def test_as_pdf_alone_only_the_pdf_is_left(customer, stock_photos, office):  # noqa: F811
    draft, _ = generate(customer)
    job = send(customer, draft, 'pdf')
    assert job.status == 'succeeded', job.error_code
    artifact = job.artifacts.get().file
    assert artifact.mime_type == 'application/pdf' and artifact.page_count == 3 and artifact.metadata['kind'] == 'pdf'
    assert artifact.name.startswith('Harbour-logistics-review-') and artifact.name.endswith('.pdf')
    assert len(PdfReader(delivered(job)).pages) == 3
    folder = services.storage_path(f'outputs/{customer.id}/{job.id}')
    assert not (folder / 'document.pptx').exists(), 'no second file behind the one that was asked for'


def test_a_sent_deck_is_drawn_in_the_faces_it_was_measured_in(customer, stock_photos, office, tmp_path):  # noqa: F811
    draft, _ = generate(customer)
    assert send(customer, draft, 'pdf').status == 'succeeded'
    assert (tmp_path / 'fontconfig.log').read_text().strip().endswith('/deck-fonts.conf')


def test_as_both_it_is_two_files_of_one_job_and_one_task(customer, stock_photos, office):  # noqa: F811
    draft, first = generate(customer)
    job = send(customer, draft, 'both')
    assert job.status == 'succeeded', job.error_code
    pdf, pptx = (artifact.file for artifact in files(job))
    assert pdf.mime_type == 'application/pdf' and pptx.mime_type == PPTX_MIME
    assert slide_xml(storage.local(pptx.object_key)) == slide_xml(delivered(first))
    assert Job.objects.filter(account=customer, feature_id=EXPORT).count() == 1 and allowance.file_jobs_this_week(customer) == 1
    # One name twice: the deck's title and the job's code, told apart by the extension.
    assert pptx.name.rsplit('.', 1)[0] == pdf.name.rsplit('.', 1)[0]
    assert re.fullmatch(r'Harbour-logistics-review-[0-9a-f]{6}\.pptx', pptx.name)


def test_a_conversion_that_fails_delivers_nothing_and_counts_nothing(customer, stock_photos, office, tmp_path):  # noqa: F811
    draft, _ = generate(customer)
    quote = quoted(customer, draft, 'both')
    (tmp_path / 'soffice').write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "LibreOffice 24.2.0"; exit 0; fi\nexit 3\n')
    job, _ = submit_job(customer, quote.id, 'a-send-that-fails')
    job = execute_job(job.id)
    assert (job.status, job.error_code) == ('failed', 'conversion_failed')
    assert not job.artifacts.exists() and allowance.file_jobs_this_week(customer) == 0
    assert not services.storage_path(f'outputs/{customer.id}/{job.id}').exists()


@REQUIRES_OFFICE
def test_a_real_conversion_gives_one_page_a_slide(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    job = send(customer, draft, 'both')
    assert job.status == 'succeeded', job.error_code
    pdf, pptx = (artifact.file for artifact in files(job))
    assert pdf.page_count == pptx.page_count == 10


def test_the_office_timeout_is_a_parameter_and_stays_a_minute_by_default(tmp_path, monkeypatch):
    seen = []

    def run_office(*args, **kwargs):
        seen.append(kwargs['timeout'])
        raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])
    monkeypatch.setattr(engine, 'office_runtime', lambda: {'available': True, 'executable': '/bin/true', 'version': 'LibreOffice 24'})
    monkeypatch.setattr(engine.subprocess, 'run', run_office)
    source = tmp_path / 'deck.pptx'
    source.write_bytes(b'pptx')
    for arguments, seconds in (({}, 60), ({'timeout': 123}, 123)):
        with pytest.raises(ProcessorError) as stopped:
            engine._office_pdf(source, 'convert.pptx_to_pdf', tmp_path, {'kind': 'pptx'}, **arguments)
        assert stopped.value.code == 'processor_timeout' and seen.pop() == seconds

    requests = []
    monkeypatch.setattr(sandbox, '_run', lambda request, timeout: requests.append((request, timeout)))
    sandbox.execute_sandbox('convert.pptx_to_pdf', [source], {}, tmp_path)
    sandbox.execute_sandbox('convert.pptx_to_pdf', [source], {}, tmp_path, timeout=210, office_timeout=180)
    assert [(request['office_timeout'], timeout) for request, timeout in requests] == [(60, 90), (180, 210)]
    assert [request['deck_fonts'] for request, _ in requests] == [False, False], 'a conversion is a customer\'s unless it says otherwise'


def test_the_customer_sees_the_decks_title_or_the_service_as_the_file_name(customer):  # noqa: F811
    sections = [{**section, 'image_query': ''} for section in deck_sections()]
    draft, _ = generate(customer, sections=sections, asked=[], title='Порт Ташкент: обзор')
    assert re.fullmatch(r'Порт-Ташкент-обзор-[0-9a-f]{6}\.pptx', send(customer, draft).artifacts.get().file.name)
    draft, _ = generate(customer, sections=sections, asked=[], title='Untitled document')
    assert re.fullmatch(r'slides-[0-9a-f]{6}\.pptx', send(customer, draft).artifacts.get().file.name)


# ---------------------------------------------------------------- the customer's own letters


def uzbek_deck(customer, heading, design='midnight'):  # noqa: F811
    sections = [{**section, 'image_query': ''} for section in deck_sections()]
    sections[0]['heading'] = heading
    sections[4] = {**sections[4], 'heading': 'Havo', 'body': 'Хаво ифлосланиши\nToza havo'}
    made = create_draft(customer, {'feature_id': SLIDES, 'title': 'Havo', 'source_text': 'Havo haqida.', 'output_locale': 'uz',
                                   'options': {'pages': len(sections), 'locale_chosen': True, 'deck_design': design, 'branding': {'name': 'Мактаб', 'accent': '#285cff'}}})
    made = update_draft(customer, made.id, {'version': made.version, 'content': {'title': 'Havo', 'sections': sections, 'questions': [], 'citations': []}})
    assert unpack(made.encrypted_data)['output_locale'] == 'uz'
    job = run(customer, made)
    assert job.status == 'succeeded', job.error_code
    made.refresh_from_db()
    return made


@pytest.mark.parametrize('design', ['midnight', CAPITALS])
def test_a_customers_own_cyrillic_in_an_uzbek_deck_passes_the_alphabet_check(customer, design):  # noqa: F811
    draft = uzbek_deck(customer, 'Ҳаво ва сув', design)
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert artifact_violations(delivered(job), 'uz'), 'there is Cyrillic in the file for the check to allow'
    words = artifact_text(delivered(job))
    assert 'Хаво' in words and 'Мактаб' in words and ('Ҳаво' in words or 'ҲАВО' in words)


@pytest.mark.parametrize('kind,variant,labels,marks', [
    ('cards', 'cards.ring_tabs', ['Продажи', 'Бюджет', 'Рынок'], ['П', 'Б', 'Р']),
    ('matrix', 'matrix.letter_tiles', ['Сильные', 'Вызовы', 'Оценка', 'Тренды'], ['С', 'В', 'О', 'Т']),
    ('matrix', 'matrix.chevron_cross', ['Сильные', 'Вызовы', 'Оценка', 'Тренды'], ['С', 'В', 'О', 'Т']),
    ('quote', 'quote.initials', ['Иван Петров'], ['ИП']),
    ('quote', 'quote.initials', ['Иван\nПетров'], ['ИП']),
], ids=['card_ring', 'matrix_tiles', 'matrix_chevrons', 'quote_speaker', 'quote_speaker_on_two_lines'])
def test_the_initials_a_variant_makes_of_a_customers_own_cyrillic_pass_too(customer, kind, variant, labels, marks):  # noqa: F811
    draft = uzbek_deck(customer, 'Havo')
    made = {key: value for key, value in fixtures.light(kind, len(labels)).items() if key != 'id'}
    edit_section(customer, draft, CARDS, **{**made, 'items': [{**item, 'label': label} for item, label in zip(made['items'], labels)]})
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    data['_render']['variants'][CARDS] = variant
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert set(marks) <= set(WORD.findall(artifact_text(delivered(job)))), 'the variant drew the initials this is about'


def test_the_letters_allowed_are_the_customers_initials_and_no_others():
    allowed = set(WORD.findall(render_export.own_words(['— Иван Петров Сидоров', 'Рынок\nцены (рост)', 'Latin'])))
    assert {'И', 'П', 'С', 'ИП', 'ПС', 'Р', 'Ц', 'РЦ', 'ЦР', 'РОСТ'} <= allowed
    assert not {'ИС', 'Х'} & allowed


def test_cyrillic_that_is_not_the_customers_is_still_refused(customer, monkeypatch):  # noqa: F811
    draft = uzbek_deck(customer, 'Havo va suv')
    monkeypatch.setattr('apps.studio.scripts.fields', lambda content: [])
    job = send(customer, draft)
    assert (job.status, job.error_code) == ('failed', 'script_policy')
    assert allowance.file_jobs_this_week(customer) == 0


# ---------------------------------------------------------------- a send waiting for its turn


def test_a_queued_send_never_blocks_autosave_and_an_edit_fails_it_with_nothing_counted(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    quote = quoted(customer, draft)
    job, _ = submit_job(customer, quote.id, 'a-send-that-waits')
    assert job.status == 'queued' and allowance.file_jobs_this_week(customer) == 1
    assert not draft_jobs(customer, draft.id, ('queued',))

    draft.refresh_from_db()
    saved_now = update_draft(customer, draft.id, {'version': draft.version, 'title': 'Saved while it waits'})
    assert saved_now.version == draft.version + 1
    done = execute_job(job.id)
    assert (done.status, done.error_code) == ('failed', 'version_conflict')
    assert not done.artifacts.exists() and allowance.file_jobs_this_week(customer) == 0
    # The customer is told to send again, and can.
    assert job_data(done)['error']['code'] == 'version_conflict'
    assert send(customer, saved_now).status == 'succeeded'


def test_a_draft_that_changed_but_kept_its_version_fails_the_send_as_well(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    job, _ = submit_job(customer, quoted(customer, draft).id, 'a-send-behind-a-change')
    data = unpack(draft.encrypted_data)
    data['content']['sections'][1]['heading'] = 'Changed, the version not'
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    done = execute_job(job.id)
    assert (done.status, done.error_code) == ('failed', 'version_conflict')


def test_a_quote_on_an_old_version_cannot_be_submitted(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    quote = quoted(customer, draft)
    edit_section(customer, draft, CARDS, heading='Edited after the quote')
    with pytest.raises(DomainError, match='version_conflict'):
        submit_job(customer, quote.id, 'a-send-too-late')
    assert not Job.objects.filter(quote=quote).exists()


def test_a_generation_waiting_refuses_a_quote_and_a_send_waiting_does_not_hold_it_up(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    waiting, _ = submit_job(customer, generation_quote(customer, draft.id, GenerationDraft.objects.get(pk=draft.pk).version).id, 'generating-again')
    with pytest.raises(DomainError, match='generation_running'):
        quoted(customer, draft)
    Job.objects.filter(pk=waiting.pk).update(status='canceled')
    quote = quoted(customer, draft)
    submit_job(customer, quote.id, 'a-send-waiting')
    assert quote.feature_id == EXPORT and not draft_jobs(customer, draft.id, ('queued',))


def test_a_quote_with_another_version_is_refused(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    with pytest.raises(DomainError, match='version_conflict'):
        export_quote(customer, draft.id, GenerationDraft.objects.get(pk=draft.pk).version + 1, 'pptx', 'chat')


@pytest.mark.parametrize('fmt,deliver', [('docx', 'chat'), ('pptx', 'fax'), (None, 'chat'), ('pptx', None)])
def test_a_format_or_way_of_delivery_it_does_not_have_is_refused(customer, stock_photos, fmt, deliver):  # noqa: F811
    draft, _ = generate(customer)
    with pytest.raises(DomainError, match='invalid_parameters'):
        export_quote(customer, draft.id, GenerationDraft.objects.get(pk=draft.pk).version, fmt, deliver)


def test_a_pdf_is_refused_at_the_quote_where_there_is_no_office(customer, stock_photos, monkeypatch):  # noqa: F811
    draft, _ = generate(customer)
    monkeypatch.setattr(engine, 'office_runtime', lambda: {'available': False, 'reason': 'engine_unavailable'})
    for fmt in ('pdf', 'both'):
        with pytest.raises(DomainError, match='engine_unavailable'):
            quoted(customer, draft, fmt)
    assert quoted(customer, draft, 'pptx').parameters['format'] == 'pptx'


# ---------------------------------------------------------------- the quote


def test_with_the_deck_editor_off_a_deck_cannot_be_sent_again_or_measured(customer, stock_photos, monkeypatch):
    draft, _ = generate(customer)
    monkeypatch.delenv('EDITOR_FLAG_DECK_EDITOR')
    for path, body in ((f'{draft.id}/export-quote', {'version': draft.version, 'format': 'pptx', 'deliver': 'download'}),
                       (f'{draft.id}/fit', {'section': {'id': CARDS, 'heading': 'H', 'body': 'B'}})):
        answer = api_post(customer, path, **body)
        assert answer.status_code == 409 and answer.json()['error']['code'] == 'feature_unavailable'


def test_a_quote_points_at_the_draft_and_lists_only_the_chosen_pictures(customer, stock_photos, office):  # noqa: F811
    draft, _ = generate(customer)
    quote = quoted(customer, draft, 'both', 'chat')
    assert quote.feature_id == EXPORT
    assert quote.parameters == {'generation_draft_id': str(draft.id), 'version': draft.version, 'format': 'both', 'deliver': 'chat',
                                'snapshot': hashlib.sha256(bytes(draft.encrypted_data)).hexdigest()}
    assert quote.policy['tariff_version'] == 'deck-render-v1' and quote.policy['lease_seconds'] == 300 and quote.policy['plan'] == customer.plan
    assert timedelta(minutes=9) < quote.expires_at - timezone.now() <= timedelta(minutes=10)
    chosen = pinned_assets(draft)
    assert set(chosen) == {COVER, PHOTO} and sorted(quote.input_ids) == sorted(chosen.values())
    assert kept_pictures(customer, candidate=True).count() == 4, 'candidates exist, and are not listed'
    assert quote.input_fingerprints == [{'id': asset_id, 'sha256': FileAsset.objects.get(pk=asset_id).sha256} for asset_id in quote.input_ids]
    assert allowance.quote_kind(quote) == 'file' and 'revision' not in quote.parameters


def test_a_quote_reads_no_file_and_runs_nothing(customer, monkeypatch):  # noqa: F811
    mark = logo(customer)
    draft = branded_deck(customer, mark)

    def refuse(*args, **kwargs):
        raise AssertionError('the API process parses no customer bytes and renders nothing')
    for name in ('local', 'read_bytes'):
        monkeypatch.setattr(storage, name, refuse)
    monkeypatch.setattr('subprocess.run', refuse)
    monkeypatch.setattr('subprocess.Popen', refuse)
    monkeypatch.setattr('apps.studio.branding.render_style', refuse)
    assert api_post(customer, f'{draft.id}/export-quote', version=draft.version, format='pptx', deliver='download').status_code == 201
    assert api_post(customer, f'{draft.id}/fit', section={'id': CARDS, 'heading': 'H', 'body': 'B'}).status_code == 200


def test_more_pictures_than_a_plan_now_lists_are_still_all_drawn(customer, stock_photos, monkeypatch):  # noqa: F811
    draft, first = generate(customer)
    chosen = pinned_assets(draft)
    limits = dict(render_export.plan_limits(customer), max_deck_images=1)
    monkeypatch.setattr(render_export, 'plan_limits', lambda account: limits)
    quote = quoted(customer, draft)
    assert len(quote.input_ids) == 1 and quote.input_ids[0] in chosen.values()
    job, _ = submit_job(customer, quote.id, 'a-send-of-a-bigger-deck')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    assert media(delivered(job)) == media(delivered(first))


def test_the_quote_says_what_review_shows(customer, stock_photos, office):  # noqa: F811
    draft, _ = generate(customer)
    answer = api_post(customer, f'{draft.id}/export-quote', version=draft.version, format='both', deliver='chat')
    assert answer.status_code == 201, answer.content
    data = answer.json()
    assert data['feature_id'] == EXPORT and data['tariff_version_id'] == 'deck-render-v1' and data['affordable'] is True
    summary = data['summary']
    assert summary['slides'] == 10 and summary['format'] == 'both' and summary['warnings'] == []
    assert summary['cost'] == {'kind': 'included', 'left': None, 'limit': None}
    pictures = sum(asset.size_bytes for asset in FileAsset.objects.filter(pk__in=pinned_assets(draft).values()))
    assert summary['size_estimate'] > 2 * pictures
    assert timezone.now() + timedelta(hours=23) < datetime.fromisoformat(summary['kept_until'].replace('Z', '+00:00')) <= timezone.now() + timedelta(hours=24)


def test_on_a_plan_with_a_weekly_limit_the_quote_says_what_is_left_and_refuses_past_it(settings, stock_photos, monkeypatch):  # noqa: F811
    settings.DEBUG = True
    free = account()
    draft, _ = generate(free)
    summary = quote_summary(free, quoted(free, draft))
    assert summary['cost'] == {'kind': 'file_task', 'left': 15, 'limit': 15}
    monkeypatch.setattr(allowance, '_limit', lambda account, key: 1 if key == 'weekly_file_jobs' else None)
    assert send(free, draft).status == 'succeeded'
    assert quote_summary(free, quoted(free, draft))['cost']['kind'] == 'none', 'the same deck again makes nothing new'
    edit_section(free, draft, CARDS, heading='Edited since')
    with pytest.raises(DomainError) as refused:
        quoted(free, draft)
    assert refused.value.code == 'weekly_file_limit' and refused.value.status == 429


def test_the_channels_rule_is_asked_like_any_other_task(customer, stock_photos, monkeypatch):  # noqa: F811
    draft, _ = generate(customer)

    def require_channels(account):
        raise DomainError('channels_required', 403)
    monkeypatch.setattr('apps.core.channel_gate.require', require_channels)
    with pytest.raises(DomainError, match='channels_required'):
        quoted(customer, draft)


def test_only_the_quote_of_a_send_can_make_this_job(customer, stock_photos):  # noqa: F811
    """Not a draft of its own, not the generic quote, not the catalog: nothing but export_quote starts one."""
    assert EXPORT in RENDER_IDS
    with pytest.raises(DomainError, match='feature_unavailable'):
        create_draft(customer, {'feature_id': EXPORT, 'title': 'Not a service', 'source_text': 'Words.'})
    client = login_client(customer)
    answer = client.post('/api/v1/generation/drafts', json.dumps({'feature_id': EXPORT, 'title': 'Not a service', 'source_text': 'Words.'}), content_type='application/json')
    assert answer.status_code == 409 and answer.json()['error']['code'] == 'feature_unavailable'
    source = upload(customer)
    answer = client.post('/api/v1/quotes', json.dumps({'feature_id': EXPORT, 'input_ids': [str(source.id)], 'parameters': {}}), content_type='application/json')
    assert answer.status_code == 409 and answer.json()['error']['code'] == 'feature_unavailable'
    assert EXPORT not in {feature['id'] for feature in catalog(customer)} and EXPORT not in engine.capabilities()
    assert not any(EXPORT in children for children in batches.CHILDREN.values())
    assert EXPORT not in json.dumps(client.get('/api/v1/plans').json()['plans'][0]['features'])
    assert EXPORT not in json.dumps(client.get('/api/v1/studio/config').json()['features'])


def test_a_plan_without_it_is_refused(customer, stock_photos, hold_back):  # noqa: F811
    draft, _ = generate(customer)
    hold_back(EXPORT, customer.plan)
    with pytest.raises(DomainError, match='feature_not_in_plan'):
        quoted(customer, draft)
    require(account(99), SLIDES)


# ---------------------------------------------------------------- what cannot be sent


def test_only_a_deck_that_was_drawn_can_be_sent(customer, stock_photos):  # noqa: F811
    sections = [{**section, 'image_query': ''} for section in deck_sections()]
    never_made = deck_draft(customer, sections=sections)
    document = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'A paper', 'source_text': 'Words of a paper.'})
    assert run(customer, document).status == 'succeeded'
    profile = create_draft(customer, {'feature_id': CV, 'prompt': 'Jasur Toshmatov, developer. jasur@example.com. Samarkand University, 2021.'})
    assert run(customer, profile).status == 'succeeded'
    made, _ = generate(customer, sections=sections)
    change = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(made.id)}})
    for draft in (never_made, document, profile, change):
        draft.refresh_from_db()
        with pytest.raises(DomainError) as refused:
            export_quote(customer, draft.id, draft.version, 'pptx', 'chat')
        assert refused.value.code == 'deck_not_editable' and refused.value.status == 409
        with pytest.raises(DomainError, match='deck_not_editable'):
            fit_section(customer, draft.id, {'id': 's1', 'heading': 'H', 'body': 'B'})


def test_a_change_drawn_can_be_sent_and_one_rebuilt_cannot(customer, stock_photos):  # noqa: F811
    made, _ = generate(customer)
    change = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(made.id)}})
    assert run(customer, change).status == 'succeeded'
    job = send(customer, change)
    assert job.status == 'succeeded', job.error_code
    assert not Job.objects.get(pk=job.pk).parameters.get('revision') and allowance.quote_kind(job) == 'file'
    assert allowance.edits_of(customer, str(made.id)) == 1, 'the one the model made, not this'

    made.refresh_from_db()
    rebuilt = update_draft(customer, made.id, {'version': made.version, 'prompt': 'Another deck altogether, about rivers.'})
    with pytest.raises(DomainError, match='deck_not_editable'):
        export_quote(customer, rebuilt.id, rebuilt.version, 'pptx', 'chat')


def test_another_account_cannot_quote_measure_or_submit(customer, stock_photos, settings):  # noqa: F811
    draft, _ = generate(customer)
    other = paid(settings, account(77))
    with pytest.raises(DomainError, match='not_found'):
        export_quote(other, draft.id, draft.version, 'pptx', 'chat')
    assert api_post(other, f'{draft.id}/export-quote', version=draft.version, format='pptx', deliver='chat').status_code == 404
    assert api_post(other, f'{draft.id}/fit', section={'id': CARDS, 'heading': 'H', 'body': 'B'}).status_code == 404
    with pytest.raises(DomainError, match='not_found'):
        submit_job(other, quoted(customer, draft).id, 'someone-elses-quote')


@pytest.mark.parametrize('gone', ['expired', 'deleted', 'missing', 'file'])
def test_a_chosen_picture_that_has_gone_is_refused_at_the_quote_and_named(customer, stock_photos, gone):  # noqa: F811
    draft, _ = generate(customer)
    asset = FileAsset.objects.get(pk=pinned_assets(draft)[PHOTO])
    if gone == 'expired':
        FileAsset.objects.filter(pk=asset.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    elif gone == 'deleted':
        FileAsset.objects.filter(pk=asset.pk).update(state='deleted')
    elif gone == 'missing':
        asset.delete()
    else:
        storage.delete(asset.object_key)
    with pytest.raises(DomainError) as refused:
        quoted(customer, draft)
    assert refused.value.code == 'pinned_asset_expired' and refused.value.status == 409
    assert refused.value.params == {'sections': [{'id': PHOTO, 'index': 5}]}
    answer = api_post(customer, f'{draft.id}/export-quote', version=draft.version, format='pptx', deliver='chat')
    assert answer.status_code == 409 and answer.json()['error']['code'] == 'pinned_asset_expired'


def test_a_picture_that_goes_after_the_quote_fails_at_submit_or_run_with_nothing_counted(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    asset = FileAsset.objects.filter(pk=pinned_assets(draft)[PHOTO])
    quote = quoted(customer, draft)
    asset.update(state='deleted')
    with pytest.raises(DomainError, match='pinned_asset_expired'):
        submit_job(customer, quote.id, 'a-picture-gone-at-submit')
    asset.update(state='ready')

    job, _ = submit_job(customer, quote.id, 'a-picture-gone-at-run')
    asset.update(state='deleted')
    job = execute_job(job.id)
    assert (job.status, job.error_code) == ('failed', 'pinned_asset_expired') and allowance.file_jobs_this_week(customer) == 0

    # Its bytes gone from under its row: found out by the worker, and nothing is counted either.
    asset.update(state='ready')
    second = quoted(customer, draft)
    job, _ = submit_job(customer, second.id, 'a-picture-gone-from-the-disk')
    storage.delete(asset.get().object_key)
    job = execute_job(job.id)
    assert (job.status, job.error_code) == ('failed', 'pinned_asset_expired') and allowance.file_jobs_this_week(customer) == 0


def test_a_picture_the_bucket_will_not_give_back_is_gone_and_one_with_other_bytes_has_changed(customer, stock_photos, bucket, monkeypatch, django_capture_on_commit_callbacks):  # noqa: F811
    with django_capture_on_commit_callbacks(execute=True):
        draft, _ = generate(customer)
    storage.sync()
    asset = FileAsset.objects.get(pk=pinned_assets(draft)[PHOTO])
    job, _ = submit_job(customer, quoted(customer, draft).id, 'a-picture-the-bucket-holds-back')
    path = storage.storage_path(asset.object_key)
    kept = path.read_bytes()
    path.unlink()

    def refuse(**kwargs):
        raise OSError('the bucket is not answering')
    monkeypatch.setattr(bucket, 'get_object', refuse)
    job = execute_job(job.id)
    assert (job.status, job.error_code) == ('failed', 'pinned_asset_expired') and allowance.file_jobs_this_week(customer) == 0
    monkeypatch.undo()

    path.write_bytes(kept)
    job, _ = submit_job(customer, quoted(customer, draft).id, 'a-picture-with-other-bytes')
    path.write_bytes(kept[:-1] + b'\0')
    job = execute_job(job.id)
    assert (job.status, job.error_code) == ('failed', 'file_changed') and allowance.file_jobs_this_week(customer) == 0


def test_a_candidate_gone_or_a_picture_on_a_slide_since_removed_stops_nothing(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    pins = pins_of(draft)
    FileAsset.objects.filter(pk=pins['photos'][PHOTO]['candidates'][0]['asset_id']).update(state='deleted')
    assert quoted(customer, draft).input_ids

    FileAsset.objects.filter(pk=pinned_assets(draft)[PHOTO]).update(state='deleted')
    content = copy.deepcopy(unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)['content'])
    content['sections'] = [section for section in content['sections'] if section['id'] != PHOTO]
    draft.refresh_from_db()
    shorter = update_draft(customer, draft.id, {'version': draft.version, 'content': content})
    quote = quoted(customer, shorter)
    assert quote.input_ids == [pinned_assets(shorter)[COVER]]


def test_a_picture_that_cannot_be_placed_is_said_on_the_file(customer, stock_photos, monkeypatch):  # noqa: F811
    draft, _ = generate(customer)

    def unplaceable(*args, **kwargs):
        raise ValueError('not a picture')
    monkeypatch.setattr('apps.studio.slide_layouts.place_photo', unplaceable)
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert job.warnings == ['images_skipped'] and media(delivered(job)) == []


def test_a_slide_laid_out_without_its_picture_does_not_need_it(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    photo = pinned_assets(draft)[PHOTO]
    edited = edit_section(customer, draft, PHOTO, layout='bullets')
    FileAsset.objects.filter(pk=photo).update(state='deleted')
    job = send(customer, edited)
    assert job.status == 'succeeded', job.error_code
    assert FileAsset.objects.filter(pk=pinned_assets(edited)[COVER]).exists()


# ---------------------------------------------------------------- text that would not show


def test_a_slide_too_long_is_refused_at_the_quote_and_named_with_the_words_that_would_not_show(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    edited = edit_section(customer, draft, LIST, body='\n'.join(fixtures.line('en', 590) for _ in range(9)))
    with pytest.raises(DomainError) as refused:
        quoted(customer, edited)
    assert refused.value.code == 'slide_text_too_long' and refused.value.status == 409
    sections = refused.value.params['sections']
    assert [(slide['id'], slide['index']) for slide in sections] == [(LIST, 4)] and sections[0]['words_over'] > 50

    answer = api_post(customer, f'{draft.id}/export-quote', version=edited.version, format='pptx', deliver='chat')
    assert answer.status_code == 409
    error = answer.json()['error']
    assert error['code'] == 'slide_text_too_long' and error['message_params'] == {'sections': sections}
    assert PRIVATE not in json.dumps(error) and fixtures.line('en', 590) not in json.dumps(error)
    assert not Quote.objects.filter(account=customer, feature_id=EXPORT).exists()

    # Put right, it goes; nothing was cut from the draft meanwhile.
    assert unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)['content']['sections'][4]['body'].count('\n') == 8
    fixed = edit_section(customer, draft, LIST, body='One line that fits')
    assert send(customer, fixed).status == 'succeeded'


def test_a_slide_that_does_not_fit_when_the_job_runs_fails_it_with_nothing_shortened_or_counted(customer, stock_photos, monkeypatch):  # noqa: F811
    draft, _ = generate(customer)
    edited = edit_section(customer, draft, LIST, body='\n'.join(fixtures.line('en', 590) for _ in range(9)))
    monkeypatch.setattr(render_export, 'over_budget', lambda data, chosen: [])
    quote = quoted(customer, edited)
    job, _ = submit_job(customer, quote.id, 'a-send-the-measure-missed')
    job = execute_job(job.id)
    assert (job.status, job.error_code) == ('failed', 'slide_text_too_long')
    assert not job.artifacts.exists() and allowance.file_jobs_this_week(customer) == 0
    assert not services.storage_path(f'outputs/{customer.id}/{job.id}').exists()
    assert job_data(job)['error']['code'] == 'slide_text_too_long'


def test_a_question_slide_too_long_is_named_too(customer, stock_photos):  # noqa: F811
    long_question = ' '.join(fixtures.words('en', 400).split())
    asked = [{'id': f'q{n}', 'stem': long_question[:2000], 'options': ['North', 'South'], 'answer': 'North', 'marks': 1} for n in range(1, 6)]
    draft = deck_draft(customer, sections=[{**section, 'image_query': ''} for section in deck_sections()], asked=asked)
    assert run(customer, draft).status == 'succeeded'
    with pytest.raises(DomainError, match='slide_text_too_long') as refused:
        quoted(customer, draft)
    assert [(slide['id'], slide['index']) for slide in refused.value.params['sections']] == [('q1', 8)]


def test_a_very_long_deck_is_refused_in_good_time_with_the_first_slides_named(customer, monkeypatch):  # noqa: F811
    sections = [{**section, 'image_query': ''} for section in deck_sections()]
    draft, _ = generate(customer, sections=sections, asked=[])
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    content = copy.deepcopy(data['content'])
    for section in content['sections'][1:]:
        section['heading'] = ' '.join(fixtures.words('en', 30).split())
    draft.refresh_from_db()
    edited = update_draft(customer, draft.id, {'version': draft.version, 'content': content})
    ticking(monkeypatch)
    with pytest.raises(DomainError, match='slide_text_too_long') as refused:
        quoted(customer, edited)
    assert [slide['id'] for slide in refused.value.params['sections']] == [CARDS]


def test_a_slide_too_long_past_what_the_quote_had_time_to_measure_fails_when_drawn_and_the_next_quote_names_it(customer, stock_photos, monkeypatch):  # noqa: F811
    draft, _ = generate(customer)
    edited = edit_section(customer, draft, LIST, body='\n'.join(fixtures.line('en', 590) for _ in range(9)))
    ticking(monkeypatch)
    quote = quoted(customer, edited)
    job, _ = submit_job(customer, quote.id, 'a-send-measured-in-part')
    job = execute_job(job.id)
    assert (job.status, job.error_code) == ('failed', 'slide_text_too_long') and allowance.file_jobs_this_week(customer) == 0

    # Asked again, the quote is no slower and no worse informed: it names the slide the send failed on.
    named = job_data(job)['parameters']['too_long']
    assert [(slide['id'], slide['index']) for slide in named] == [(LIST, 4)] and set(named[0]) == {'id', 'index', 'words_over'}
    ticking(monkeypatch)
    monkeypatch.setattr(slide_fit, 'measure_deck', lambda *args, **kwargs: pytest.fail('nothing needs measuring again'))
    with pytest.raises(DomainError, match='slide_text_too_long') as refused:
        quoted(customer, edited)
    assert refused.value.params['sections'] == named
    monkeypatch.undo()

    # Any edit is another draft to the quote: it measures that one, and the send goes.
    fixed = edit_section(customer, draft, LIST, body='One line that fits')
    assert send(customer, fixed).status == 'succeeded'


def test_a_send_that_failed_for_anything_else_or_on_other_bytes_says_nothing_of_the_slides(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    job, _ = submit_job(customer, quoted(customer, draft).id, 'overtaken-by-an-edit')
    edited = edit_section(customer, draft, LIST, body='An edit that fits')
    assert execute_job(job.id).error_code == 'version_conflict'
    assert quoted(customer, edited).feature_id == EXPORT
    other = Job.objects.filter(pk=job.pk)
    other.update(error_code='slide_text_too_long', parameters={**job.parameters, 'too_long': [{'id': LIST, 'index': 4, 'words_over': 9}]})
    assert quoted(customer, edited).feature_id == EXPORT, 'that send was of the draft before this edit'


def test_a_pin_that_no_longer_holds_its_slide_is_written_back_changing_nothing_else(customer, stock_photos):  # noqa: F811
    draft, first = generate(customer)
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    kept = copy.deepcopy(data['_render']['variants'])
    data['_render']['variants'][CARDS] = 'cards.retired_since'
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    draft.refresh_from_db()

    other = quoted(customer, draft)
    before = other.parameters['snapshot']
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    artifact = job.artifacts.get().file
    assert artifact.metadata['repinned'] == [CARDS]

    after = pins_of(draft)
    assert after['variants'][CARDS] not in ('cards.retired_since', None) and variants.get(after['variants'][CARDS])
    assert {key: value for key, value in after['variants'].items() if key != CARDS} == {key: value for key, value in kept.items() if key != CARDS}
    assert {key: value for key, value in after.items() if key != 'variants'} == {key: value for key, value in data['_render'].items() if key != 'variants'}
    assert artifact.metadata['render']['variants'] == after['variants']
    current = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    assert current['content'] == data['content'] and GenerationDraft.objects.get(pk=draft.pk).version == draft.version

    # Another send quoted on those bytes is no worse off for it: it moves with them, as for a generation's pins.
    other.refresh_from_db()
    assert other.parameters['snapshot'] != before
    assert other.parameters['snapshot'] == hashlib.sha256(bytes(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)).hexdigest()
    waiting, _ = submit_job(customer, other.id, 'a-send-after-a-repin')
    assert execute_job(waiting.id).status == 'succeeded'
    # And the next deck holds to the new pin.
    assert drawn_again(customer, draft).artifacts.get().file.metadata['repinned'] == []


def test_a_draft_rebuilt_during_the_send_gets_no_pins_from_it(customer, stock_photos, monkeypatch):  # noqa: F811
    draft, _ = generate(customer)
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    data['_render']['variants'][CARDS] = 'cards.retired_since'
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    real = execution._write_pins

    def rebuilt_first(job, draft_id, pins, version):
        row = GenerationDraft.objects.get(pk=draft_id)
        update_draft(customer, row.id, {'version': row.version, 'prompt': 'Another deck altogether, about rivers.'})
        real(job, draft_id, pins, version)
    monkeypatch.setattr(execution, '_write_pins', rebuilt_first)
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert '_render' not in unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)


# ---------------------------------------------------------------- how long it all lasts


def test_a_send_extends_the_draft_its_pictures_and_their_candidates_to_its_own_deadline(customer, stock_photos, clock):  # noqa: F811
    draft, first = generate(customer)
    pictures = list(kept_pictures(customer))
    assert len(pictures) == 6
    as_delivered = media(delivered(first))
    clock(20)
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    deadline = job.artifacts.get().file.expires_at
    assert deadline > first.artifacts.get().file.expires_at
    draft.refresh_from_db()
    assert draft.expires_at == deadline
    assert all(FileAsset.objects.get(pk=picture_.pk).expires_at == deadline for picture_ in pictures)

    clock(30)
    cleanup_expired()
    assert GenerationDraft.objects.filter(pk=draft.pk).exists() and all(FileAsset.objects.get(pk=picture_.pk).state == 'ready' for picture_ in pictures)
    again = resend(customer, draft)
    assert again == job and media(delivered(again)) == as_delivered
    later = job.artifacts.get().file
    later.refresh_from_db()
    draft.refresh_from_db()
    assert later.expires_at > deadline and draft.expires_at == later.expires_at, 'the file sent again and what changes it end together'
    assert all(FileAsset.objects.get(pk=picture_.pk).expires_at == later.expires_at for picture_ in pictures)

    clock(60)
    cleanup_expired()
    assert not GenerationDraft.objects.filter(pk=draft.pk).exists() and not kept_pictures(customer).exists()


def test_a_failed_send_moves_no_clock(customer, stock_photos, clock):  # noqa: F811
    draft, _ = generate(customer)
    until = GenerationDraft.objects.get(pk=draft.pk).expires_at
    pictures = {picture_.pk: picture_.expires_at for picture_ in kept_pictures(customer)}
    job, _ = submit_job(customer, quoted(customer, draft).id, 'a-send-that-will-fail')
    edit_section(customer, draft, CARDS, heading='Edited meanwhile')
    clock(1)
    assert execute_job(job.id).status == 'failed'
    assert GenerationDraft.objects.get(pk=draft.pk).expires_at == until
    assert {picture_.pk: picture_.expires_at for picture_ in kept_pictures(customer)} == pictures


def test_a_resend_at_hour_23_keeps_every_picture(customer, stock_photos, clock):  # noqa: F811
    draft, first = generate(customer)
    photos_before = media(delivered(first))
    clock(23)
    cleanup_expired()
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert media(delivered(job)) == photos_before and len(photos_before) == 2
    assert slide_xml(delivered(job)) == slide_xml(delivered(first))


def test_a_send_takes_its_pictures_from_the_bucket_once_the_disk_has_let_them_go(customer, stock_photos, bucket, django_capture_on_commit_callbacks):  # noqa: F811
    with django_capture_on_commit_callbacks(execute=True):
        draft, first = generate(customer)
    as_delivered = media(delivered(first))
    storage.sync()
    for key in kept_pictures(customer).values_list('object_key', flat=True):
        storage.storage_path(key).unlink()
    job = send(customer, draft)
    assert job.status == 'succeeded', job.error_code
    assert media(delivered(job)) == as_delivered


def test_a_send_accepted_as_the_draft_ends_finds_all_it_draws_when_its_turn_comes(customer, stock_photos, clock):  # noqa: F811
    draft, first = generate(customer)
    as_delivered = media(delivered(first))
    clock(23.99)
    quote = quoted(customer, draft)
    job, _ = submit_job(customer, quote.id, 'in-the-last-minute')
    clock(24.5)
    cleanup_expired()
    done = execute_job(job.id)
    assert done.status == 'succeeded', done.error_code
    assert media(delivered(done)) == as_delivered
    assert done.artifacts.get().file.expires_at == GenerationDraft.objects.get(pk=draft.pk).expires_at


def test_a_send_that_waited_too_long_says_so_and_counts_nothing(customer, stock_photos, clock):  # noqa: F811
    draft, _ = generate(customer)
    clock(23.5)
    quote = quoted(customer, draft)
    job, _ = submit_job(customer, quote.id, 'waited-past-the-hour')
    clock(25)
    cleanup_expired()
    # Its pictures are kept from cleanup while it waits, whatever becomes of the rest of the deck.
    assert all(asset.state == 'ready' and storage.exists(asset.object_key) for asset in FileAsset.objects.filter(pk__in=quote.input_ids))
    assert kept_pictures(customer).count() == len(quote.input_ids)
    done = execute_job(job.id)
    assert (done.status, done.error_code) == ('failed', 'pinned_asset_expired')
    assert allowance.file_jobs_this_week(customer) == 0


def test_a_deck_from_a_file_can_still_be_saved_and_changed_after_the_files_first_day(customer, clock):  # noqa: F811
    """The draft outlives its first day only through a send: saving and asking for a change look for its file."""
    source = upload(customer)
    sections = [{**section, 'image_query': ''} for section in deck_sections()]
    made = create_draft(customer, {'feature_id': SLIDES, 'title': TITLE, 'source_text': 'Notes.', 'source_ids': [str(source.id)], 'options': {'pages': len(sections), 'deck_design': DESIGN}})
    made = update_draft(customer, made.id, {'version': made.version, 'content': {'title': TITLE, 'sections': sections, 'questions': [], 'citations': []}})
    assert run(customer, made).status == 'succeeded'
    clock(20)
    assert send(customer, made).status == 'succeeded'
    clock(30)
    cleanup_expired()
    saved_now = edit_section(customer, made, CARDS, heading='Reworded a day later')
    assert send(customer, saved_now).status == 'succeeded'
    change = create_draft(customer, {'prompt': 'Make the second slide shorter.', 'options': {'revise_draft_id': str(made.id)}})
    assert run(customer, change).status == 'succeeded'


# ---------------------------------------------------------------- branding


def branded_deck(customer, mark):  # noqa: F811
    sections = [{**section, 'image_query': ''} for section in deck_sections()]
    made = create_draft(customer, {'feature_id': SLIDES, 'title': TITLE, 'source_text': 'Notes.',
                                   'options': {'pages': len(sections), 'deck_design': DESIGN, 'branding': {'name': 'Harbour School', 'accent': '#285cff', 'logo_asset_id': str(mark.id)}}})
    made = update_draft(customer, made.id, {'version': made.version, 'content': {'title': TITLE, 'sections': sections, 'questions': [], 'citations': []}})
    assert run(customer, made).status == 'succeeded'
    made.refresh_from_db()
    return made


def test_a_logo_is_read_again_and_lives_as_long_as_the_deck(customer, clock):  # noqa: F811
    mark = logo(customer)
    draft = branded_deck(customer, mark)
    clock(20)
    job = send(customer, draft)
    assert job.status == 'succeeded' and job.warnings == []
    assert media(delivered(job)), 'the logo is on it'
    deadline = job.artifacts.get().file.expires_at
    assert FileAsset.objects.get(pk=mark.pk).expires_at == deadline
    # So an autosave a day later still finds it, as every save of a branded draft looks for it.
    clock(30)
    assert edit_section(customer, draft, CARDS, heading='Reworded a day later')
    assert send(customer, draft).warnings == []


@pytest.mark.parametrize('gone', ['deleted', 'expired'])
def test_a_logo_that_has_gone_is_said_at_the_quote_and_on_the_file_which_keeps_the_name_and_colour(customer, gone):  # noqa: F811
    mark = logo(customer)
    draft = branded_deck(customer, mark)
    FileAsset.objects.filter(pk=mark.pk).update(**({'state': 'deleted'} if gone == 'deleted' else {'expires_at': timezone.now() - timedelta(minutes=1)}))
    answer = api_post(customer, f'{draft.id}/export-quote', version=draft.version, format='pptx', deliver='chat')
    assert answer.status_code == 201, answer.content
    assert answer.json()['summary']['warnings'] == ['logo_left_out']
    job, _ = submit_job(customer, answer.json()['id'], 'a-send-with-no-logo')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    assert job.warnings == ['logo_left_out'] and job_data(job)['warnings'] == ['logo_left_out']
    assert media(delivered(job)) == [] and 'Harbour School' in artifact_text(delivered(job))
    assert all(set(UX[locale]) >= {'logo_left_out'} for locale in ('en', 'uz', 'ru'))


def test_branding_the_plan_has_lost_is_refused_at_the_quote(customer, hold_back):  # noqa: F811
    draft = branded_deck(customer, logo(customer))
    hold_back('template.branding', customer.plan)
    with pytest.raises(DomainError, match='feature_not_in_plan'):
        quoted(customer, draft)


# ---------------------------------------------------------------- what is kept


def test_no_word_of_the_deck_reaches_a_quote_a_job_or_the_logs(customer, stock_photos, office, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    made, _ = generate(customer, title='Marker of a title')
    secret_notes = f'{PRIVATE} says this in the notes'
    edited = edit_section(customer, made, CARDS, heading=f'{PRIVATE} heading', notes=secret_notes)
    edited = edit_section(customer, edited, LIST, body=f'{PRIVATE} body line')
    quote = quoted(customer, edited, 'both', 'chat')
    job, _ = submit_job(customer, quote.id, 'the-private-words')
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    assert PRIVATE in artifact_text(storage.local(next(artifact.file for artifact in files(job) if artifact.file.mime_type == PPTX_MIME).object_key))

    quote = Quote.objects.get(pk=quote.pk)
    job = Job.objects.get(pk=job.pk)
    rows = [quote.parameters, quote.policy, quote.input_ids, quote.input_fingerprints, quote.meters, job.parameters, job.policy, job.warnings, job.error_code, job.engine,
            quote_data(quote)['normalized_parameters'], job_data(job)['parameters'],
            [list(AnalyticsEvent.objects.filter(job=job).values_list('properties', flat=True))], list(OutboxEvent.objects.filter(job=job).values('topic'))]
    written = json.dumps(rows, ensure_ascii=False, default=str)
    assert PRIVATE not in written and 'Marker of a title' not in written
    assert PRIVATE not in caplog.text and 'Marker of a title' not in caplog.text
    # What is echoed of a send is ids and the format.
    assert set(job_data(job)['parameters']) == {'generation_draft_id', 'version', 'snapshot', 'format', 'deliver'}
    assert job_data(job)['input_files'] == [], 'its pictures are the deck\'s own, not files the customer gave'
    # The file's own record keeps no more of it than a generation's does: its title goes with the file's name, not its metadata.
    for artifact in files(job):
        kept = json.dumps(artifact.file.metadata, ensure_ascii=False)
        assert PRIVATE not in kept and 'Marker of a title' not in kept and 'deck_seed' not in {key for key in artifact.file.metadata}


def test_a_refused_quote_leaves_no_row(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    edited = edit_section(customer, draft, LIST, body='\n'.join(fixtures.line('en', 590) for _ in range(9)))
    before = Quote.objects.count()
    with pytest.raises(DomainError):
        quoted(customer, edited)
    assert Quote.objects.count() == before


def test_the_new_errors_are_said_in_every_language(settings):
    for code in ('deck_not_editable', 'pinned_asset_expired', 'slide_text_too_long'):
        messages = {locale: error_data(DomainError(code), locale)['message'] for locale in ('en', 'uz', 'ru')}
        fallback = error_data(DomainError('invalid_request'), 'en')['message']
        assert len(set(messages.values())) == 3 and fallback not in messages.values()
        assert not re.search('[А-Яа-яЁё]', messages['uz']) and re.search('[А-Яа-яЁё]', messages['ru'])
        assert "'" not in messages['uz'], 'o‘ and g‘ take U+2018, and the tutuq U+02BC'
        for message in messages.values():
            assert not re.search(r'click|export|quote|rasteri|dpi|encoding|\bpoints\b|нажм|экспорт', message, re.I)


# ---------------------------------------------------------------- the bot


@pytest.mark.parametrize('sent_at', [20, 25], ids=['before_the_first_file_ends', 'past_it_with_the_button_not_yet_cleaned_up'])
def test_the_change_button_lives_as_long_as_the_newest_file(customer, stock_photos, clock, sent_at):  # noqa: F811
    draft, first = generate(customer)
    enqueue(first.artifacts.get(), f'job:{first.id}')
    button = result_controls(BotDelivery.objects.get(artifact__job=first)).inline_keyboard[0][0].callback_data
    row = BotCallback.objects.filter(pk=button)
    first_ends = row.get().expires_at
    assert first_ends == first.artifacts.get().file.expires_at
    if sent_at > 24:
        clock(20)
        assert send(customer, draft).status == 'succeeded'
        assert row.get().expires_at == first_ends, 'a send to the web has no button to move'
    clock(sent_at)
    job = send(customer, draft, origin='bot') if sent_at <= 24 else resend(customer, draft, origin='bot')
    assert job.status == 'succeeded', job.error_code
    delivery = BotDelivery.objects.get(artifact__job=job)
    assert result_controls(delivery).inline_keyboard[0][0].callback_data == button
    assert row.get().expires_at == job.artifacts.get().file.expires_at > timezone.now() and row.get().expires_at > first_ends
    # Sent again for an older file, it keeps the later end.
    result_controls(BotDelivery.objects.get(artifact__job=first))
    assert row.get().expires_at == job.artifacts.get().file.expires_at
    assert BotCallback.objects.filter(account=customer, action='ai_revise').count() == 1


def test_the_bots_as_pdf_takes_the_deck_as_last_sent(customer, stock_photos, office):  # noqa: F811
    draft, first = generate(customer)
    assert ai.delivered(customer, draft.id)[0] == first
    edited = edit_section(customer, draft, LIST, body='An edited line')
    both = send(customer, edited, 'both')
    assert both.status == 'succeeded', both.error_code
    powerpoint = next(artifact.file for artifact in both.artifacts.select_related('file') if artifact.file.metadata['kind'] == 'pptx')
    assert ai.delivered(customer, draft.id) == (both, powerpoint)
    assert ai.deck_to_pdf(customer, draft.id).input_ids == [str(powerpoint.id)]

    # Its file gone, the file before it is no stand-in: it lacks what was edited.
    FileAsset.objects.filter(pk=powerpoint.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert ai.delivered(customer, draft.id) == (None, None) and ai.deck_to_pdf(customer, draft.id) is None
    FileAsset.objects.filter(pk=powerpoint.pk).update(expires_at=timezone.now() + timedelta(hours=1))

    # Nor is it when the deck was last sent as a PDF alone.
    alone = send(customer, edit_section(customer, draft, LIST, body='Edited once more'), 'pdf')
    assert alone.status == 'succeeded', alone.error_code
    assert ai.delivered(customer, draft.id) == (None, None) and ai.deck_to_pdf(customer, draft.id) is None


def as_a_job(customer, asset):  # noqa: F811
    from apps.core.services import create_quote
    quote = create_quote(customer, ai.CONVERTER, [str(asset.id)], {})
    job, _ = submit_job(customer, quote.id, f'tool-{quote.id}', origin='bot')
    return execute_job(job.id)


def test_the_bots_as_pdf_draws_our_deck_in_its_faces_and_the_same_bytes_uploaded_in_a_customers(customer, stock_photos, office, tmp_path):  # noqa: F811
    draft, first = generate(customer)
    deck = first.artifacts.get().file
    tool = ai.deck_to_pdf(customer, draft.id)
    assert tool.input_ids == [str(deck.id)]
    assert as_a_job(customer, deck).status == 'succeeded'
    log = tmp_path / 'fontconfig.log'
    assert log.read_text().strip().endswith('/deck-fonts.conf')

    # The file itself says nothing a customer could not write: only the job that made it does.
    log.unlink()
    copy_of_it = services.upload_file(customer, SimpleUploadedFile('deck.pptx', storage.read_bytes(deck.object_key), PPTX_MIME))
    assert as_a_job(customer, copy_of_it).status == 'succeeded'
    assert set(log.read_text().split()) == {'none'}


def test_the_change_button_and_the_labels_follow_a_sent_deck(customer, stock_photos, office):  # noqa: F811
    draft, _ = generate(customer)
    job = send(customer, draft, 'both', origin='bot')
    assert job.status == 'succeeded', job.error_code
    deliveries = list(BotDelivery.objects.filter(account=customer, artifact__job=job))
    assert len(deliveries) == 2, 'both files arrive'
    for delivery in deliveries:
        assert revisable_draft(delivery) == str(draft.id)
        labels = [button.text for row in result_controls(delivery).inline_keyboard for button in row]
        assert UX['en']['ai_revise'] in labels
    assert set(TOOL_NAMES[EXPORT]) == {'en', 'uz', 'ru'} and all('AI' not in name and 'ИИ' not in name for name in TOOL_NAMES[EXPORT].values())
    assert not re.search('[А-Яа-яЁё]', TOOL_NAMES[EXPORT]['uz'])


def sent_again(account):
    """The files the bot sent again, by format; those sent with a job are not among them."""
    return sorted(delivery.artifact.file.metadata['kind'] for delivery in BotDelivery.objects.filter(account=account, idempotency_key__startswith='resend:').select_related('artifact__file'))


def said(result):
    return '\n'.join(message['text'] for message in result['messages'] if message.get('direction') != 'inbound')


def bot_deck(account):
    delivered = made(account)
    return GenerationDraft.objects.filter(account=account, feature_id=SLIDES).latest('created_at'), delivered


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_deck_sent_as_a_pdf_alone_is_that_pdf_when_asked_and_no_older_powerpoint(chatting, office):
    draft, delivered = bot_deck(chatting)
    alone = send(chatting, draft, 'pdf', origin='bot')
    assert alone.status == 'succeeded', alone.error_code

    assert UX['en']['ai_same_format'].format(format='PDF') in said(change(chatting, delivered, 'send it as PDF'))
    assert sent_again(chatting) == ['pdf'] and not BotDraft.objects.filter(account=chatting, feature_id=ai.CONVERTER).exists(), 'sent as it is, with no tool to start'

    words, labels = screen(change(chatting, delivered, 'send it as PowerPoint'))
    assert words == UX['en']['ai_edited_not_kept'].format(format='PowerPoint'), words
    assert UX['en']['ai_revise'] in labels and sent_again(chatting) == ['pdf'], 'the older deck is not offered as this one'


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_deck_with_its_pdf_gone_is_not_sent_to_the_converter_from_the_older_copy(chatting, office):
    draft, delivered = bot_deck(chatting)
    alone = send(chatting, draft, 'pdf', origin='bot')
    FileAsset.objects.filter(pk=alone.artifacts.get().file_id).update(expires_at=timezone.now() - timedelta(seconds=1))
    words, _ = screen(change(chatting, delivered, 'send it as PDF'))
    assert words == UX['en']['ai_edited_not_kept'].format(format='PDF'), words
    assert UX['en']['ai_deck_gone'] not in words and sent_again(chatting) == []


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_of_a_deck_sent_as_both_the_bot_sends_again_only_the_format_asked_for(chatting, office):
    draft, delivered = bot_deck(chatting)
    assert send(chatting, draft, 'both', origin='bot').status == 'succeeded'

    assert UX['en']['ai_same_format'].format(format='PowerPoint') in said(change(chatting, delivered, 'send it as PowerPoint'))
    assert sent_again(chatting) == ['pptx']

    assert UX['en']['ai_same_format'].format(format='PDF') in said(change(chatting, delivered, 'send it as PDF'))
    assert sent_again(chatting) == ['pdf', 'pptx']


def test_the_edited_deck_message_is_said_in_every_language():
    assert all('{format}' in UX[locale]['ai_edited_not_kept'] for locale in ('en', 'uz', 'ru'))
    assert not re.search('[А-Яа-яЁё]', UX['uz']['ai_edited_not_kept'])


def test_a_send_that_fails_says_no_task_was_used(settings, stock_photos):  # noqa: F811
    from telegram.notifications import not_counted
    settings.DEBUG = True
    free = account()
    draft, _ = generate(free)
    job, _ = submit_job(free, quoted(free, draft).id, 'a-send-that-fails-in-the-bot', origin='bot')
    edit_section(free, draft, CARDS, heading='Edited meanwhile')
    done = execute_job(job.id)
    assert done.status == 'failed' and not_counted(done, 'en')


# ---------------------------------------------------------------- the routes


def test_measuring_a_slide_tells_how_it_sits_and_which_layouts_would_hold_it(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    data = unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    held = bytes(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)
    section = next(section for section in data['content']['sections'] if section['id'] == LIST)

    answer = api_post(customer, f'{draft.id}/fit', section=section)
    assert answer.status_code == 200, answer.content
    fit = answer.json()
    assert set(fit) == {'id', 'index', 'fits', 'words_over', 'lines_used', 'lines_max', 'layouts_fitting'}
    assert fit['id'] == LIST and fit['index'] == 4 and fit['fits'] is True and fit['words_over'] == 0
    assert 0 < fit['lines_used'] <= fit['lines_max'] and 'bullets' in fit['layouts_fitting']
    assert 'cover' not in fit['layouts_fitting'] and 'closing' not in fit['layouts_fitting'], 'not the slide this is'
    assert not set(fit['layouts_fitting']) & {'image_split', 'image_full'}, 'it has no picture'

    longer = {**section, 'body': '\n'.join(fixtures.line('en', 590) for _ in range(9))}
    over = api_post(customer, f'{draft.id}/fit', section=longer).json()
    assert over['fits'] is False and over['words_over'] > 50 and over['lines_used'] > over['lines_max'] and 'bullets' not in over['layouts_fitting']
    assert bytes(GenerationDraft.objects.get(pk=draft.pk).encrypted_data) == held, 'nothing saved'

    pictured = next(section for section in data['content']['sections'] if section['id'] == PHOTO)
    assert 'image_split' in api_post(customer, f'{draft.id}/fit', section=pictured).json()['layouts_fitting']
    # A divider has no place for cards: they would go unseen, which is no fit. A list takes them.
    cards = next(section for section in data['content']['sections'] if section['id'] == CARDS)
    other_layouts = api_post(customer, f'{draft.id}/fit', section=cards).json()['layouts_fitting']
    assert {'cards', 'bullets'} <= set(other_layouts) and 'section' not in other_layouts
    # Nor does a stale list behind a slide's own lines make it a slide of cards.
    lines_first = {**section, 'items': [{'label': f'Stale {number}', 'text': 'Not shown', 'value': ''} for number in range(3)]}
    assert 'cards' not in api_post(customer, f'{draft.id}/fit', section=lines_first).json()['layouts_fitting']
    cover = next(section for section in data['content']['sections'] if section['id'] == COVER)
    assert api_post(customer, f'{draft.id}/fit', section=cover).json()['layouts_fitting'] == ['cover']


def test_measuring_a_slide_about_to_be_added_or_one_badly_made(customer, stock_photos):  # noqa: F811
    draft, _ = generate(customer)
    added = api_post(customer, f'{draft.id}/fit', section={'id': 'added-now', 'heading': 'A new slide', 'body': 'First line\nSecond line', 'layout': 'bullets'}).json()
    assert added['id'] == 'added-now' and added['index'] == 8 and added['fits'] is True
    assert api_post(customer, f'{draft.id}/fit', section={'heading': 'No id yet', 'body': 'A line'}).json()['fits'] is True
    for wrong in ('words', None, {'id': 's9', 'heading': 'H', 'body': 'B', 'layout': 'not-a-layout'}, {'id': 's9', 'heading': 'H', 'body': 'B', 'items': 'none'}):
        answer = api_post(customer, f'{draft.id}/fit', section=wrong)
        assert answer.status_code == 400 and answer.json()['error']['code'] == 'invalid_parameters', wrong


def test_a_slide_past_what_the_plan_holds_is_refused(customer, stock_photos, monkeypatch):  # noqa: F811
    draft, _ = generate(customer)
    sections = len(unpack(GenerationDraft.objects.get(pk=draft.pk).encrypted_data)['content']['sections'])
    monkeypatch.setattr('apps.studio.domain.limits', lambda account: {'sections': sections, 'slides': sections, 'questions': 40, 'source_chars': 1000})
    with pytest.raises(DomainError, match='generation_limit'):
        fit_section(customer, draft.id, {'id': 'one-too-many', 'heading': 'H', 'body': 'B'})


def test_the_routes_are_held_to_a_rate_per_account(customer, stock_photos, settings):  # noqa: F811
    from apps.studio import views
    draft, _ = generate(customer)
    answers = [api_post(customer, f'{draft.id}/export-quote', version=draft.version, format='pptx', deliver='chat').status_code for _ in range(views.EXPORT_QUOTES_PER_MINUTE + 1)]
    assert answers[:-1] == [201] * views.EXPORT_QUOTES_PER_MINUTE and answers[-1] == 429
    answers = [api_post(customer, f'{draft.id}/fit', section={'id': LIST, 'heading': 'H', 'body': 'B'}).status_code for _ in range(views.FITS_PER_MINUTE + 1)]
    assert answers[:-1] == [200] * views.FITS_PER_MINUTE and answers[-1] == 429
    # One account's minute is not another's.
    other = paid(settings, account(77))
    assert api_post(other, f'{uuid.uuid4()}/fit', section={}).status_code == 404


def test_the_contract_describes_both_routes():
    from apps.core.management.commands.export_contract import schema
    contract = schema()
    route = contract['paths']['/generation/drafts/{id}/export-quote']['post']
    assert set(route['requestBody']['content']['application/json']['schema']['required']) == {'version', 'format', 'deliver'}
    assert {'deck_not_editable', 'pinned_asset_expired', 'slide_text_too_long'} <= set(re.findall(r'`(\w+)`', route['description']))
    assert contract['components']['schemas']['DeckExportSummary']['required'] == ['slides', 'format', 'kept_until', 'size_estimate', 'cost', 'warnings']
    assert contract['components']['schemas']['DeckSlideFit']['required'] == ['id', 'index', 'fits', 'words_over', 'lines_used', 'lines_max', 'layouts_fitting']
    assert '/generation/drafts/{id}/fit' in contract['paths']


# ---------------------------------------------------------------- the measure


def plain_deck(*sections):
    first = {'id': 'c', 'heading': 'Cover', 'body': 'Subtitle', 'layout': 'cover'}
    return {'title': 'A deck', 'questions': [], 'citations': [], 'sections': [first, *sections]}


def slide(section_id='s', **fields):
    return {'id': section_id, 'heading': 'Heading', 'body': '', 'notes': '', 'layout': 'bullets', 'items': [], 'columns': [], 'image_query': '', **fields}


def over_of(content, tmp_path, **options):
    return {row['id']: row['words_over'] for row in render_pptx(content, tmp_path / 'measured.pptx', **options)['metadata']['shortened']}


@pytest.mark.parametrize('section,words', [
    (slide(heading=' '.join(f'w{n}' for n in range(20)), body='A line'), 6),                                    # a heading's limit of 14
    (slide(body='\n'.join(f'line number {n}' for n in range(8))), 6),                                           # two lines past six
    (slide(body='one\ntwo\nthree', layout='section'), 2),                                                       # a divider has room for one line
    (slide(layout='cards', items=[{'label': f'L{n}', 'text': 'Words here', 'value': ''} for n in range(3)] + [{'label': '', 'text': 'no label', 'value': ''}]), 2),
    (slide(layout='stats', items=[{'label': 'Share', 'text': 'x', 'value': '10 20 30 40'}, {'label': 'Rate', 'text': 'y', 'value': '5'}]), 1),  # a figure's three words
    (slide(layout='quote', body=' '.join(f'w{n}' for n in range(50)), items=[{'label': 'Someone', 'text': 'a role', 'value': ''}]), 5),         # a quotation's 45
    (slide(layout='stats', items=[{'label': 'Share', 'text': 'x', 'value': 'high'}, {'label': 'Rate', 'text': 'y', 'value': 'low'}]), 0),       # no figures: a list, whole
], ids=['heading', 'too_many_lines', 'divider', 'no_label', 'figure', 'quotation', 'fallback'])
def test_a_deck_reports_each_slide_it_shortened_and_by_how_many_words(tmp_path, section, words):
    assert over_of(plain_deck(section), tmp_path).get('s', 0) == words


@pytest.mark.parametrize('design', ['', DESIGN, CAPITALS])
def test_a_title_page_of_eight_lines_shows_them_all_and_a_ninth_does_not(tmp_path, design):
    """More than a list holds, which marks the deck shortened, and every one of them on the cover all the same."""
    style = {'deck_design': design} if design else {}
    lines = [f'Line {word}' for word in ('one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine')]
    cover = slide('c', heading='Cover', layout='cover', body='\n'.join(lines[:5]))
    assert over_of({**plain_deck(), 'sections': [cover, slide('s', body='A line')]}, tmp_path, style=style) == {}
    cover = {**cover, 'body': '\n'.join(lines)}
    content = {**plain_deck(), 'sections': [cover, slide('s', body='A line')]}
    assert over_of(content, tmp_path, style=style).get('c', 0) == measure_deck(content, style=style)[0]['words_over'] >= 2


def test_what_a_layout_has_no_place_for_is_not_missing_from_it(tmp_path):
    """A list's items beside its body, a process step's value, a chart's sentences, items on a cover: nobody ever saw those on a slide."""
    deck = plain_deck(slide('a', body='A line', items=[{'label': 'not drawn', 'text': 'nor this', 'value': ''}]),
                      slide('b', layout='process', body='not drawn either', items=[{'label': f'Step {n}', 'text': 'Go', 'value': 'not drawn'} for n in range(3)]),
                      slide('c2', layout='chart', items=[{'label': 'A', 'text': 'not drawn', 'value': '1'}, {'label': 'B', 'text': 'not drawn', 'value': '2'}]))
    assert over_of(deck, tmp_path) == {}
    # The editor offers no items on a cover or a divider, so they can hold up no send.
    deck['sections'][0] = {**deck['sections'][0], 'body': '', 'items': [{'label': f'Item {n}', 'text': 'Not drawn', 'value': ''} for n in range(4)]}
    deck['sections'].append(slide('d', layout='section', items=[{'label': f'Item {n}', 'text': 'Not drawn', 'value': ''} for n in range(2)]))
    assert over_of(deck, tmp_path) == {}


@pytest.mark.parametrize('kind', list(fixtures.RANGES))
@pytest.mark.parametrize('locale', fixtures.LOCALES)
def test_a_slide_filled_to_its_guide_loses_nothing_in_any_variant(kind, locale):
    """No send is ever held up by a word every variant draws: the guides are what the model is asked for."""
    from apps.studio.deck_designs import look as design_look
    from apps.studio.slide_layouts import Ctx
    from apps.studio import layouts, slides as deck_slides
    style = {'deck_design': DESIGN}
    look = design_look(style)
    roles = deck_slides.palette(look['accent'], look['theme'], look['secondary'], look.get('paper'), look.get('accent_headings', False))
    scratch = variants.Scratch(deck_slides.SLIDE_WIDTH, deck_slides.SLIDE_HEIGHT)
    low, high = fixtures.RANGES[kind]
    for count in {low, high}:
        for section in (fixtures.section(kind, count, locale), fixtures.light(kind, count, locale)):
            lines, _ = deck_slides.bullets_of(section['body'])
            if not lines and section.get('items'):
                lines, _ = deck_slides.bullets_of('\n'.join(layouts.as_lines(section)))
            for variant in variants.load(kind).values():
                if variant.holds(section, lines):
                    target = scratch.slide()
                    context = Ctx(target, roles, style, 3, 12, 18, locale, kind.startswith('image'), None, look['heading_bold'])
                    variant.draw(context, section, lines)
                    if not (context.shortened or context.squeezed):
                        assert left_out(kind, section, list(target.shapes._spTree)[2:]) == 0, variant.id


def everything(locale='en', make=fixtures.section):
    sections = [slide('c', heading='Cover', body='Subtitle', layout='cover')]
    for kind, (low, high) in fixtures.RANGES.items():
        for count in {low, high}:
            sections.append({**make(kind, count, locale), 'id': f's{len(sections)}', 'notes': 'To say'})
    sections.append(slide('divider', heading='Part two', body='A kicker\nAnother line', layout='section'))
    sections.append(slide('long', body='\n'.join(fixtures.line(locale, 590) for _ in range(9))))
    sections.append(slide('end', heading='Thanks', body='Questions welcome', layout='closing'))
    return {'title': 'Everything', 'citations': [], 'sections': sections,
            'questions': [{'id': f'q{n}', 'stem': f'Which pier, case {n}?', 'options': ['North', 'South'], 'answer': 'North', 'marks': 1} for n in range(1, 8)]}


@pytest.mark.parametrize('design,locale', [('midnight', 'en'), ('', 'ru'), *((key, 'uz') for key in ONE_OF_EACH_COMPOSITION)])
def test_the_measure_says_what_the_drawing_comes_to(tmp_path, design, locale):
    content = everything(locale)
    style = {'deck_design': design} if design else {}
    has_picture = {section['id'] for section in content['sections'] if section['layout'] in ('cover', 'image_split', 'image_full')}
    jpeg = {'jpeg': picture(1), 'width': 1600, 'height': 1000}
    photos = {section_id: jpeg for section_id in has_picture}
    first = render_pptx(content, tmp_path / 'first.pptx', locale, style=style, photos=photos)
    pins = {'body_size': first['metadata']['body_size'], 'deck_seed': first['metadata']['deck_seed'], 'design': first['metadata']['design'],
            'variants': {section['id']: variant for section, variant in zip(content['sections'], first['metadata']['variants'])}}
    drawn = render_pptx(content, tmp_path / 'again.pptx', locale, style=style, photos=photos, pins=pins)
    measured = measure_deck(content, locale, style, pins, has_picture)
    assert {row['id']: row['words_over'] for row in measured if not row['fits']} == {row['id']: row['words_over'] for row in drawn['metadata']['shortened']}
    assert {row['id'] for row in measured if not row['fits']} == {'divider', 'long'}
    assert [row['index'] for row in measured] == list(range(drawn['page_count'])) and {row['id'] for row in drawn['metadata']['shortened']} == {'divider', 'long'}
    for row in measured:
        assert row['lines_used'] <= row['lines_max'] if row['fits'] else row['lines_used'] > row['lines_max'], row
        assert row['lines_max'] > 0, row
    # The measure leaves no mark: with the same pins the same slides come out.
    assert slide_xml(tmp_path / 'again.pptx') == slide_xml(tmp_path / 'first.pptx')


def test_a_whole_deck_is_measured_in_about_a_second_with_no_file_and_no_picture(tmp_path, monkeypatch):
    """0.6 s for 60 slides of every field full, on an M2 Pro: this holds it to the same order on a busy runner."""
    kinds = list(fixtures.RANGES)
    sections = [slide('c', heading='Cover', body='Subtitle', layout='cover')]
    for number in range(59):
        kind = kinds[number % len(kinds)]
        if kind.startswith('image'):
            kind = 'bullets'
        sections.append({**fixtures.section(kind, fixtures.RANGES[kind][1], 'ru'), 'id': f's{number}'})
    content = {'title': 'Sixty slides', 'questions': [], 'citations': [], 'sections': sections}
    first = render_pptx(content, tmp_path / 'first.pptx', 'ru', style={'deck_design': DESIGN})
    pins = {'body_size': first['metadata']['body_size'], 'deck_seed': first['metadata']['deck_seed'], 'design': first['metadata']['design'],
            'variants': {section['id']: variant for section, variant in zip(sections, first['metadata']['variants'])}}

    def refuse(*args, **kwargs):
        raise AssertionError('the measure reads and writes no file of a deck')
    monkeypatch.setattr('pptx.presentation.Presentation.save', refuse)
    monkeypatch.setattr('subprocess.run', refuse)
    monkeypatch.setattr('subprocess.Popen', refuse)
    started = time.monotonic()
    measured = measure_deck(content, 'ru', {'deck_design': DESIGN}, pins)
    assert time.monotonic() - started < 5 and len(measured) == 60


def test_past_its_time_the_measure_stops_whatever_it_has_found(monkeypatch):
    content = plain_deck(slide('a', body='A line'), slide('b', layout='section', body='one\ntwo'), slide('d', layout='section', body='one\ntwo'))
    assert [row['id'] for row in measure_deck(content)] == ['c', 'a', 'b', 'd']
    ticking(monkeypatch)
    assert [row['id'] for row in measure_deck(content, seconds=3)] == ['c', 'a', 'b']
    # A deck that fits has no refusal to give, and holds the API worker just the same.
    ticking(monkeypatch)
    assert [(row['id'], row['fits']) for row in measure_deck(plain_deck(slide('a', body='A line'), slide('b', body='B line')), seconds=2)] == [('c', True), ('a', True)]
    # Asked about one slide, it is the slides before that are given up, never that one.
    ticking(monkeypatch)
    assert [row['id'] for row in measure_deck(content, only={'d'}, seconds=0)] == ['d']


def test_past_its_time_measuring_one_slide_says_no_layouts_rather_than_some(monkeypatch):
    content = plain_deck(slide('a', body='A line'), slide('b', body='B line'))
    assert 'bullets' in measure_deck(content, only={'a'})[0]['layouts_fitting']
    ticking(monkeypatch)
    # Read first as it starts, and on the way to each layout: it gets through two of them.
    row = measure_deck(content, only={'a'}, seconds=2)[0]
    assert row['fits'] is True and row['lines_max'] > 0 and row['layouts_fitting'] == []


@pytest.mark.parametrize('kind,words', [('stats', 34), ('process', 32)])
def test_a_deck_that_fits_where_every_slide_tries_many_variants_holds_the_worker_only_so_long(kind, words):
    """60 such slides take 3 to 8 s on an M2 Pro: one account at the quote limit would hold more than an API worker."""
    made = {**fixtures.section(kind, fixtures.RANGES[kind][1], 'en'), 'body': ''}
    made['items'] = [{'label': fixtures.words('en', 3, k), 'text': fixtures.words('en', words, k), 'value': f'{k}%'} for k in range(6)]
    content = {'title': 'Sixty slides', 'questions': [], 'citations': [], 'sections': [slide('c', heading='Cover', body='Subtitle', layout='cover'), *({**made, 'id': f's{number}'} for number in range(59))]}
    started = time.monotonic()
    measured = measure_deck(content, 'en', {'deck_design': 'midnight'}, {'deck_seed': 'a seed'}, seconds=0.2)
    assert time.monotonic() - started < 3 and 0 < len(measured) < 60 and all(row['fits'] for row in measured)


def test_a_slide_on_a_deck_that_tries_many_variants_is_measured_in_about_its_time():
    """Unbounded, the last of 60 such slides takes 5 to 10 s, and on such a deck a live measure came to 1.3 s when it had 0.5."""
    made = {**fixtures.section('stats', fixtures.RANGES['stats'][1], 'en'), 'body': ''}
    made['items'] = [{'label': fixtures.words('en', 3, k), 'text': fixtures.words('en', 34, k), 'value': f'{k}%'} for k in range(6)]
    content = {'title': 'Sixty slides', 'questions': [], 'citations': [], 'sections': [slide('c', heading='Cover', body='Subtitle', layout='cover'), *({**made, 'id': f's{number}'} for number in range(59))]}
    started = time.monotonic()
    measured = measure_deck(content, 'en', {'deck_design': 'midnight'}, {'deck_seed': 'a seed'}, only={'s58'}, seconds=0.1)
    assert time.monotonic() - started < 2 and measured[0]['id'] == 's58' and measured[0]['layouts_fitting'] == []


@pytest.mark.parametrize('pins', [{}, {'variants': {'a': 'process.nothing', 'c2': 'cards.no_longer_there'}}], ids=['no_pins', 'pins_that_do_not_hold'])
def test_measuring_one_slide_is_what_measuring_the_deck_says_of_it(pins):
    """The slides of its layout before it take their variants first, so it is not measured on one the drawing gives another."""
    def section_of(kind, number):
        return {**fixtures.section(kind, fixtures.RANGES[kind][1], 'en'), 'id': number}
    sections = [slide('c', heading='Cover', body='Subtitle', layout='cover'), section_of('cards', 'a'), section_of('stats', 'b'), section_of('cards', 'c2'),
                section_of('stats', 'd'), section_of('cards', 'e'), section_of('cards', 'f')]
    content = {'title': 'Slides', 'questions': [], 'citations': [], 'sections': sections}
    style, pins = {'deck_design': 'midnight'}, {'deck_seed': 'a seed', **pins}
    whole = {row['id']: row for row in measure_deck(content, 'en', style, pins)}
    for section_id in whole:
        alone = measure_deck(content, 'en', style, pins, only={section_id})[0]
        assert {**alone, 'layouts_fitting': []} == whole[section_id]
