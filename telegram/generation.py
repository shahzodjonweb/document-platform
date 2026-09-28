"""Making a document or a deck from the chat.

Synchronous and transaction-safe, with no Telegram network calls, like
workflows.py. There are two services and one input: what the customer wants,
written out. Page count, questions, tone and audience are all read from that
description by apps.studio, which the web app uses identically.
"""
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import FileAsset, Job
from apps.core.services import submit_job
from apps.studio.domain import DOCUMENT, SLIDES, create_draft, generation_quote, require
from apps.studio.models import GenerationDraft

SERVICES = (DOCUMENT, SLIDES)
# Re-exported so bot.py can name them without a second import.
__all__ = ['DOCUMENT', 'SLIDES', 'SERVICES']
# A document is a PDF and a deck is an editable PowerPoint, in the chat as on
# the web. The server forces this too; it is repeated here so the bot does not
# describe an output it cannot produce.
FORMAT = {DOCUMENT: 'pdf', SLIDES: 'pptx'}


def available(account, feature_id):
    """Raise the reason this service cannot be started, if there is one."""
    if feature_id not in SERVICES:
        raise DomainError('feature_unavailable', 409)
    require(account, feature_id)


def sources(account, file_ids):
    """The PDFs staged in the chat, in the order they were sent."""
    assets = {
        str(asset.id): asset
        for asset in FileAsset.objects.filter(account=account, id__in=file_ids, state='ready',
                                              expires_at__gt=timezone.now())
    }
    ordered = [assets[key] for key in file_ids if key in assets]
    return [str(asset.id) for asset in ordered if asset.metadata.get('kind') == 'pdf']


def throttle(account, limit=10):
    """Authoring is uncharged but not free of work; cap it per account."""
    key = f'rate:bot_generation:{account.pk}'
    count = cache.get(key, 0)
    if count >= limit:
        raise DomainError('rate_limited', 429, retryable=True)
    cache.set(key, count + 1, 60)


@transaction.atomic
def build(account, feature_id, description, file_ids=()):
    """Author a draft from one chat message. Nothing is charged."""
    available(account, feature_id)
    text = (description or '').strip()
    ids = sources(account, list(file_ids))
    if not text and not ids:
        raise DomainError('prompt_required')
    throttle(account)
    from operations.integrations import ai_config
    # Local authoring has no model to write with, so the text has to be yours.
    written = ai_config()['mode'] == 'local_fixture'
    data = {'feature_id': feature_id, 'source_ids': ids, 'output_locale': account.locale,
            'output_format': FORMAT[feature_id],
            'prompt': '' if written else text, 'source_text': text if written else ''}
    if text:
        data['title'] = text.split('\n')[0][:160]
    return create_draft(account, data)


@transaction.atomic
def revise(account, draft_id, request):
    """Apply a change request to a document that has already been generated."""
    text = (request or '').strip()
    if not text:
        raise DomainError('prompt_required')
    from apps.studio.domain import revision_source
    source, _ = revision_source(account, draft_id)
    require(account, source.feature_id)
    throttle(account)
    return create_draft(account, {'prompt': text, 'options': {'revise_draft_id': str(source.id)}})


def revisable(account, draft_id):
    """The document a change would apply to, or None when there is none left."""
    from apps.core.errors import DomainError as _DomainError
    from apps.studio.domain import revision_source
    try:
        source, original = revision_source(account, draft_id)
    except _DomainError:
        return None
    return original.get('title') or ''


def title_of(draft):
    """Drafts are encrypted at rest; the review screen needs the title back."""
    from apps.studio.domain import unpack
    return unpack(draft.encrypted_data).get('title', '')


def summary(draft):
    """Pages resolved, and pages asked for when the two differ."""
    from apps.studio.domain import unpack
    options = unpack(draft.encrypted_data)['options']
    return options.get('length', 0), options.get('requested_pages')


def change_request(draft):
    """What this draft was asked to change, when it is a change at all."""
    from apps.studio.domain import unpack
    return (unpack(draft.encrypted_data).get('revision') or {}).get('request', '')


def revised_from(draft):
    """The document this draft changes, so a reword goes back to the change."""
    from apps.studio.domain import unpack
    return (unpack(draft.encrypted_data).get('revision') or {}).get('source_draft_id', '')


def quote(account, draft_id):
    draft = GenerationDraft.objects.filter(account=account, id=draft_id,
                                           expires_at__gt=timezone.now()).first()
    if not draft:
        raise DomainError('controls_expired', 409)
    return draft, generation_quote(account, draft.id, draft.version)


def start(account, quote_id):
    """Quote-bound key, so a double tap on Generate cannot charge twice."""
    job, _ = submit_job(account, quote_id, f'bot:quote:{quote_id}', 'bot')
    return job


def submitted(account, quote_id):
    return Job.objects.filter(account=account, quote_id=quote_id).first()
