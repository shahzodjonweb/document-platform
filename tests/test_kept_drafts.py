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
