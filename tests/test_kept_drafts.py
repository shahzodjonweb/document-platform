"""✏️ Make changes keeps working for good: a generated document's draft, and every file a change of it needs, never expire.

What the customer was sent goes after 24 hours, as every result does; the draft
it was made from stays until the customer deletes it, with its sources, logo,
pictures and slides. So a change asked for a day, or 400 days, later is quoted
and made, in the chat from the old message's button and on the web, and a change
of that change too. A draft never generated, the results themselves and uploads
no kept draft needs still go after 24 hours.
"""
import json
import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.commerce.models import BotDelivery
from apps.core import storage
from apps.core.models import BotCallback, FileAsset, Job
from apps.core.services import cleanup_expired, execute_job, submit_job
from apps.studio import keeping
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, draft_data, generation_quote, pack, unpack, update_draft
from apps.studio.models import GenerationDraft, SlideRender
from telegram.local import deliver_local, dispatch_local, history
from tests.test_bot_edit_review import converter  # noqa: F401
from tests.test_bot_generation import body, customer as chatting, describe, labels, stage_pdf, tap  # noqa: F401
from tests.test_deck_pins import CARDS, PHOTO, customer, deck_sections, media, delivered, pins_of, questions, stock_photos  # noqa: F401
from tests.test_editor_tasks import converted  # noqa: F401
from tests.test_manual_payments import paid as paid_by_card
from tests.test_platform import login_client, upload
from tests.test_studio_branding import logo

DAY = 25
LONG_AFTER = 400 * 24
CHANGE = 'Use a friendlier tone throughout.'


@pytest.fixture(autouse=True)
def deck_editor_on(monkeypatch, settings):
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '1')
    monkeypatch.setenv('EDITOR_FLAG_PHOTOS_TASK', '1')
    settings.LOCAL_SYNC_JOBS = True


@pytest.fixture
def clock(monkeypatch):
    """The platform's clock, this many hours from now; the cleanup runs as the service would, every time it moves."""
    start = timezone.now()

    def move(hours, clean=True):
        moment = start + timedelta(hours=hours)
        monkeypatch.setattr(timezone, 'now', lambda: moment)
        if clean:
            cleanup_expired()
        return moment
    return move


def gone(asset):
    """A file that is no more: its row deleted or marked so, and its bytes away."""
    row = FileAsset.objects.filter(pk=asset.pk).first()
    return row is None or (row.state in ('expired', 'deleted', 'revoked') and not storage.exists(row.object_key))


def there(asset):
    row = FileAsset.objects.filter(pk=asset.pk).first()
    return row is not None and row.state == 'ready' and row.expires_at > timezone.now() and storage.exists(row.object_key)


def draft_of(job):
    return GenerationDraft.objects.get(pk=job.parameters['generation_draft_id'])


def deck_files(draft):
    """The deck's own pictures (worn and on offer) and its slides as last drawn."""
    pins = pins_of(draft)
    ids = {photo['asset_id'] for photo in pins['photos'].values() if photo['asset_id']}
    ids |= {c['asset_id'] for photo in pins['photos'].values() for c in photo['candidates'] if c.get('asset_id')}
    ids |= {str(value) for pair in SlideRender.objects.filter(draft=draft).values_list('file_id', 'thumb_id') for value in pair}
    return list(FileAsset.objects.filter(pk__in=ids))


def made_deck(account, mark=None, origin='web', sources=()):
    """A deck with pictures on its cover and a slide, and a logo or a source, made as a customer has one."""
    sections = deck_sections()
    options = {'pages': len(sections), 'deck_design': 'midnight'}
    if mark is not None:
        options['branding'] = {'name': 'Harbour School', 'accent': '#285cff', 'logo_asset_id': str(mark.id)}
    draft = create_draft(account, {'feature_id': SLIDES, 'title': 'Harbour logistics review', 'source_text': 'Notes about the harbour.',
                                   'source_ids': [str(asset.id) for asset in sources], 'options': options})
    draft = update_draft(account, draft.id, {'version': draft.version, 'content': {
        'title': 'Harbour logistics review', 'sections': sections, 'questions': questions(), 'citations': []}})
    quote = generation_quote(account, draft.id, draft.version)
    job, _ = submit_job(account, quote.id, f'deck-{quote.id}', origin=origin)
    job = execute_job(job.id)
    assert job.status == 'succeeded', job.error_code
    draft.refresh_from_db()
    return draft, job


def in_chat(account, job):
    """The job's files sent to the chat as the bot sends them, under their buttons."""
    for delivery in BotDelivery.objects.filter(account=account, artifact__job=job):
        deliver_local(account, delivery)
    return history(account)


def changed_in_chat(account, delivered, request=CHANGE):
    """✏️ Make changes tapped on a delivered file, the change written, and Generate tapped: the new job."""
    asked = tap(account, delivered, 'Make changes')
    assert 'What should change?' in body(asked), body(asked)[-400:]
    review = dispatch_local(account, text=request)
    assert request in body(review), body(review)[-400:]
    before = set(Job.objects.filter(account=account).values_list('pk', flat=True))
    result = tap(account, review, 'Generate')
    job = Job.objects.filter(account=account).exclude(pk__in=before).get()
    assert job.status == 'succeeded', job.error_code
    assert job.parameters.get('revision') is True
    return job, result


# ---------------------------------------------------------------- in the chat


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_document_made_in_the_chat_takes_a_change_a_day_and_400_days_later(chatting, clock):  # noqa: F811
    source = stage_pdf(chatting)
    material = ' '.join(['tide'] * 390)
    delivered_now = tap(chatting, describe(chatting, f'A 1 page guide to tide tables.\n\n{material}'), 'Generate')
    made = Job.objects.get(account=chatting, feature_id=DOCUMENT)
    assert made.status == 'succeeded', made.error_code
    draft = draft_of(made)
    assert keeping.is_kept(draft.expires_at)
    assert unpack(draft.encrypted_data)['source_ids'] == [str(source.id)]
    result = made.artifacts.get().file

    clock(DAY)
    assert gone(result), 'the file sent goes after 24 hours, as every result does'
    assert there(source), 'the file it was made from stays with its draft'
    first, delivered_later = changed_in_chat(chatting, delivered_now)
    assert keeping.is_kept(draft_of(first).expires_at), 'a change is kept once its file is made'

    clock(LONG_AFTER)
    paid_by_card(chatting, 'premium')
    assert GenerationDraft.objects.filter(pk=draft.pk).exists() and there(source)
    again, _ = changed_in_chat(chatting, delivered_now, 'Make it two pages long.')
    assert unpack(draft_of(again).encrypted_data)['revision']['source_draft_id'] == str(draft.pk)
    # A change of the change, from the button under the file the change sent.
    later, _ = changed_in_chat(chatting, delivered_later, 'Add an example to each section.')
    assert unpack(draft_of(later).encrypted_data)['revision']['source_draft_id'] == str(draft_of(first).pk)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_deck_with_pictures_and_a_source_takes_a_change_in_the_chat_400_days_later(chatting, stock_photos, clock):  # noqa: F811
    source = upload(chatting, 'harbour-notes.pdf')
    draft, made = made_deck(chatting, origin='bot', sources=[source])
    chat = in_chat(chatting, made)
    assert 'Make changes' in ' '.join(labels(chat)), labels(chat)
    pictures = deck_files(draft)
    assert any(asset.metadata['kind'] == 'deck_photo' for asset in pictures)
    assert all(keeping.is_kept(asset.expires_at) for asset in pictures)
    button = BotCallback.objects.get(account=chatting, action='ai_revise', payload={'draft_id': str(draft.pk)})
    assert keeping.is_kept(button.expires_at), 'the button lasts as long as its draft'

    clock(DAY)
    assert gone(made.artifacts.get().file)
    clock(LONG_AFTER)
    paid_by_card(chatting, 'premium')
    assert BotCallback.objects.filter(pk=button.pk).exists()
    assert there(source) and all(there(asset) for asset in pictures)
    change, _ = changed_in_chat(chatting, chat)
    assert change.feature_id == SLIDES and change.artifacts.get().file.name.endswith('.pptx')


# ---------------------------------------------------------------- on the web


@pytest.mark.django_db
def test_on_the_web_a_change_is_asked_quoted_and_made_400_days_later(customer, clock):  # noqa: F811
    source = upload(customer, 'tides.pdf')
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Tides', 'source_text': 'The moon pulls the sea twice a day.',
                                    'source_ids': [str(source.id)]})
    quote = generation_quote(customer, draft.id, draft.version)
    made = execute_job(submit_job(customer, quote.id, 'web-document')[0].id)
    assert made.status == 'succeeded'

    clock(LONG_AFTER)
    paid_by_card(customer, 'premium')
    client = login_client(customer)
    shown = client.get(f'/api/v1/generation/drafts/{draft.id}')
    assert shown.status_code == 200 and shown.json()['expires_at'] is None, 'kept: no date to show'
    assert client.get(f'/api/v1/files/{source.id}').json()['expires_at'] is None
    asked = client.post('/api/v1/generation/drafts', json.dumps({'prompt': CHANGE, 'options': {'revise_draft_id': str(draft.id)}}),
                        content_type='application/json')
    assert asked.status_code == 201, asked.content
    change = asked.json()
    assert change['expires_at'], 'a change not yet made has its day, as any new draft'
    priced = client.post(f'/api/v1/generation/drafts/{change["id"]}/quote', json.dumps({'version': change['version']}),
                         content_type='application/json')
    assert priced.status_code == 201, priced.content
    job = client.post('/api/v1/jobs', json.dumps({'quote_id': priced.json()['id']}), content_type='application/json',
                      headers={'Idempotency-Key': 'change-a-year-later'})
    assert job.status_code == 201 and job.json()['status'] == 'succeeded', job.content
    assert client.get(f'/api/v1/generation/drafts/{change["id"]}').json()['expires_at'] is None


