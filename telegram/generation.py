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
from apps.studio.language import settings_locale
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
    """Authoring counts against no limit but is not free of work; cap it per account."""
    key = f'rate:bot_generation:{account.pk}'
    count = cache.get(key, 0)
    if count >= limit:
        raise DomainError('rate_limited', 429, retryable=True)
    cache.set(key, count + 1, 60)


def unthrottle(account):
    """Give back the slot of a request refused by a rule before anything was made."""
    key = f'rate:bot_generation:{account.pk}'
    count = cache.get(key, 0)
    if count:
        cache.set(key, count - 1, 60)


# Refused by reading the description alone, before a draft is made: a cheap
# check, so it does not use one of the minute's builds.
READ_REFUSALS = ('topic_required', 'convert_requested')


@transaction.atomic
def build(account, feature_id, description, file_ids=(), topic_given=False):
    """Author a draft from one chat message. Nothing is counted yet.

    `topic_given` is the customer's answer to the topic question taken as it
    is (apps.studio.domain.create_draft): a topic the check does not know
    must not keep them asking.
    """
    available(account, feature_id)
    text = (description or '').strip()
    ids = sources(account, list(file_ids))
    if not text and not ids:
        raise DomainError('prompt_required')
    throttle(account)
    from operations.integrations import ai_config
    # Local authoring has no model to write with, so the text has to be yours.
    written = ai_config()['mode'] == 'local_fixture'
    # The output language in the account's settings, then the chat's language,
    # as the web sends it: the interface language alone would hide the setting.
    data = {'feature_id': feature_id, 'source_ids': ids, 'output_locale': settings_locale(account),
            'output_format': FORMAT[feature_id],
            'prompt': '' if written else text, 'source_text': text if written else ''}
    if text:
        data['title'] = text.split('\n')[0][:160]
    if topic_given:
        data['options'] = {'topic_given': True}
    try:
        return create_draft(account, data)
    except DomainError as exc:
        if exc.code in READ_REFUSALS:
            unthrottle(account)
        raise


@transaction.atomic
def revise(account, draft_id, request):
    """Apply a change request to a document that has already been generated."""
    text = (request or '').strip()
    if not text:
        raise DomainError('prompt_required')
    source = editable(account, draft_id)
    require(account, source.feature_id)
    throttle(account)
    return create_draft(account, {'prompt': text, 'options': {'revise_draft_id': str(source.id)}})


def editable(account, draft_id):
    """The document a change would apply to; edit_limit when its file has no edits left.

    Asked before a change is written and again before its draft is made, so a
    file whose edits are used up never leaves a draft that cannot be generated.
    """
    from apps.core.allowance import require_edit
    from apps.studio.domain import edit_root, revision_source
    source, original = revision_source(account, draft_id)
    require_edit(account, edit_root(original, source.id))
    return source


def edits_used(draft):
    """(edits made to this draft's file, the plan's edits per file); None is unlimited.

    For an edit, the file is the document it changes: the edit on screen is not
    counted until it is generated.
    """
    from apps.core.allowance import edits_of
    from apps.core.policy import plan_limits
    from apps.studio.domain import edit_root, unpack
    root = edit_root(unpack(draft.encrypted_data), draft.id)
    return edits_of(draft.account, root), plan_limits(draft.account).get('edits_per_file')


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
    # A deck's question slides are slides too: without them a twelve-slide deck
    # whose change keeps every slide read "10 → 12".
    questions = int(original.get('options', {}).get('question_slides', 0) or 0) if draft.feature_id == SLIDES else 0
    return len(original['content']['sections']) + questions


def language_of(draft):
    from apps.studio.domain import unpack
    return unpack(draft.encrypted_data).get('output_locale', '')


def images_wanted(draft):
    """(pictures the description or the change asks for, pictures the plan adds); (0, cap) when none are asked."""
    from apps.studio.domain import unpack
    data = unpack(draft.encrypted_data)
    options = data.get('options', {})
    return int(options.get('images_wanted', 0) or 0), int(options.get('image_cap', 0) or 0)


def pictures_on():
    """Whether any plan can add pictures: none can while photo search is switched off."""
    from operations.integrations import pixabay_config
    return bool(pixabay_config()['ready'])


def _changed(account, draft_id, change):
    """The draft redone with `change(data)` applied to its fields, and its new quote."""
    from apps.studio.domain import unpack, update_draft
    draft = GenerationDraft.objects.filter(account=account, id=draft_id, expires_at__gt=timezone.now()).first()
    if not draft:
        raise DomainError('controls_expired', 409)
    data = unpack(draft.encrypted_data)
    # A change is decided by its request alone. ➖/➕ and language buttons left
    # on a review sent before they were taken off a change are old buttons.
    if data.get('revision'):
        raise DomainError('controls_expired', 409)
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
    from apps.studio.deck_designs import current
    design = current(unpack(draft.encrypted_data).get('options', {}).get('template_style', {}).get('deck_design', ''))
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
    """The service the description names when it is not the one it was sent to, else None.

    Read as the topic refusal reads it (topics.asked_other_service): a format
    that is the topic ("PowerPoint haqida referat") asks for nothing.
    """
    from apps.studio.domain import unpack
    from apps.studio.topics import asked_other_service
    data = unpack(draft.encrypted_data)
    if data.get('revision') or {}:
        return None
    return asked_other_service(data.get('prompt', ''), draft.feature_id) or None


