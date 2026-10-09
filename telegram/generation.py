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
from apps.core.models import BotCallback, FileAsset, Job, Quote
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


def length_before(draft):
    """For a change request, how many pages the document it changes has; else None."""
    from apps.studio.domain import revision_source, unpack
    source_id = (unpack(draft.encrypted_data).get('revision') or {}).get('source_draft_id')
    if not source_id:
        return None
    try:
        _, original = revision_source(draft.account, source_id)
    except DomainError:
        return None
    return len(original['content']['sections'])


def language_of(draft):
    from apps.studio.domain import unpack
    return unpack(draft.encrypted_data).get('output_locale', '')


def images_wanted(draft):
    """(pictures the description asks for, pictures the plan adds), for a deck; else (0, 0)."""
    from apps.studio.domain import unpack
    data = unpack(draft.encrypted_data)
    options = data.get('options', {})
    return int(options.get('images_wanted', 0) or 0), int(options.get('image_cap', 0) or 0)


PLAN_ORDER = ('free', 'plus', 'premium')


def next_plan(account, limit, needed):
    """(plan, its `limit`) for the first plan above this one that covers `needed`,
    or the biggest above it when none does; None when nothing above gives more."""
    from apps.commerce.services import effective_plan
    from apps.core.policy import limits_for_plan
    current = effective_plan(account)
    if current not in PLAN_ORDER:
        return None
    have = int(limits_for_plan(current).get(limit) or 0)
    best = None
    for plan in PLAN_ORDER[PLAN_ORDER.index(current) + 1:]:
        value = int(limits_for_plan(plan).get(limit) or 0)
        if value > have:
            best = (plan, value)
            if value >= needed:
                return best
    return best


def _changed(account, draft_id, change):
    """The draft redone with `change(data)` applied to its fields, and its new price."""
    from apps.studio.domain import unpack, update_draft
    draft = GenerationDraft.objects.filter(account=account, id=draft_id, expires_at__gt=timezone.now()).first()
    if not draft:
        raise DomainError('controls_expired', 409)
    data = unpack(draft.encrypted_data)
    fields = change(data)
    draft = update_draft(account, draft.id, {'version': draft.version, **fields})
    return draft, generation_quote(account, draft.id, draft.version)


@transaction.atomic
def resize(account, draft_id, pages):
    """The same draft at another page or slide count, chosen on the review screen."""
    if type(pages) is not int or pages < 1:
        raise DomainError('invalid_parameters')
    return _changed(account, draft_id, lambda data: {'options': {**data['options'], 'pages': pages}})


def design_of(draft):
    """The deck design's name if one is set — picked, or inherited by a change — else '' for auto."""
    from apps.studio.domain import unpack
    design = unpack(draft.encrypted_data).get('options', {}).get('template_style', {}).get('deck_design', '')
    return design.replace('_', ' ').title()


@transaction.atomic
def relocale(account, draft_id, locale):
    """The same draft in another language, chosen on the review screen."""
    if locale not in ('en', 'uz', 'ru'):
        raise DomainError('invalid_locale')
    return _changed(account, draft_id, lambda data: {
        'output_locale': locale, 'options': {**data['options'], 'locale_chosen': True}})


def is_example(description):
    """Whether a description is one of the bot's own examples, sent back unchanged."""
    import difflib
    from .ux_copy import PROMPT_EXAMPLES
    text = ' '.join((description or '').lower().split())
    if len(text) < 40:
        return False
    for examples in PROMPT_EXAMPLES.values():
        for translations in examples:
            for example in translations:
                if difflib.SequenceMatcher(None, text, ' '.join(example.lower().split())).ratio() >= 0.9:
                    return True
    return False


def other_service(draft):
    """The service the description names when it is not the one it was sent to, else None."""
    from apps.studio.domain import unpack
    from apps.studio.pages import names_document, names_slides
    if (unpack(draft.encrypted_data).get('revision') or {}):
        return None
    prompt = unpack(draft.encrypted_data).get('prompt', '')
    if draft.feature_id == DOCUMENT and names_slides(prompt):
        return SLIDES
    if draft.feature_id == SLIDES and names_document(prompt) and not names_slides(prompt):
        return DOCUMENT
    return None


@transaction.atomic
def switch(account, draft_id, feature_id):
    """The same description, sent to the other service."""
    from apps.studio.domain import unpack
    draft = GenerationDraft.objects.filter(account=account, id=draft_id, expires_at__gt=timezone.now()).first()
    if not draft or feature_id not in SERVICES:
        raise DomainError('controls_expired', 409)
    data = unpack(draft.encrypted_data)
    rebuilt = build(account, feature_id, data.get('prompt') or data.get('source_text', ''), data.get('source_ids', []))
    return rebuilt, generation_quote(account, rebuilt.id, rebuilt.version)


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


@transaction.atomic
def retry(account, callback_token):
    """One confirmation per owned Retry button; replays never create new work."""
    from apps.studio.checkpoints import retry_quote
    from apps.studio.domain import validate_generation_quote
    control = BotCallback.objects.select_for_update().filter(
        pk=callback_token, account=account, action='ai_retry', expires_at__gt=timezone.now()).first()
    if not control:
        raise DomainError('controls_expired', 409)
    # The callback token represents this explicit retry, not permission to
    # create another quote on every delivery or double tap.
    if control.payload.get('quote_id'):
        result = Quote.objects.filter(pk=control.payload['quote_id'], account=account,
                                      expires_at__gt=timezone.now()).first()
        if not result:
            raise DomainError('controls_expired', 409)
        validate_generation_quote(account, result)
    else:
        result = retry_quote(account, control.payload.get('job_id'))
        control.payload = {**control.payload, 'quote_id': str(result.id)}
        control.save(update_fields=['payload'])
    draft = GenerationDraft.objects.get(pk=result.parameters['generation_draft_id'], account=account)
    return draft, result


def start(account, quote_id):
    """Quote-bound key, so a double tap on Generate cannot charge twice."""
    job, _ = submit_job(account, quote_id, f'bot:quote:{quote_id}', 'bot')
    return job


def submitted(account, quote_id):
    return Job.objects.filter(account=account, quote_id=quote_id).first()