@pytest.mark.django_db
def test_in_the_deck_editor_a_deck_with_a_logo_is_opened_changed_and_sent_400_days_later(customer, stock_photos, converted, clock):  # noqa: F811
    mark = logo(customer)
    draft, made = made_deck(customer, mark=mark)
    pictures = deck_files(draft)
    assert there(mark) and keeping.is_kept(FileAsset.objects.get(pk=mark.pk).expires_at)

    clock(DAY)
    assert gone(made.artifacts.get().file)
    clock(LONG_AFTER)
    paid_by_card(customer, 'premium')
    assert there(mark) and all(there(asset) for asset in pictures)
    client = login_client(customer)
    opened = client.get(f'/api/v1/generation/drafts/{draft.id}').json()
    assert opened['render'] and opened['expires_at'] is None
    # Its logo is held for the deck, no download after its day; the deck's own pictures and slides are the editor's.
    assert client.get(f'/api/v1/files/{mark.id}/download').status_code == 410
    # Saved as the editor saves it, drawn, and a picture taken off and put back.
    content = opened['content']
    content['sections'][1]['heading'] = 'Reworded a year later'
    saved = client.patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': opened['version'], 'content': content}),
                         content_type='application/json')
    assert saved.status_code == 200, saved.content
    drawing = client.post(f'/api/v1/generation/drafts/{draft.id}/render', json.dumps({'version': saved.json()['version']}),
                          content_type='application/json')
    assert drawing.status_code == 202, drawing.content
    state = client.get(f'/api/v1/generation/drafts/{draft.id}/render').json()
    assert state['status'] == 'done', state
    assert client.get(state['slides'][0]['url']).status_code == 200
    worn = pins_of(draft)['photos'][PHOTO]['asset_id']
    assert client.get(f'/api/v1/generation/drafts/{draft.id}/pictures/{worn}.jpg').status_code == 200
    removed = client.post(f'/api/v1/generation/drafts/{draft.id}/photos', json.dumps({'action': 'remove', 'version': saved.json()['version'], 'section_id': PHOTO}),
                          content_type='application/json')
    assert removed.status_code == 200, removed.content
    back = client.post(f'/api/v1/generation/drafts/{draft.id}/photos', json.dumps({'action': 'next', 'version': removed.json()['version'], 'section_id': PHOTO}),
                       content_type='application/json')
    assert back.status_code == 202, back.content
    assert client.get(f'/api/v1/generation/drafts/{draft.id}/photos/{back.json()["task_id"]}').json()['status'] == 'done'
    draft.refresh_from_db()
    assert all(keeping.is_kept(asset.expires_at) for asset in deck_files(draft))
    # Sent again, logo and all.
    quote = client.post(f'/api/v1/generation/drafts/{draft.id}/export-quote', json.dumps({'version': draft.version, 'format': 'pptx', 'deliver': 'download'}),
                        content_type='application/json')
    assert quote.status_code == 201, quote.content
    sent = client.post('/api/v1/jobs', json.dumps({'quote_id': quote.json()['id']}), content_type='application/json',
                       headers={'Idempotency-Key': 'send-a-year-later'})
    assert sent.status_code == 201 and sent.json()['status'] == 'succeeded', sent.content
    job = Job.objects.get(pk=sent.json()['id'])
    assert job.warnings == [] and media(delivered(job)), 'the logo is on it'
    # And asked to change, from the editor's Ask AI.
    asked = client.post('/api/v1/generation/drafts', json.dumps({'prompt': CHANGE, 'options': {'revise_draft_id': str(draft.id)}}),
                        content_type='application/json')
    assert asked.status_code == 201, asked.content


# ---------------------------------------------------------------- what still goes


@pytest.mark.django_db
def test_a_draft_never_made_results_and_other_uploads_still_go_after_24_hours(customer, clock):  # noqa: F811
    source, unrelated, unsent_source = upload(customer, 'a.pdf'), upload(customer, 'b.pdf'), upload(customer, 'c.pdf')
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Tides', 'source_text': 'The moon pulls the sea.',
                                    'source_ids': [str(source.id)]})
    made = execute_job(submit_job(customer, generation_quote(customer, draft.id, draft.version).id, 'made-document')[0].id)
    unsent = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Waves', 'source_text': 'Wind makes waves.',
                                     'source_ids': [str(unsent_source.id)]})
    assert not keeping.is_kept(unsent.expires_at)
    assert login_client(customer).get(f'/api/v1/generation/drafts/{unsent.id}').json()['expires_at'], 'its day is still said'

    clock(DAY)
    assert not GenerationDraft.objects.filter(pk=unsent.pk).exists(), 'a draft never generated expires as before'
    assert gone(unsent_source) and gone(unrelated) and gone(made.artifacts.get().file)
    assert GenerationDraft.objects.filter(pk=draft.pk).exists() and there(source)


@pytest.mark.django_db
def test_an_outline_alone_keeps_nothing(customer, clock):  # noqa: F811
    from apps.studio.outlines import create_outline_quote
    draft = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Tides', 'source_text': 'The moon pulls the sea.'})
    quote = create_outline_quote(customer, draft.id, draft.version)
    assert execute_job(submit_job(customer, quote.id, 'outline-only')[0].id).status == 'succeeded'
    draft.refresh_from_db()
    assert not keeping.is_kept(draft.expires_at), 'an outline is a plan, not a file'
    clock(DAY)
    assert not GenerationDraft.objects.filter(pk=draft.pk).exists()


@pytest.mark.django_db
def test_a_picture_the_deck_no_longer_wears_or_offers_goes_on_its_own_clock(customer, stock_photos, clock):  # noqa: F811
    draft, _ = made_deck(customer)
    pins = pins_of(draft)
    offered = [c['asset_id'] for c in pins['photos'][PHOTO]['candidates'] if c.get('asset_id')]
    assert offered
    data = unpack(draft.encrypted_data)
    data['_render']['photos'][PHOTO]['candidates'] = []
    GenerationDraft.objects.filter(pk=draft.pk).update(encrypted_data=pack(data))
    draft.refresh_from_db()
    keeping.hold(draft)
    for asset in FileAsset.objects.filter(pk__in=offered):
        assert not keeping.is_kept(asset.expires_at) and asset.expires_at <= timezone.now() + keeping.OWN_CLOCK
    clock(DAY)
    assert all(gone(asset) for asset in FileAsset.objects.filter(pk__in=offered)) or not FileAsset.objects.filter(pk__in=offered).exists()
    assert there(FileAsset.objects.get(pk=pins_of(draft)['photos'][PHOTO]['asset_id']))


# ---------------------------------------------------------------- deleting


@pytest.mark.django_db
def test_deleting_the_document_takes_its_draft_and_files_but_not_what_another_kept_draft_holds(customer, stock_photos, clock):  # noqa: F811
    mark, other_mark = logo(customer), logo(customer)
    draft, _ = made_deck(customer, mark=mark)
    sibling, _ = made_deck(customer, mark=other_mark)
    pictures = deck_files(draft)
    clock(LONG_AFTER)
    client = login_client(customer)
    # A change of the deck holds its logo too.
    asked = client.post('/api/v1/generation/drafts', json.dumps({'prompt': CHANGE, 'options': {'revise_draft_id': str(sibling.id)}}),
                        content_type='application/json').json()
    paid_by_card(customer, 'premium')
    priced = client.post(f'/api/v1/generation/drafts/{asked["id"]}/quote', json.dumps({'version': asked['version']}), content_type='application/json').json()
    assert client.post('/api/v1/jobs', json.dumps({'quote_id': priced['id']}), content_type='application/json',
                       headers={'Idempotency-Key': 'the-change'}).json()['status'] == 'succeeded'

    assert client.delete(f'/api/v1/generation/drafts/{draft.id}').json() == {'deleted': True}
    assert not GenerationDraft.objects.filter(pk=draft.pk).exists()
    assert not BotCallback.objects.filter(action='ai_revise', payload={'draft_id': str(draft.pk)}).exists()
    clock(LONG_AFTER + 1)
    assert all(gone(asset) for asset in pictures) and gone(mark)
    assert client.get(f'/api/v1/generation/drafts/{draft.id}').status_code == 404

    assert client.delete(f'/api/v1/generation/drafts/{sibling.id}').json() == {'deleted': True}
    clock(LONG_AFTER + 2)
    assert there(other_mark), 'the change still holds the logo'
    assert client.delete(f'/api/v1/generation/drafts/{asked["id"]}').json() == {'deleted': True}
    clock(LONG_AFTER + 3)
    assert gone(other_mark)


@pytest.mark.django_db
def test_deleting_the_account_takes_every_kept_draft_and_its_files(customer, stock_photos, clock):  # noqa: F811
    mark = logo(customer)
    draft, _ = made_deck(customer, mark=mark)
    pictures = deck_files(draft)
    clock(DAY)
    answer = login_client(customer).delete('/api/v1/me')
    assert answer.json() == {'status': 'deletion_requested'}
    assert not GenerationDraft.objects.filter(account=customer).exists()
    clock(DAY + 1)
    assert gone(mark) and all(gone(asset) for asset in pictures)


# ---------------------------------------------------------------- drafts from before


@pytest.mark.django_db
def test_drafts_with_a_file_from_before_are_kept_by_the_next_cleanup_and_unsent_ones_are_not(customer, stock_photos, clock):  # noqa: F811
    mark = logo(customer)
    draft, made = made_deck(customer, mark=mark)
    unsent = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Waves', 'source_text': 'Wind makes waves.'})
    # As the platform left them before: the draft, its pictures, slides, logo and button on the result's clock.
    deadline = made.artifacts.get().file.expires_at
    GenerationDraft.objects.filter(pk=draft.pk).update(expires_at=deadline)
    files = deck_files(draft)
    FileAsset.objects.filter(pk__in=[asset.pk for asset in files] + [mark.pk]).update(expires_at=deadline)
    FileAsset.objects.filter(pk=mark.pk).update(metadata={key: value for key, value in mark.metadata.items() if key != 'kept_by'})
    BotCallback.objects.create(token='old-change-button', account=customer, action='ai_revise', payload={'draft_id': str(draft.pk)}, expires_at=deadline)

    clock(1)
    draft.refresh_from_db()
    assert keeping.is_kept(draft.expires_at)
    assert all(keeping.is_kept(FileAsset.objects.get(pk=asset.pk).expires_at) for asset in [*files, mark])
    assert keeping.is_kept(BotCallback.objects.get(pk='old-change-button').expires_at)
    assert not keeping.is_kept(GenerationDraft.objects.get(pk=unsent.pk).expires_at)
    assert keeping.backfill() == 0, 'once is enough'
    clock(LONG_AFTER)
    assert GenerationDraft.objects.filter(pk=draft.pk).exists() and there(mark)
    assert not GenerationDraft.objects.filter(pk=unsent.pk).exists()