def brief_of(data):
    """What a document was described as. A change's own prompt is the change
    ("slayd qilib ber"), so for a change it is the description it began from."""
    revision = data.get('revision') or {}
    if revision:
        return revision.get('original_prompt') or data.get('source_text', '')
    return data.get('prompt') or data.get('source_text', '')


def description_of(account, draft_id):
    """What a draft was described as, or '' once it has gone."""
    from apps.studio.domain import unpack
    draft = GenerationDraft.objects.filter(account=account, id=draft_id).first()
    return brief_of(unpack(draft.encrypted_data)) if draft else ''


@transaction.atomic
def switch(account, draft_id, feature_id):
    """The same description, sent to the other service."""
    from apps.studio.domain import unpack
    draft = GenerationDraft.objects.filter(account=account, id=draft_id, expires_at__gt=timezone.now()).first()
    if not draft or feature_id not in SERVICES:
        raise DomainError('controls_expired', 409)
    data = unpack(draft.encrypted_data)
    rebuilt = build(account, feature_id, brief_of(data), data.get('source_ids', []))
    return rebuilt, generation_quote(account, rebuilt.id, rebuilt.version)


def change_request(draft):
    """What this draft was asked to change, when it is a change at all."""
    from apps.studio.domain import unpack
    return (unpack(draft.encrypted_data).get('revision') or {}).get('request', '')


def revised_from(draft):
    """The document this draft changes, so a reword goes back to the change."""
    from apps.studio.domain import unpack
    return (unpack(draft.encrypted_data).get('revision') or {}).get('source_draft_id', '')


# A change that asks only for the file in some format is not an AI edit: the
# model would write the same document again and spend an edit doing it, and
# the server refuses it (format_only_change). The chat answers it instead: a
# deck asked for as a PDF goes to PowerPoint → PDF, a document asked for as
# slides is offered a new deck on its subject, and a file asked for in the
# format it already has is sent again.
CONVERTER = 'convert.pptx_to_pdf'


def asked_format(account, draft_id, request):
    """(format, service) when a change to this document asks for nothing but
    the file as 'pdf' or 'pptx'; (None, None) when it asks for anything more."""
    import uuid
    from apps.studio.edits import asks_only_for_format, read
    try:
        identifier = uuid.UUID(str(draft_id))
    except ValueError:
        return None, None
    feature = GenerationDraft.objects.filter(account=account, id=identifier).values_list('feature_id', flat=True).first()
    if feature not in SERVICES:
        return None, None
    kind = asks_only_for_format(request or '')
    if kind is None:
        # Read as the server reads it too, so nothing it would refuse is priced.
        edit = read(request or '', fmt=FORMAT[feature], sections=[])
        kind = edit.format if edit.format_only else None
    return (kind, feature) if kind else (None, None)


def delivered(account, draft_id):
    """(job, file) last made from this draft, while the server still keeps the file; else (None, None)."""
    now = timezone.now()
    jobs = Job.objects.filter(account=account, feature_id__in=SERVICES, status='succeeded',
                              parameters__generation_draft_id=str(draft_id)).order_by('-created_at')
    for job in jobs:
        for artifact in job.artifacts.select_related('file'):
            asset = artifact.file
            if (asset.state == 'ready' and asset.expires_at > now
                    and asset.metadata.get('kind') == FORMAT[job.feature_id]):
                return job, asset
    return None, None


def format_kept(draft):
    """The other format a change names beside other changes, which it does not make; else ''."""
    from apps.studio.domain import unpack
    edit = (unpack(draft.encrypted_data).get('revision') or {}).get('edit') or {}
    return edit.get('format') or ''


@transaction.atomic
def deck_to_pdf(account, draft_id):
    """The PowerPoint → PDF tool set up on this draft's delivered deck; None when the file is gone.

    The tool is checked first either way: where it is not offered, its refusal
    is the answer, not an AI edit that cannot make a PDF of a deck.
    """
    from apps.core.models import Account, BotDraft
    from apps.core.policy import require_feature
    from .workflows import configure
    Account.objects.select_for_update().get(pk=account.pk)
    require_feature(account, CONVERTER)
    job, asset = delivered(account, draft_id)
    if asset is None or job.feature_id != SLIDES:
        return None
    # The customer asked for this file just now; a file task left waiting gives way to it.
    BotDraft.objects.filter(account=account).delete()
    draft = configure(account, feature_id=CONVERTER)
    draft.input_ids = [str(asset.id)]
    draft.version += 1
    draft.save(update_fields=['input_ids', 'version', 'updated_at'])
    return draft


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
    """Quote-bound key, so a double tap on Generate cannot start, or count, twice."""
    job, _ = submit_job(account, quote_id, f'bot:quote:{quote_id}', 'bot')
    return job


def submitted(account, quote_id):
    return Job.objects.filter(account=account, quote_id=quote_id).first()