# ---------------------------------------------------------------- the far-off moment


@pytest.mark.django_db
def test_nothing_shortens_what_is_kept(customer, stock_photos):  # noqa: F811
    """A file task on a kept source settles with its 24 hours, as every task does: the source and the draft stay as they are."""
    mark, source = logo(customer), upload(customer, 'harbour-notes.pdf')
    draft, _ = made_deck(customer, mark=mark, sources=[source])
    from apps.core.services import create_quote
    rotated = execute_job(submit_job(customer, create_quote(customer, 'pdf.rotate', [str(source.id)], {}).id, 'rotate-a-source')[0].id)
    assert rotated.status == 'succeeded', rotated.error_code
    assert keeping.is_kept(FileAsset.objects.get(pk=source.pk).expires_at)
    assert not keeping.is_kept(rotated.artifacts.get().file.expires_at), 'its result goes after 24 hours'
    draft.refresh_from_db()
    assert draft.expires_at == keeping.KEPT_UNTIL and keeping.is_kept(FileAsset.objects.get(pk=mark.pk).expires_at)


@pytest.mark.django_db
def test_the_kept_moment_is_never_shown_as_a_date(customer, stock_photos):  # noqa: F811
    mark = logo(customer)
    draft, made = made_deck(customer, mark=mark)
    assert draft_data(draft)['expires_at'] is None
    client = login_client(customer)
    listed = client.get('/api/v1/generation/drafts').json()['results']
    assert [row['expires_at'] for row in listed if row['id'] == str(draft.id)] == [None]
    assert client.get(f'/api/v1/files/{mark.id}').json()['expires_at'] is None
    assert '2999' not in client.get(f'/api/v1/generation/drafts/{draft.id}').content.decode()
    job = client.get(f'/api/v1/jobs/{made.id}').json()
    assert job['artifacts'][0]['expires_at'], 'the file it was sent as still says when it goes'
    assert [row['expires_at'] for row in job['input_files']] == [None], 'its logo, kept with it, says nothing'

def test_what_a_change_reads_again_is_what_is_kept():
    """Its quote's files (sources and logo) and a CV's photo; a CV's own files never, as what they gave is in the draft."""
    logo_id, source_id, photo_id = (str(uuid.uuid4()) for _ in range(3))
    document = {'source_ids': [source_id], 'options': {'branding': {'logo_asset_id': logo_id}}}
    cv = {'source_ids': [source_id], 'options': {'cv_source': 'file', 'portrait_asset_id': photo_id}}
    assert keeping._uploads(document) == {source_id, logo_id}
    assert keeping._uploads(cv) == {photo_id}
    assert keeping.shown(keeping.KEPT_UNTIL) is None and keeping.shown(timezone.now()) is not None


# ---------------------------------------------------------------- after review


@pytest.fixture
def orphans_due(monkeypatch):
    """The backstop's own schedule, fresh: another test's clock never decides whether it runs in this one."""
    monkeypatch.setattr(keeping, '_orphans', {'at': None})


def document(account, name, **extra):
    draft = create_draft(account, {'feature_id': DOCUMENT, 'title': name, 'source_text': f'Notes about {name}.', **extra})
    made = execute_job(submit_job(account, generation_quote(account, draft.id, draft.version).id, f'doc-{draft.id}')[0].id)
    assert made.status == 'succeeded', made.error_code
    draft.refresh_from_db()
    return draft, made


@pytest.mark.django_db
def test_one_unreadable_old_draft_never_stops_the_cleanup(customer, clock, caplog):  # noqa: F811
    """A draft from before that cannot be read is left to expire; the others are kept and every file still goes on time."""
    readable, _ = document(customer, 'Tides')
    unreadable, _ = document(customer, 'Waves')
    unrelated = upload(customer, 'unrelated.pdf')
    # As the platform left them before: on their result's day, not kept; one of them a row no key opens any more.
    deadline = timezone.now() + timedelta(hours=24)
    GenerationDraft.objects.filter(pk__in=[readable.pk, unreadable.pk]).update(expires_at=deadline)
    GenerationDraft.objects.filter(pk=unreadable.pk).update(encrypted_data=b'not a token')

    clock(DAY)
    assert gone(unrelated), 'files still expire after the draft that failed'
    assert keeping.is_kept(GenerationDraft.objects.get(pk=readable.pk).expires_at), 'the readable one is kept'
    assert not GenerationDraft.objects.filter(pk=unreadable.pk).exists(), 'the unreadable one expires as it would have'
    assert 'could not be kept' in caplog.text


@pytest.mark.django_db
def test_a_kept_draft_removed_any_other_way_lets_its_files_go(customer, stock_photos, clock, orphans_due):  # noqa: F811
    """A row deleted by hand, not through keeping.delete: the backstop gives its files their own clock back."""
    source = upload(customer, 'harbour-notes.pdf')
    first, _ = made_deck(customer, sources=[source])
    second, _ = made_deck(customer, sources=[source])
    assert set(FileAsset.objects.get(pk=source.pk).metadata['kept_by']) == {str(first.pk), str(second.pk)}
    pictures = deck_files(first)
    assert pictures and all(keeping.is_kept(asset.expires_at) for asset in pictures)
    BotCallback.objects.create(token='orphan-change-button', account=customer, action='ai_revise',
                               payload={'draft_id': str(first.pk)}, expires_at=keeping.KEPT_UNTIL)

    GenerationDraft.objects.filter(pk=first.pk).delete()
    clock(DAY)
    assert all(gone(asset) for asset in pictures), 'its own pictures and slides go with it'
    assert not BotCallback.objects.filter(pk='orphan-change-button').exists()
    assert there(source) and FileAsset.objects.get(pk=source.pk).metadata['kept_by'] == [str(second.pk)], 'still held by the other'
    assert all(there(asset) for asset in deck_files(second))

    GenerationDraft.objects.filter(pk=second.pk).delete()
    clock(DAY + keeping.ORPHANS_EVERY.total_seconds() / 3600 + 1)
    assert gone(source), 'held by nothing, it goes'


@pytest.mark.django_db
def test_support_deletes_a_customers_ai_documents_with_their_files(customer, stock_photos, clock, settings):  # noqa: F811
    from operations.models import AuditLog
    from tests.test_operations_admin import staff_client
    settings.DEBUG = True
    mark = logo(customer)
    draft, _ = made_deck(customer, mark=mark)
    create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Waves', 'source_text': 'Wind makes waves.'})
    pictures = deck_files(draft)
    finance, _ = staff_client('Finance')
    assert finance.post(f'/ops/users/{customer.id}/documents/delete', {'confirm': 'yes'}).status_code == 403
    client, user = staff_client('Support')
    page = client.get(f'/ops/users/{customer.id}').content.decode()
    assert '2 AI documents, 1 of them kept for changes.' in page and 'delete-documents' in page
    assert client.post(f'/ops/users/{customer.id}/documents/delete', {}).status_code == 400, 'confirmed or nothing'
    assert GenerationDraft.objects.filter(account=customer).count() == 2

    answer = client.post(f'/ops/users/{customer.id}/documents/delete', {'confirm': 'yes'})
    assert answer.status_code == 302
    assert not GenerationDraft.objects.filter(account=customer).exists()
    entry = AuditLog.objects.get(action='account.documents_delete')
    assert entry.actor == user and entry.target == str(customer.id) and entry.before == {'documents': 2, 'kept': 1}
    clock(DAY)
    assert gone(mark) and all(gone(asset) for asset in pictures)


@pytest.mark.django_db
def test_another_picture_on_a_kept_deck_long_after_asks_pixabay_again_by_its_id(customer, stock_photos, clock):  # noqa: F811
    """Pixabay's links last about a day: one that ran out is asked for again by the picture's id, and the picture is had."""
    import urllib.error
    from operations.integrations import save_config
    from apps.studio import photos as stock
    from tests.test_photos import KEY, Response, hit, jpeg
    draft, _ = made_deck(customer)
    candidate = next(c for c in pins_of(draft)['photos'][PHOTO]['candidates'] if c.get('asset_id') and not c.get('full'))
    clock(LONG_AFTER)
    paid_by_card(customer, 'premium')
    save_config('pixabay', {'pixabay_key': KEY, 'enabled': 'true'})
    fresh = f'https://pixabay.com/get/fresh{candidate["id"]}_1280.jpg'
    calls = []

    def network(request, timeout, handler):
        calls.append(request.full_url)
        if request.full_url.startswith(stock.API):
            return Response(json.dumps({'total': 1, 'totalHits': 1, 'hits': [hit(candidate['id'], url=fresh)]}).encode())
        if request.full_url == fresh:
            return Response(jpeg())
        raise urllib.error.HTTPError(request.full_url, 403, 'Forbidden', {}, None)
    stock_open = stock._open
    try:
        stock._open = network
        client = login_client(customer)
        draft.refresh_from_db()
        asked = client.post(f'/api/v1/generation/drafts/{draft.id}/photos', json.dumps(
            {'action': 'next', 'version': draft.version, 'section_id': PHOTO, 'asset_id': candidate['asset_id']}), content_type='application/json')
        assert asked.status_code == 202, asked.content
        state = client.get(f'/api/v1/generation/drafts/{draft.id}/photos/{asked.json()["task_id"]}').json()
    finally:
        stock._open = stock_open
    assert state['status'] == 'done', state
    assert calls[0] == candidate['url'], 'the link it was found with first'
    assert f'id={candidate["id"]}' in calls[1] and calls[2] == fresh
    worn = FileAsset.objects.get(pk=pins_of(draft)['photos'][PHOTO]['asset_id'])
    assert worn.metadata['id'] == candidate['id'] and keeping.is_kept(worn.expires_at)


@pytest.mark.django_db
def test_a_kept_source_is_held_for_changes_but_never_downloaded_after_its_day(customer, clock):  # noqa: F811
    source = upload(customer, 'tides.pdf')
    draft, _ = document(customer, 'Tides', source_ids=[str(source.id)])
    client = login_client(customer)
    assert client.get(f'/api/v1/files/{source.id}/download').status_code == 200, 'its own day, as any upload'
    clock(DAY)
    client = login_client(customer)
    refused = client.get(f'/api/v1/files/{source.id}/download')
    assert refused.status_code == 410 and refused.json()['error']['code'] == 'file_expired'
    assert client.get(f'/api/v1/files/{source.id}/preview').status_code == 410
    assert there(source) and client.get(f'/api/v1/files/{source.id}').json()['expires_at'] is None, 'still kept for a change'


# ---------------------------------------------------------------- after the second review


def branded(account, source, mark, origin='web'):
    """A kept AI PDF made from a source, with a logo."""
    draft = create_draft(account, {'feature_id': DOCUMENT, 'title': 'Tides', 'source_text': 'The moon pulls the sea twice a day.',
                                   'source_ids': [str(source.id)],
                                   'options': {'branding': {'name': 'Harbour School', 'accent': '#285cff', 'logo_asset_id': str(mark.id)}}})
    job, _ = submit_job(account, generation_quote(account, draft.id, draft.version).id, f'branded-{draft.id}', origin=origin)
    made = execute_job(job.id)
    assert made.status == 'succeeded', made.error_code
    draft.refresh_from_db()
    return draft, made


def task_screen(account, job):
    """The task's screen in the chat, opened from /myfiles as a customer opens it: (the chat, the screen's message)."""
    listed = dispatch_local(account, text='/myfiles')
    token = next(button['callback_data'] for message in listed['messages'] for row in message['buttons'] for button in row
                 if BotCallback.objects.filter(pk=button['callback_data'], action='job', payload__job_id=str(job.id)).exists())
    chat = dispatch_local(account, callback_data=token)
    return chat, next(message for message in reversed(chat['messages']) if message['direction'] == 'outbound' and str(job.id)[:8] in message['text'])


def asked_on_the_web(client, draft_id, key):
    """A change asked, quoted and made as JobDetail asks it: the job."""
    asked = client.post('/api/v1/generation/drafts', json.dumps({'prompt': CHANGE, 'options': {'revise_draft_id': str(draft_id)}}),
                        content_type='application/json')
    assert asked.status_code == 201, asked.content
    priced = client.post(f'/api/v1/generation/drafts/{asked.json()["id"]}/quote', json.dumps({'version': asked.json()['version']}),
                         content_type='application/json')
    assert priced.status_code == 201, priced.content
    sent = client.post('/api/v1/jobs', json.dumps({'quote_id': priced.json()['id']}), content_type='application/json', headers={'Idempotency-Key': key})
    assert sent.status_code == 201 and sent.json()['status'] == 'succeeded', sent.content
    return Job.objects.get(pk=sent.json()['id'])


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
@pytest.mark.parametrize('deleted', ['source', 'logo'])
def test_a_kept_document_whose_source_or_logo_was_deleted_still_takes_a_change(chatting, clock, deleted):  # noqa: F811
    """The customer deleted the file (DELETE /files/{id}): the change goes on without it, from what the draft holds."""
    source, mark = upload(chatting, 'tides.pdf'), logo(chatting)
    draft, made = branded(chatting, source, mark, origin='bot')
    chat = in_chat(chatting, made)
    excerpts = unpack(draft.encrypted_data)['excerpts']
    assert excerpts
    removed, left = (source, mark) if deleted == 'source' else (mark, source)
    client = login_client(chatting)
    assert client.delete(f'/api/v1/files/{removed.id}').status_code == 200
    clock(DAY)

    # In the chat, from the button under the file.
    asked = tap(chatting, chat, 'Make changes')
    assert 'What should change?' in body(asked), body(asked)[-400:]
    review = dispatch_local(chatting, text=CHANGE)
    assert CHANGE in body(review), body(review)[-400:]
    assert ('logo is no longer stored' in body(review)) == (deleted == 'logo'), body(review)[-600:]
    before = set(Job.objects.filter(account=chatting).values_list('pk', flat=True))
    tap(chatting, review, 'Generate')
    job = Job.objects.filter(account=chatting).exclude(pk__in=before).get()
    assert job.status == 'succeeded', job.error_code
    assert job.input_ids == [str(left.id)]
    assert unpack(draft_of(job).encrypted_data)['excerpts'] == excerpts, 'what was read from the source stays'
    assert ('logo_left_out' in job.warnings) == (deleted == 'logo'), job.warnings

    # On the web, as the task's page asks it.
    client = login_client(chatting)
    job = asked_on_the_web(client, draft.id, f'web-change-{deleted}')
    assert job.input_ids == [str(left.id)]
    assert ('logo_left_out' in job.warnings) == (deleted == 'logo'), job.warnings

    # Review draft: the kept draft saved as the web saves it, its sources as it lists them, and generated.
    opened = client.get(f'/api/v1/generation/drafts/{draft.id}').json()
    fields = {key: opened[key] for key in ('title', 'prompt', 'source_text', 'source_ids')}
    fields['options'] = {key: value for key, value in opened['options'].items() if value != ''}
    saved = client.patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': opened['version'], **fields}),
                         content_type='application/json')
    assert saved.status_code == 200, saved.content
    assert saved.json()['excerpts'] == excerpts
    priced = client.post(f'/api/v1/generation/drafts/{draft.id}/quote', json.dumps({'version': saved.json()['version']}),
                         content_type='application/json')
    assert priced.status_code == 201, priced.content
    assert priced.json()['input_fingerprints'] == [{'id': str(left.id), 'sha256': FileAsset.objects.get(pk=left.pk).sha256}]
    again = client.post('/api/v1/jobs', json.dumps({'quote_id': priced.json()['id']}), content_type='application/json',
                        headers={'Idempotency-Key': f'review-draft-{deleted}'})
    assert again.status_code == 201 and again.json()['status'] == 'succeeded', again.content


@pytest.mark.django_db
def test_a_kept_upload_past_its_day_is_held_for_changes_and_served_by_no_path(customer, clock):  # noqa: F811
    """No file tool, editor, download, preview or send has it after its 24 hours; a change of its document still reads it."""
    from apps.core.errors import DomainError
    from apps.core.services import create_quote
    source = upload(customer, 'tides.pdf')
    rotated = execute_job(submit_job(customer, create_quote(customer, 'pdf.rotate', [str(source.id)], {}).id, 'rotate-first')[0].id)
    result = rotated.artifacts.get()
    draft, _ = document(customer, 'Tides', source_ids=[str(source.id), str(result.file_id)])
    client = login_client(customer)
    assert client.get(f'/api/v1/artifacts/{result.id}/download').status_code == 200, 'its own day, as any result'

    clock(DAY)
    client = login_client(customer)
    # (a) A file tool, quoted in the domain and on the API, and the editor.
    with pytest.raises(DomainError) as refused:
        create_quote(customer, 'pdf.rotate', [str(source.id)], {})
    assert (refused.value.code, refused.value.status) == ('file_expired', 410)
    asked = client.post('/api/v1/quotes', json.dumps({'feature_id': 'pdf.rotate', 'input_ids': [str(result.file_id)], 'parameters': {}}),
                        content_type='application/json')
    assert asked.status_code == 410 and asked.json()['error']['code'] == 'file_expired'
    opened = client.post('/api/v1/editor/documents', json.dumps({'file_id': str(source.id)}), content_type='application/json')
    assert opened.status_code == 410, opened.content
    # (b) A result used as a source: neither its download nor its file's, and no preview offered.
    assert client.get(f'/api/v1/artifacts/{result.id}/download').status_code == 410
    assert client.get(f'/api/v1/files/{result.file_id}/download').status_code == 410
    assert client.get(f'/api/v1/artifacts/{result.id}/preview').status_code == 410
    assert client.get(f'/api/v1/jobs/{rotated.id}').json()['artifacts'][0]['preview_url'] is None
    assert client.get(f'/api/v1/files/{source.id}').json()['preview_url'] is None
    assert there(source) and there(FileAsset.objects.get(pk=result.file_id))

    # (d) A change 400 days later still reads both.
    clock(LONG_AFTER)
    paid_by_card(customer, 'premium')
    change = asked_on_the_web(login_client(customer), draft.id, 'change-much-later')
    assert change.input_ids == [str(source.id), str(result.file_id)]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_the_bot_sends_no_kept_upload_past_its_day(chatting, clock):  # noqa: F811
    """A result kept as a source is not sent to the chat again once its day is over: its task offers no download."""
    from apps.core.services import create_quote
    source = upload(chatting, 'tides.pdf')
    rotated = execute_job(submit_job(chatting, create_quote(chatting, 'pdf.rotate', [str(source.id)], {}).id, 'rotate-in-chat', origin='bot')[0].id)
    result = rotated.artifacts.get()
    document(chatting, 'Tides', source_ids=[str(result.file_id)])
    clock(DAY)
    delivery = BotDelivery.objects.create(account=chatting, artifact=result, idempotency_key='late-resend')
    delivered = deliver_local(chatting, delivery)
    assert (delivered.status, delivered.error_code) == ('failed', 'file_expired')
    from telegram.delivery import editable_pdf
    from telegram.ux_copy import UX
    _, screen = task_screen(chatting, rotated)
    assert UX['en']['download'] not in [button['label'] for row in screen['buttons'] for button in row]
    # Still stored, for the document's changes: never "no longer stored".
    assert UX['en']['result_held'] in screen['text'] and UX['en']['result_expired'] not in screen['text'], screen['text']
    assert not editable_pdf(FileAsset.objects.get(pk=result.file_id)), 'no ✏️ Edit, nor /editor, offers it'


@pytest.mark.django_db
def test_an_account_that_asked_to_be_deleted_never_has_a_draft_kept(customer, clock):  # noqa: F811
    old, made = document(customer, 'Tides')
    # As the platform left it before: on its result's day, not kept yet.
    GenerationDraft.objects.filter(pk=old.pk).update(expires_at=made.artifacts.get().file.expires_at)
    customer.deletion_requested_at = timezone.now()
    customer.save(update_fields=['deletion_requested_at'])

    clock(1)
    assert not GenerationDraft.objects.filter(pk=old.pk).exists(), 'the backfill deletes it, never keeps it'
    # A job settling after the account asked to be deleted keeps nothing (the next cleanup deletes its draft).
    settling = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Waves', 'source_text': 'Wind makes waves.'})
    keeping.keep(settling)
    assert not keeping.is_kept(GenerationDraft.objects.get(pk=settling.pk).expires_at)


@pytest.mark.django_db
def test_the_backfill_costs_nothing_once_it_has_done_its_job(customer, clock):  # noqa: F811
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    tables = (Job._meta.db_table, GenerationDraft._meta.db_table)
    clock(1)
    # Within a day of its first clean pass a worker from before may still settle a job: it goes on looking.
    with CaptureQueriesContext(connection) as within:
        keeping.backfill()
    assert any(GenerationDraft._meta.db_table in query['sql'] for query in within.captured_queries)
    clock(1 + DAY)
    with CaptureQueriesContext(connection) as later:
        assert keeping.backfill() == 0
    assert not [query['sql'] for query in later.captured_queries if any(table in query['sql'] for table in tables)]
    clock(LONG_AFTER)
    with CaptureQueriesContext(connection) as long_after:
        keeping.backfill()
    assert len(long_after.captured_queries) <= 1


@pytest.mark.django_db
def test_the_backstop_reads_kept_files_a_few_at_a_time(customer, stock_photos, clock, orphans_due, monkeypatch):  # noqa: F811
    monkeypatch.setattr(keeping, 'ORPHANS_BATCH', 2)
    source = upload(customer, 'harbour-notes.pdf')
    first, _ = made_deck(customer, sources=[source])
    second, _ = made_deck(customer, sources=[source])
    pictures, others = deck_files(first), deck_files(second)
    assert len(pictures) > 2
    GenerationDraft.objects.filter(pk=first.pk).delete()
    clock(DAY)
    assert all(gone(asset) for asset in pictures)
    assert all(there(asset) for asset in others) and FileAsset.objects.get(pk=source.pk).metadata['kept_by'] == [str(second.pk)]


@pytest.mark.django_db
def test_a_delete_that_rolls_back_leaves_every_file_in_place(customer, stock_photos, clock, django_capture_on_commit_callbacks):  # noqa: F811
    from django.db import transaction
    mark = logo(customer)
    draft, _ = made_deck(customer, mark=mark)
    pictures = deck_files(draft)
    assert pictures
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            keeping.delete(GenerationDraft.objects.get(pk=draft.pk))
            raise RuntimeError('the request failed after the delete')
    assert GenerationDraft.objects.filter(pk=draft.pk).exists()
    assert all(there(asset) for asset in pictures) and there(mark)
    # Committed, its rows go with it and their bytes right after.
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        keeping.delete(GenerationDraft.objects.get(pk=draft.pk))
    assert len(callbacks) == 1
    assert not FileAsset.objects.filter(pk__in=[asset.pk for asset in pictures]).exists()
    assert not any(storage.exists(asset.object_key) for asset in pictures)
    clock(DAY)
    assert gone(mark)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_make_changes_shown_again_and_again_is_one_button(chatting, clock):  # noqa: F811
    stage_pdf(chatting)
    material = ' '.join(['tide'] * 390)
    delivered_now = tap(chatting, describe(chatting, f'A 1 page guide to tide tables.\n\n{material}'), 'Generate')
    draft = draft_of(Job.objects.get(account=chatting, feature_id=DOCUMENT))
    buttons = BotCallback.objects.filter(account=chatting, action='ai_revise', payload={'draft_id': str(draft.pk)})
    assert buttons.count() == 1
    tap(chatting, delivered_now, 'Make changes')
    first_review = dispatch_local(chatting, text=CHANGE)
    tap(chatting, first_review, 'Make changes')
    second_review = dispatch_local(chatting, text='Make it shorter.')
    assert 'Make it shorter.' in body(second_review)
    assert buttons.count() == 1, 'the reword button of each review is the one under the file'
    assert keeping.is_kept(buttons.get().expires_at)
    # Every one of them still works: the oldest review's too.
    asked = tap(chatting, first_review, 'Make changes')
    assert 'What should change?' in body(asked), body(asked)[-300:]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_an_old_ai_task_offers_make_changes_not_the_original_file(chatting, clock):  # noqa: F811
    from telegram.ux_copy import UX
    stage_pdf(chatting)
    material = ' '.join(['tide'] * 390)
    tap(chatting, describe(chatting, f'A 1 page guide to tide tables.\n\n{material}'), 'Generate')
    made = Job.objects.get(account=chatting, feature_id=DOCUMENT)
    draft = draft_of(made)
    clock(DAY)
    chat, screen = task_screen(chatting, made)
    assert UX['en']['result_expired'] not in screen['text'] and UX['en']['ai_result_kept'] in screen['text'], screen['text']
    row = BotCallback.objects.get(account=chatting, action='ai_revise', payload={'draft_id': str(draft.pk)})
    assert row.token in [button['callback_data'] for button in screen['buttons'][0]], 'the button under the file, reused'
    asked = dispatch_local(chatting, callback_data=row.token)
    assert 'What should change?' in body(asked)
    assert all(UX[locale]['ai_result_kept'] for locale in ('en', 'uz', 'ru'))


# ---------------------------------------------------------------- after the third review


HELD = {
    'en': 'This file is kept only for changing the AI document made from it, so it can no longer be opened here. Send it again to edit it.',
    'uz': 'Bu fayl faqat undan yaratilgan AI hujjatni o‘zgartirish uchun saqlanadi, shuning uchun uni bu yerda endi ochib bo‘lmaydi. '
          'Tahrirlash uchun uni qayta yuboring.',
    'ru': 'Этот файл хранится только для изменения сделанного по нему ИИ-документа, поэтому открыть его здесь больше нельзя. '
          'Чтобы отредактировать, пришлите его снова.',
}
# The chat's own words for it: the chat sends files and opens none, so it says the file is sent there no more.
CHAT_HELD = {
    'en': '⌛ This file is kept only for changing the AI document made from it, so it can no longer be sent here. Send the file again to use it.',
    'uz': '⌛ Bu fayl faqat undan yaratilgan AI hujjatni o‘zgartirish uchun saqlanadi, shuning uchun uni bu yerga endi yuborib bo‘lmaydi. '
          'Undan foydalanish uchun faylni qayta yuboring.',
    'ru': '⌛ Этот файл хранится только для изменения сделанного по нему ИИ-документа, поэтому прислать его сюда больше нельзя. '
          'Чтобы воспользоваться им, отправьте файл снова.',
}


def refused_as(answer):
    error = answer.json()['error']
    return answer.status_code, error['code'], error['message_params'].get('reason'), error['message']


@pytest.mark.django_db
def test_a_file_held_for_a_document_is_said_to_be_kept_never_deleted(customer, clock):  # noqa: F811
    """Every refusal of a held upload past its day says it is kept for the document, in each language; one that ran out still says so."""
    from apps.core.errors import DomainError, error_data
    from telegram.errors import bot_error
    from telegram.ux_copy import UX
    source = upload(customer, 'tides.pdf')
    client = login_client(customer)
    opened = client.post('/api/v1/editor/documents', json.dumps({'file_id': str(source.id)}), content_type='application/json')
    assert opened.status_code == 201, opened.content
    document(customer, 'Tides', source_ids=[str(source.id)])
    lost = upload(customer, 'lost.pdf')
    # Its day over, before the cleanup has run: once it has, the editor's draft on it is gone, as any file's is.
    clock(DAY, clean=False)
    client = login_client(customer)
    said = (410, 'file_expired', keeping.KEPT_FOR_DOCUMENT, HELD['en'])
    # The editor, by the file (the bot's ✏️ Edit, /editor, Edit under a result) and by its draft.
    assert refused_as(client.post('/api/v1/editor/documents', json.dumps({'file_id': str(source.id)}), content_type='application/json')) == said
    assert refused_as(client.get(f'/api/v1/editor/documents/{opened.json()["id"]}')) == said
    # A download, a preview, a file tool.
    assert refused_as(client.get(f'/api/v1/files/{source.id}/download')) == said
    assert refused_as(client.get(f'/api/v1/files/{source.id}/preview')) == said
    assert refused_as(client.post('/api/v1/quotes', json.dumps({'feature_id': 'pdf.rotate', 'input_ids': [str(source.id)], 'parameters': {}}),
                                  content_type='application/json')) == said
    assert there(source)
    # One no draft kept ran out, and says that.
    ran_out = client.post('/api/v1/editor/documents', json.dumps({'file_id': str(lost.id)}), content_type='application/json')
    assert refused_as(ran_out) == (410, 'file_expired', None, error_data(DomainError('file_expired'))['message'])
    held = DomainError('file_expired', 410, {'reason': keeping.KEPT_FOR_DOCUMENT})
    for locale in ('en', 'uz', 'ru'):
        assert error_data(held, locale)['message'] == HELD[locale]
        assert bot_error(held, locale) == UX[locale]['result_held'] == CHAT_HELD[locale]
        assert bot_error(DomainError('file_expired', 410), locale) != bot_error(held, locale)
    cleanup_expired()
    assert client.get(f'/api/v1/editor/documents/{opened.json()["id"]}').status_code == 404, 'its marks went with its day'
    assert there(source)


@pytest.mark.django_db
def test_a_held_file_shows_when_it_stops_being_opened_and_is_expired_after(customer, clock):  # noqa: F811
    """Its editor row and its task's result name the end of its own day, as any file's do, and are expired after it: the
    editor's list lets it go, its draft can still be removed until the cleanup takes it with that day, and the file is
    still kept for the document's changes."""
    from django.utils.dateparse import parse_datetime
    from apps.core.services import create_quote
    from apps.studio.models import EditorDocument
    source = upload(customer, 'tides.pdf')
    rotated = execute_job(submit_job(customer, create_quote(customer, 'pdf.rotate', [str(source.id)], {}).id, 'rotate-shown')[0].id)
    result = rotated.artifacts.get()
    client = login_client(customer)
    opened = client.post('/api/v1/editor/documents', json.dumps({'file_id': str(source.id)}), content_type='application/json').json()
    _, made = document(customer, 'Tides', source_ids=[str(source.id), str(result.file_id)])
    # Their own day runs to the end of the document made from them, as it would for any file a task used.
    source_ends = result_ends = made.artifacts.get().file.expires_at

    def at(value, moment):
        return value is not None and abs(parse_datetime(value) - moment) < timedelta(seconds=1)

    def job_result(client):
        return client.get(f'/api/v1/jobs/{rotated.id}').json()['artifacts'][0]

    row = next(item for item in client.get('/api/v1/editor/documents').json()['results'] if item['id'] == opened['id'])
    assert row['file']['state'] == 'ready' and at(row['file']['expires_at'], source_ends), row['file']
    assert job_result(client)['state'] == 'ready' and at(job_result(client)['expires_at'], result_ends)
    assert client.get(f'/api/v1/files/{source.id}').json()['expires_at'] is None, 'as a source it is kept: Review draft reads this'

    # Its day over, before the cleanup has run (which deletes the editor's draft on it, as on any file past its day).
    clock(DAY, clean=False)
    client = login_client(customer)
    assert opened['id'] not in [item['id'] for item in client.get('/api/v1/editor/documents').json()['results']]
    assert job_result(client)['state'] == 'expired' and at(job_result(client)['expires_at'], result_ends)
    listed = next(item for item in client.get('/api/v1/jobs').json()['results'] if item['id'] == str(rotated.id))
    assert [artifact['state'] for artifact in listed['artifacts']] == ['expired']
    assert client.delete(f'/api/v1/editor/documents/{opened["id"]}').json() == {'deleted': True}
    assert not EditorDocument.objects.filter(pk=opened['id']).exists()
    kept = client.get(f'/api/v1/files/{source.id}').json()
    assert kept['state'] == 'ready' and kept['expires_at'] is None
    assert there(source) and there(FileAsset.objects.get(pk=result.file_id))


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_document_never_sent_to_the_chat_never_says_its_copy_is_there(chatting, clock):  # noqa: F811
    """Made on the web, nothing of it went to the chat: its task there says the file is gone and the document can be changed."""
    from telegram.ux_copy import UX
    _, made = document(chatting, 'Tides')
    assert made.origin_channel == 'web' and not BotDelivery.objects.filter(artifact__job=made).exists()
    clock(DAY)
    chat, screen = task_screen(chatting, made)
    assert UX['en']['ai_result_kept_unsent'] in screen['text'] and UX['en']['ai_result_kept'] not in screen['text'], screen['text']
    asked = tap(chatting, chat, 'Make changes')
    assert 'What should change?' in body(asked), body(asked)[-300:]
    assert all(UX[locale]['ai_result_kept_unsent'] for locale in ('en', 'uz', 'ru'))


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_document_sent_to_the_chat_as_a_link_never_says_its_copy_is_there(chatting, clock):  # noqa: F811
    """A file over Telegram's 50 MB goes to the chat as a link to the web app: no copy of it is in the chat."""
    from telegram.ux_copy import UX
    stage_pdf(chatting)
    material = ' '.join(['tide'] * 390)
    tap(chatting, describe(chatting, f'A 1 page guide to tide tables.\n\n{material}'), 'Generate')
    made = Job.objects.get(account=chatting, feature_id=DOCUMENT)
    assert BotDelivery.objects.filter(artifact__job=made, status='delivered').exists()
    FileAsset.objects.filter(pk=made.artifacts.get().file_id).update(size_bytes=60 * 1024 * 1024)
    clock(DAY)
    _, screen = task_screen(chatting, made)
    assert UX['en']['ai_result_kept_unsent'] in screen['text'] and UX['en']['ai_result_kept'] not in screen['text'], screen['text']


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_kept_decks_send_a_day_later_offers_make_changes(chatting, stock_photos, clock):  # noqa: F811
    """A deck sent from its editor: the deck is kept, so its task says it can still be changed, never to send the original file."""
    from telegram.ux_copy import UX
    from tests.test_render_export import send
    draft, _ = made_deck(chatting, origin='bot')
    sent = send(chatting, draft, origin='bot')
    assert sent.status == 'succeeded', sent.error_code
    in_chat(chatting, sent)
    clock(DAY)
    chat, screen = task_screen(chatting, sent)
    assert UX['en']['ai_result_kept'] in screen['text'] and UX['en']['result_expired'] not in screen['text'], screen['text']
    asked = tap(chatting, chat, 'Make changes')
    assert 'What should change?' in body(asked), body(asked)[-300:]


def test_a_cv_without_its_photo_says_the_photo_is_no_longer_stored_in_every_language():
    """A kept CV keeps its photo: one found gone was deleted, or is a draft's from before, so no language says it ran out."""
    from telegram.ux_copy import UX
    said = {locale: UX[locale]['cv_photo_gone'] for locale in ('en', 'uz', 'ru')}
    assert 'no longer stored' in said['en'] and 'endi saqlanmagan' in said['uz'] and 'больше не хранится' in said['ru'], said
    assert not any(word in said[locale] for locale in said for word in ('expired', 'muddat', 'Срок', 'истёк')), said


# ---------------------------------------------------------------- after the fourth review


@pytest.mark.django_db
def test_a_held_upload_past_its_day_is_never_put_on_a_slide(customer, stock_photos, clock):  # noqa: F811
    """The deck editor's own photo is an upload of the customer's: never one held for a document past its day, whose copy
    the kept deck would then wear, and serve, for good."""
    from types import SimpleNamespace
    from apps.core.errors import DomainError
    from apps.studio import deck_photos
    mark = logo(customer)
    draft, _ = made_deck(customer, mark=mark)
    worn = pins_of(draft)['photos'][PHOTO]['asset_id']
    pictures = FileAsset.objects.filter(account=customer, metadata__kind='deck_photo').count()
    clock(DAY)
    client = login_client(customer)
    draft.refresh_from_db()
    asked = client.post(f'/api/v1/generation/drafts/{draft.id}/photos', json.dumps(
        {'action': 'upload', 'version': draft.version, 'section_id': PHOTO, 'asset_id': str(mark.id)}), content_type='application/json')
    assert refused_as(asked) == (410, 'file_expired', keeping.KEPT_FOR_DOCUMENT, HELD['en'])
    assert pins_of(draft)['photos'][PHOTO]['asset_id'] == worn
    assert FileAsset.objects.filter(account=customer, metadata__kind='deck_photo').count() == pictures
    # Nor by a task asked within its day that runs after it.
    draft.refresh_from_db()
    with pytest.raises(DomainError) as refused:
        deck_photos._upload(SimpleNamespace(account=customer), draft, unpack(draft.encrypted_data),
                            {'section_id': PHOTO, 'asset_id': str(mark.id), 'version': draft.version})
    assert refused.value.code == 'picture_unavailable'
    assert FileAsset.objects.filter(account=customer, metadata__kind='deck_photo').count() == pictures
    assert there(mark), 'still held for the deck’s changes'


@pytest.mark.django_db
def test_a_file_made_into_an_ai_document_is_served_as_long_as_any_file_used_then(customer, clock):  # noqa: F811
    """A held upload's own day runs as any file's does: to the end of the latest task it went into, the AI document's
    among them, never cut back to 24 hours from its upload. Past it, a change of the document reads it and no more."""
    from apps.core.services import create_quote
    held, plain = upload(customer, 'held.pdf'), upload(customer, 'plain.pdf')
    clock(20)
    for asset in (held, plain):
        rotated = execute_job(submit_job(customer, create_quote(customer, 'pdf.rotate', [str(asset.id)], {}).id, f'rotate-{asset.id}')[0].id)
        assert rotated.status == 'succeeded', rotated.error_code
    clock(21)
    draft, made = document(customer, 'Tides', source_ids=[str(held.id)])
    ends = made.artifacts.get().file.expires_at
    assert keeping.is_kept(FileAsset.objects.get(pk=held.pk).expires_at)
    assert keeping.served_until(FileAsset.objects.get(pk=held.pk)) == ends, 'its day runs to the end of the document made from it'

    clock(30)
    client = login_client(customer)
    for asset in (held, plain):
        quoted = client.post('/api/v1/quotes', json.dumps({'feature_id': 'pdf.rotate', 'input_ids': [str(asset.id)], 'parameters': {}}),
                             content_type='application/json')
        assert quoted.status_code == 201, (asset.name, quoted.content)
        assert client.get(f'/api/v1/files/{asset.id}/download').status_code == 200, asset.name
    # Used again within its day, by a file tool: its day runs to the end of that task, as the plain file's would.
    again = execute_job(submit_job(customer, create_quote(customer, 'pdf.rotate', [str(held.id)], {}).id, 'rotate-held-again')[0].id)
    assert again.status == 'succeeded', again.error_code
    ends = again.artifacts.get().file.expires_at
    assert keeping.served_until(FileAsset.objects.get(pk=held.pk)) == ends and keeping.is_kept(FileAsset.objects.get(pk=held.pk).expires_at)

    clock(53)
    assert login_client(customer).get(f'/api/v1/files/{held.id}/download').status_code == 200
    clock(55)
    client = login_client(customer)
    assert refused_as(client.get(f'/api/v1/files/{held.id}/download')) == (410, 'file_expired', keeping.KEPT_FOR_DOCUMENT, HELD['en'])
    # Past its day, a change of the document reads it, and serves it no more for that.
    change = asked_on_the_web(client, draft.id, 'change-after-its-day')
    assert change.input_ids == [str(held.id)]
    assert refused_as(login_client(customer).get(f'/api/v1/files/{held.id}/download'))[0] == 410
    assert there(held)


@pytest.mark.django_db
def test_a_held_file_sent_again_from_its_editor_is_served_a_day_from_then(customer, clock):  # noqa: F811
    """The PDF editor's send, and the same marks sent again, move a held upload's day as they move any file's."""
    from tests.test_editor_documents import NOTE, run, save, send as quoted_send
    source = upload(customer, 'tides.pdf')
    client = login_client(customer)
    opened = client.post('/api/v1/editor/documents', json.dumps({'file_id': str(source.id)}), content_type='application/json')
    assert opened.status_code == 201, opened.content
    url = f'/api/v1/editor/documents/{opened.json()["id"]}'
    document(customer, 'Tides', source_ids=[str(source.id)])
    clock(20)
    client = login_client(customer)
    assert save(client, url, 1, [NOTE]).status_code == 200
    first = run(client, quoted_send(client, url, 2), 'editor-send-held')
    assert first.status == 'succeeded', first.error_code
    assert keeping.served_until(FileAsset.objects.get(pk=source.pk)) == first.artifacts.get().file.expires_at
    clock(22)
    client = login_client(customer)
    again = client.post('/api/v1/jobs', {'quote_id': quoted_send(client, url, 2).json()['id']}, content_type='application/json',
                        HTTP_IDEMPOTENCY_KEY='editor-send-held-again')
    assert again.status_code == 200 and again.json()['id'] == str(first.pk), 'the same marks: the file made from them, sent again'
    served = keeping.served_until(FileAsset.objects.get(pk=source.pk))
    assert served == FileAsset.objects.get(pk=first.artifacts.get().file_id).expires_at and served > timezone.now() + timedelta(hours=23)
    assert keeping.is_kept(FileAsset.objects.get(pk=source.pk).expires_at)
    clock(45)
    assert login_client(customer).get(f'/api/v1/files/{source.id}/download').status_code == 200
    clock(47)
    assert refused_as(login_client(customer).get(f'/api/v1/files/{source.id}/download'))[2] == keeping.KEPT_FOR_DOCUMENT


@pytest.mark.django_db
def test_a_kept_decks_send_moves_its_sources_day_as_it_moves_any(customer, stock_photos, clock):  # noqa: F811
    """A deck sent from its editor carries the files it stands on to the end of the send's day, unless their own is over."""
    from tests.test_render_export import send
    source = upload(customer, 'harbour-notes.pdf')
    draft, _ = made_deck(customer, sources=[source])
    clock(20)
    sent = send(customer, draft)
    assert sent.status == 'succeeded', sent.error_code
    assert keeping.served_until(FileAsset.objects.get(pk=source.pk)) == sent.artifacts.get().file.expires_at
    clock(50)
    from tests.test_deck_pins import edit_section
    assert edit_section(customer, draft, CARDS, heading='Reworded after its day')
    late = send(customer, GenerationDraft.objects.get(pk=draft.pk))
    assert late.status == 'succeeded', late.error_code
    assert keeping.served_until(FileAsset.objects.get(pk=source.pk)) == sent.artifacts.get().file.expires_at, 'past its day it stays past it'


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_document_never_sent_to_the_chat_asked_for_as_a_pdf_names_no_copy_there(chatting, clock):  # noqa: F811
    """Make changes on its task, then the format alone: the file is gone, and no copy of it is said to be in the chat."""
    from telegram.ux_copy import UX
    from tests.test_bot_edit_review import screen
    _, made = document(chatting, 'Tides')
    assert not BotDelivery.objects.filter(artifact__job=made).exists()
    clock(DAY)
    chat, _ = task_screen(chatting, made)
    tap(chatting, chat, 'Make changes')
    words, labels = screen(dispatch_local(chatting, text='pdf shaklida yubor'))
    assert words == UX['en']['ai_file_gone_unsent'], words
    assert '✏️ Make changes' in labels, labels


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_deck_never_sent_to_the_chat_asked_for_as_a_pdf_is_sent_to_its_editor(chatting, stock_photos, clock, converter):  # noqa: F811
    """No .pptx of it is in the chat to convert: the deck editor sends it as a PDF instead."""
    from telegram.ux_copy import UX
    from tests.test_bot_edit_review import screen
    draft, made = made_deck(chatting)
    assert not BotDelivery.objects.filter(artifact__job=made).exists()
    clock(DAY)
    chat, _ = task_screen(chatting, made)
    tap(chatting, chat, 'Make changes')
    said = dispatch_local(chatting, text='pdf shaklida yubor')
    words, labels = screen(said)
    assert words == UX['en']['ai_deck_gone_unsent'], words
    assert 'PowerPoint → PDF' not in labels and UX['en']['edit'] in labels, labels
    opener = next(button for message in said['messages'] for row in message['buttons'] for button in row if button['label'] == UX['en']['edit'])
    assert f'editor/deck/{draft.id}' in json.dumps(opener), opener


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_a_deck_never_sent_to_the_chat_without_its_editor_is_offered_a_change(chatting, stock_photos, clock, converter, monkeypatch):  # noqa: F811
    from telegram.ux_copy import UX
    from tests.test_bot_edit_review import screen
    monkeypatch.setenv('EDITOR_FLAG_DECK_EDITOR', '0')
    _, made = made_deck(chatting)
    clock(DAY)
    chat, _ = task_screen(chatting, made)
    tap(chatting, chat, 'Make changes')
    words, labels = screen(dispatch_local(chatting, text='pdf shaklida yubor'))
    assert words == UX['en']['ai_file_gone_unsent'], words
    assert 'PowerPoint → PDF' not in labels and '✏️ Make changes' in labels, labels


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures('bot_verification_disabled')
def test_an_edited_deck_never_sent_to_the_chat_names_no_older_file_there(chatting, stock_photos, clock, converter):  # noqa: F811
    from telegram.ux_copy import UX
    from tests.test_bot_edit_review import screen
    from tests.test_render_export import send
    draft, _ = made_deck(chatting)
    sent = send(chatting, draft, origin='web')
    assert sent.status == 'succeeded' and not BotDelivery.objects.filter(artifact__job__in=[sent]).exists()
    clock(DAY)
    chat, _ = task_screen(chatting, sent)
    tap(chatting, chat, 'Make changes')
    words, _ = screen(dispatch_local(chatting, text='pdf shaklida yubor'))
    assert words == UX['en']['ai_edited_not_kept_unsent'].format(format='PDF'), words


def test_what_names_no_copy_in_the_chat_is_said_in_every_language():
    import re
    from telegram.ux_copy import UX
    for key in ('ai_file_gone_unsent', 'ai_deck_gone_unsent', 'ai_edited_not_kept_unsent'):
        said = [UX[locale][key] for locale in ('en', 'uz', 'ru')]
        assert all(said) and not any('chat' in line or 'чат' in line for line in said), said
        assert not re.search('[А-Яа-яЁё]', UX['uz'][key]) and "'" not in UX['uz'][key], UX['uz'][key]
    assert all('{format}' in UX[locale]['ai_edited_not_kept_unsent'] for locale in ('en', 'uz', 'ru'))


# ---------------------------------------------------------------- after the fifth review


@pytest.mark.django_db
def test_editor_marks_and_cv_reads_on_a_kept_upload_go_when_its_day_ends(customer, clock):  # noqa: F811
    """The PDF editor's draft on a file later made into an AI document, and what a CV's reader took from it, go when the
    file's own day ends, as they go with any file: nothing opens them after it, and a change of the document never reads them."""
    from apps.studio.models import CvSourceRead, EditorDocument
    from tests.test_editor_documents import NOTE, save
    held, plain = upload(customer, 'held.pdf'), upload(customer, 'plain.pdf')
    client = login_client(customer)
    opened = {}
    for asset in (held, plain):
        answer = client.post('/api/v1/editor/documents', json.dumps({'file_id': str(asset.id)}), content_type='application/json')
        assert answer.status_code == 201, answer.content
        opened[asset.name] = answer.json()['id']
        assert save(client, f'/api/v1/editor/documents/{answer.json()["id"]}', 1, [NOTE]).status_code == 200
        CvSourceRead.objects.create(account=customer, asset=asset, status='done')
    draft, _ = document(customer, 'Tides', source_ids=[str(held.id)])
    clock(20)
    assert EditorDocument.objects.filter(pk=opened['held.pdf']).exists() and CvSourceRead.objects.filter(asset_id=held.pk).exists(), 'its own day'

    clock(DAY)
    for asset in (held, plain):
        assert not EditorDocument.objects.filter(pk=opened[asset.name]).exists(), asset.name
        assert not CvSourceRead.objects.filter(asset_id=asset.pk).exists(), asset.name
    assert there(held), 'still kept for the document'
    client = login_client(customer)
    assert client.get('/api/v1/editor/documents').json()['results'] == []
    # Asked after as a CV's file, it is read no more: the page forgets it, as it forgets a file that ran out.
    asked = client.get(f'/api/v1/studio/cv-reads?ids={held.id}')
    assert asked.status_code == 404, asked.content
    assert not CvSourceRead.objects.filter(asset_id=held.pk).exists()
    clock(LONG_AFTER)
    paid_by_card(customer, 'premium')
    assert asked_on_the_web(login_client(customer), draft.id, 'change-without-marks').input_ids == [str(held.id)]


@pytest.mark.django_db
def test_an_account_that_asked_to_be_deleted_loses_every_draft_at_the_next_cleanup(customer, stock_photos, clock):  # noqa: F811
    """DELETE /me is not one transaction, and the backfill stops once done: cut off after the ask, the account's drafts,
    kept or not, go with what they hold at the next cleanup however long after, its files with them."""
    from apps.core.models import Account
    source = upload(customer, 'harbour-notes.pdf')
    draft, _ = made_deck(customer, sources=[source])
    unsent = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Waves', 'source_text': 'Wind makes waves.'})
    pictures = deck_files(draft)
    assert pictures and keeping.is_kept(FileAsset.objects.get(pk=source.pk).expires_at)
    BotCallback.objects.create(token='leaving-change-button', account=customer, action='ai_revise',
                               payload={'draft_id': str(draft.pk)}, expires_at=keeping.KEPT_UNTIL)
    staying = Account.objects.create(display_name='Staying', plan='free')
    kept, _ = document(staying, 'Tides')
    keeping._note_backfill({'done': True, 'done_at': timezone.now().isoformat()})
    # As DELETE /me leaves an account it was cut off on: asked, and nothing else done.
    customer.deletion_requested_at = timezone.now()
    customer.save(update_fields=['deletion_requested_at'])

    clock(2)
    assert not GenerationDraft.objects.filter(account=customer).exists(), 'kept or not'
    assert not GenerationDraft.objects.filter(pk=unsent.pk).exists()
    assert not FileAsset.objects.filter(account=customer, expires_at__gte=keeping.KEPT_UNTIL).exists()
    assert gone(source) and all(gone(asset) for asset in pictures)
    assert not BotCallback.objects.filter(account=customer, action='ai_revise').exists()
    assert keeping.is_kept(GenerationDraft.objects.get(pk=kept.pk).expires_at), 'another account keeps its own'


@pytest.mark.django_db
def test_a_held_upload_past_its_day_goes_into_no_new_document(customer, stock_photos, clock):  # noqa: F811
    """A new document's source or logo, a new CV's photo or file, a draft given it on a save, a kept deck given it as a
    logo: each is refused as the file is everywhere past its day, kept for its own document."""
    from operations.integrations import save_config
    from apps.core.services import upload_file
    from apps.studio.domain import CV
    from telegram.generation import usable_portrait
    from tests.test_bot_cv import image
    from tests.test_cv_content import BRIEF
    source, mark = upload(customer, 'tides.pdf'), logo(customer)
    first, _ = branded(customer, source, mark)
    save_config('ai', {'mode': 'local_fixture'})
    photo = upload_file(customer, image())
    cv = create_draft(customer, {'feature_id': CV, 'prompt': BRIEF, 'options': {'portrait_asset_id': str(photo.id)}})
    assert execute_job(submit_job(customer, generation_quote(customer, cv.id, cv.version).id, 'cv-with-its-photo')[0].id).status == 'succeeded'
    deck, _ = made_deck(customer)
    clock(DAY)
    unsent = create_draft(customer, {'feature_id': DOCUMENT, 'title': 'Waves', 'source_text': 'Wind makes waves.'})
    paid_by_card(customer, 'premium')
    client = login_client(customer)
    said = (410, 'file_expired', keeping.KEPT_FOR_DOCUMENT, HELD['en'])

    def asked(payload):
        return client.post('/api/v1/generation/drafts', json.dumps(payload), content_type='application/json')

    def saved(draft, **fields):
        opened = client.get(f'/api/v1/generation/drafts/{draft.id}').json()
        return client.patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': opened['version'], **fields}),
                            content_type='application/json')

    brand = {'name': 'Harbour', 'accent': '#285cff', 'logo_asset_id': str(mark.id)}
    assert refused_as(asked({'feature_id': DOCUMENT, 'title': 'Another', 'source_text': 'Other notes.', 'source_ids': [str(source.id)]})) == said
    assert refused_as(asked({'feature_id': DOCUMENT, 'title': 'Another', 'source_text': 'Other notes.', 'options': {'branding': brand}})) == said
    assert refused_as(asked({'feature_id': SLIDES, 'title': 'Another', 'source_text': 'Other notes.', 'options': {'branding': brand}})) == said
    assert refused_as(asked({'feature_id': CV, 'prompt': BRIEF, 'options': {'portrait_asset_id': str(photo.id)}})) == said
    assert refused_as(asked({'feature_id': CV, 'prompt': '', 'source_ids': [str(source.id)], 'options': {'cv_source': 'file'}})) == said
    assert usable_portrait(customer, str(photo.id)) == '', 'the chat carries it to no new CV'
    assert refused_as(saved(unsent, source_ids=[str(source.id)])) == said
    opened = client.get(f'/api/v1/generation/drafts/{deck.id}').json()
    options = {key: value for key, value in opened['options'].items() if value != ''}
    assert refused_as(saved(deck, options={**options, 'branding': brand})) == said
    assert FileAsset.objects.get(pk=source.pk).metadata['kept_by'] == [str(first.pk)], 'held by its own document alone'
    assert FileAsset.objects.get(pk=mark.pk).metadata['kept_by'] == [str(first.pk)]
    from apps.studio.models import CvSourceRead
    assert not CvSourceRead.objects.filter(asset_id=source.pk).exists(), 'no read queued for it'


@pytest.mark.django_db
def test_a_held_upload_past_its_day_still_goes_into_its_own_documents_changes(customer, clock):  # noqa: F811
    """What the draft already names, or the document a change changes, is not a new input: a change, a change of that
    change, its wording saved again, Review draft's save of the document's own files and a CV's change keep working."""
    from operations.integrations import save_config
    from apps.core.services import upload_file
    from apps.studio.domain import CV
    from tests.test_bot_cv import image
    from tests.test_cv_content import BRIEF
    source, mark = upload(customer, 'tides.pdf'), logo(customer)
    draft, _ = branded(customer, source, mark)
    save_config('ai', {'mode': 'local_fixture'})
    photo = upload_file(customer, image())
    cv = create_draft(customer, {'feature_id': CV, 'prompt': BRIEF, 'options': {'portrait_asset_id': str(photo.id)}})
    assert execute_job(submit_job(customer, generation_quote(customer, cv.id, cv.version).id, 'cv-kept-photo')[0].id).status == 'succeeded'
    clock(DAY)
    paid_by_card(customer, 'premium')
    client = login_client(customer)
    assert client.get(f'/api/v1/files/{source.id}/download').status_code == 410, 'past its day'

    change = asked_on_the_web(client, draft.id, 'own-change')
    assert change.input_ids == [str(source.id), str(mark.id)]
    again = asked_on_the_web(client, draft_of(change).id, 'own-change-of-change')
    assert again.input_ids == [str(source.id), str(mark.id)]
    reworded = client.post('/api/v1/generation/drafts', json.dumps({'prompt': CHANGE, 'options': {'revise_draft_id': str(draft.id)}}),
                           content_type='application/json')
    assert reworded.status_code == 201, reworded.content
    reworded = client.patch(f'/api/v1/generation/drafts/{reworded.json()["id"]}', json.dumps(
        {'version': reworded.json()['version'], 'prompt': 'Make it shorter.'}), content_type='application/json')
    assert reworded.status_code == 200, reworded.content
    opened = client.get(f'/api/v1/generation/drafts/{draft.id}').json()
    fields = {key: opened[key] for key in ('title', 'prompt', 'source_text', 'source_ids')}
    fields['options'] = {key: value for key, value in opened['options'].items() if value != ''}
    review = client.patch(f'/api/v1/generation/drafts/{draft.id}', json.dumps({'version': opened['version'], **fields}),
                          content_type='application/json')
    assert review.status_code == 200, review.content
    assert review.json()['source_ids'] == [str(source.id)] and review.json()['options']['branding']['logo_asset_id'] == str(mark.id)
    cv_change = client.post('/api/v1/generation/drafts', json.dumps({'prompt': 'Make it more formal.', 'options': {'revise_draft_id': str(cv.id)}}),
                            content_type='application/json')
    assert cv_change.status_code == 201, cv_change.content
    assert cv_change.json()['options'].get('portrait_asset_id') == str(photo.id) and not cv_change.json()['options'].get('cv_warnings')


@pytest.mark.django_db
def test_the_chat_offers_no_held_upload_past_its_day_for_a_new_document(customer, clock):  # noqa: F811
    """The files staged in the chat, and a CV's files written again, leave a held upload past its day out, as they
    leave out one that ran out: a new document never asks for it."""
    from apps.studio.domain import CV
    from telegram.generation import category_sources, sources, written_again
    source = upload(customer, 'tides.pdf')
    document(customer, 'Tides', source_ids=[str(source.id)])
    old_cv = GenerationDraft.objects.create(account=customer, feature_id=CV, expires_at=keeping.KEPT_UNTIL, encrypted_data=pack(
        {'prompt': 'Notes.', 'source_ids': [str(source.id)], 'options': {'cv_source': 'file'}}))
    assert sources(customer, [str(source.id)]) == [str(source.id)], 'its own day'
    clock(DAY)
    fresh = upload(customer, 'fresh.pdf')
    staged = [str(source.id), str(fresh.id)]
    assert sources(customer, staged) == [str(fresh.id)]
    assert category_sources(customer, staged) == [str(fresh.id)]
    assert written_again(customer, old_cv.id)['source_ids'] == []
    assert there(source)


def test_the_chat_says_in_its_own_words_that_a_held_file_is_sent_there_no_more():
    """A task's screen and a refusal in the chat: the file is sent no more and is sent again to be used, never the
    editor's "opened here" and "edit it"; the web and the editor keep their own words."""
    import re
    from apps.core.errors import DomainError, error_data
    from telegram.errors import bot_error
    from telegram.ux_copy import UX
    held = DomainError('file_expired', 410, {'reason': keeping.KEPT_FOR_DOCUMENT})
    for locale in ('en', 'uz', 'ru'):
        assert UX[locale]['result_held'] == CHAT_HELD[locale] == bot_error(held, locale)
        assert error_data(held, locale)['message'] == HELD[locale]
    assert 'opened' not in UX['en']['result_held'] and 'edit' not in UX['en']['result_held']
    assert not re.search('[А-Яа-яЁё]', UX['uz']['result_held']) and "'" not in UX['uz']['result_held']
