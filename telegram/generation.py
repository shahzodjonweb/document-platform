"""Making a document, a deck or a CV from the chat.

Synchronous and transaction-safe, with no Telegram network calls, like
workflows.py. There are three services and one input: what the customer wants,
written out. Page count, questions, tone and audience are all read from that
description by apps.studio, which the web app uses identically. A CV is
written from what the customer says about themselves, or made from their
LinkedIn profile or old CV sent as files (apps/studio/cv/sources.py), and may
carry the one photo they send in the chat as its portrait.
"""
import uuid

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import BotCallback, FileAsset, Job, Quote
from apps.core.services import submit_job
from apps.studio.cv.sources import FILE, LINKEDIN, TEXT
from apps.studio.domain import CV, DOCUMENT, SLIDES, create_draft, generation_quote, require
from apps.studio.language import settings_locale
from apps.studio.models import GenerationDraft

SERVICES = (DOCUMENT, SLIDES, CV)
# Re-exported so bot.py can name them without a second import.
__all__ = ['CV', 'DOCUMENT', 'SLIDES', 'SERVICES']
# A document and a CV are PDFs and a deck is an editable PowerPoint, in the
# chat as on the web. The server forces this too; it is repeated here so the
# bot does not describe an output it cannot produce.
FORMAT = {DOCUMENT: 'pdf', SLIDES: 'pptx', CV: 'pdf'}


def available(account, feature_id):
    """Raise the reason this service cannot be started, if there is one."""
    if feature_id not in SERVICES:
        raise DomainError('feature_unavailable', 409)
    require(account, feature_id)


def sources(account, file_ids, feature_id=None):
    """The PDFs staged in the chat, in the order they were sent.

    None for a CV: the file tools' files are never its files. A CV made from
    files takes the ones sent on its own screens, which never go on the file
    tools' draft (build's `cv_source`).
    """
    if feature_id == CV:
        return []
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


# Refused by reading the description alone, or a CV's files' kinds, before a
# draft is made: a cheap check, so it does not use one of the minute's builds.
READ_REFUSALS = ('topic_required', 'convert_requested', 'cv_name_required', 'cv_file_required', 'cv_file_kind',
                 'cv_linkedin_link')


@transaction.atomic
def build(account, feature_id, description, file_ids=(), topic_given=False, portrait_asset_id='', cv_source=''):
    """Author a draft from one chat message. Nothing is counted yet.

    `topic_given` is the customer's answer to the topic question taken as it
    is (apps.studio.domain.create_draft): a topic the check does not know
    must not keep them asking. For a CV it is the name question answered a
    second time, and `portrait_asset_id` the photo sent for it in the chat.
    A CV made from the customer's LinkedIn profile or old CV (`cv_source`
    'linkedin' or 'file') is made from `file_ids`, the files sent for it,
    and `description` is the notes on top of them, which may be empty.
    """
    available(account, feature_id)
    text = (description or '').strip()
    files = feature_id == CV and cv_source in (LINKEDIN, FILE)
    ids = [str(identifier) for identifier in file_ids] if files else sources(account, list(file_ids), feature_id)
    if not text and not ids:
        raise DomainError('prompt_required')
    throttle(account)
    from operations.integrations import ai_config
    # Local authoring has no model to write with, so the text has to be yours.
    # A CV made from files is the files' text there: the notes stay notes.
    written = ai_config()['mode'] == 'local_fixture' and not files
    # The output language in the account's settings, then the chat's language,
    # as the web sends it: the interface language alone would hide the setting.
    data = {'feature_id': feature_id, 'source_ids': ids, 'output_locale': settings_locale(account),
            'output_format': FORMAT[feature_id],
            'prompt': '' if written else text, 'source_text': text if written else ''}
    # A CV's title is the person's name, which the server finds in the
    # description (apps/studio/cv/content.require_name): its first line is as
    # often a phone number or "Hello", and would be the file's name. Only when
    # the customer answered the name question twice and no name was seen is
    # the first line, their own answer, the best there is.
    if text and (feature_id != CV or topic_given):
        data['title'] = text.split('\n')[0][:160]
    options = {'topic_given': True} if topic_given else {}
    if files:
        options['cv_source'] = cv_source
    if feature_id == CV and portrait_asset_id:
        # The server checks it is the customer's own JPEG or PNG and pins it.
        options['portrait_asset_id'] = str(portrait_asset_id)
    if options:
        data['options'] = options
    try:
        return create_draft(account, data)
    except DomainError as exc:
        # A CV from files asked for its name has had its files read: that build
        # counts, so answers that name nobody cannot read them again and again.
        if exc.code in READ_REFUSALS and not (files and exc.code == 'cv_name_required'):
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
    """Pages resolved, and pages asked for when the two differ.

    Not shown for a CV: its length is its eight sections, which its template
    lays out on one page or two (the review says "1–2").
    """
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


def portrait_of(draft):
    """The asset id of the photo a CV carries, or '' when it has none."""
    from apps.studio.domain import unpack
    return str(unpack(draft.encrypted_data).get('options', {}).get('portrait_asset_id') or '')


def template_of(draft):
    """The CV template's name if one is set — picked, or inherited by a change — else '' for Auto."""
    from apps.studio.domain import unpack
    from apps.studio.cv import templates
    options = unpack(draft.encrypted_data).get('options', {})
    key = templates.chosen(options) or templates.current((options.get('template_style') or {}).get('cv_template') or '')
    names = {entry['id']: entry['name'] for group in templates.catalogue() for entry in group['templates']}
    return names.get(key, '')


def photo_slot(draft):
    """Whether the CV's template has a place for a photo: False only when one without is picked or kept.

    On Auto nobody knows yet, and the model is told to choose a template with
    a place for the photo the customer sent (apps/studio/cv/templates.py).
    """
    from apps.studio.domain import unpack
    from apps.studio.cv import templates
    options = unpack(draft.encrypted_data).get('options', {})
    key = templates.chosen(options) or templates.current((options.get('template_style') or {}).get('cv_template') or '')
    return templates.TEMPLATES[key]['photo'] if key in templates.TEMPLATES else True


@transaction.atomic
def append_description(account, draft_id, more):
    """A new CV on the review screen with `more` written after its description, and its new quote.

    Telegram sends a description longer than one message as two: the second
    part arrives on the review the first one led to, and belongs to that CV.
    For a CV made from files it is more of the notes on top of them, which
    are its prompt even when there were none before.
    """
    from apps.studio.domain import unpack
    text = (more or '').strip()
    draft = GenerationDraft.objects.filter(account=account, id=draft_id, feature_id=CV,
                                           expires_at__gt=timezone.now()).first()
    if not text or draft is None or unpack(draft.encrypted_data).get('revision'):
        raise DomainError('controls_expired', 409)
    data = unpack(draft.encrypted_data)
    files = (data.get('options') or {}).get('cv_source') in (LINKEDIN, FILE)
    field = 'prompt' if data.get('prompt') or files else 'source_text'
    return _changed(account, draft_id, lambda data: {field: f"{data.get(field) or ''}\n{text}".strip()})


def _cv_draft(account, draft_id, *, live=False):
    """This account's CV draft `draft_id`, or None: also for an id that is no draft's id at all."""
    try:
        identifier = uuid.UUID(str(draft_id))
    except ValueError:
        return None
    drafts = GenerationDraft.objects.filter(account=account, id=identifier, feature_id=CV)
    return (drafts.filter(expires_at__gt=timezone.now()) if live else drafts).first()


def file_names(account, ids):
    """The names of these files of the account's, in the order given; '' for one no longer kept."""
    names = {str(key): name for key, name in FileAsset.objects.filter(account=account, id__in=list(ids))
             .values_list('id', 'name')}
    return [names.get(str(identifier), '') for identifier in ids]


def made_from(draft):
    """How a CV was made: (way, the names of its files, the notes on top of them).

    ('text', [], '') for one written in a message. A change keeps the way and
    the files of the CV it changes; its prompt is the change, so it has no notes.
    """
    from apps.studio.domain import unpack
    data = unpack(draft.encrypted_data)
    way = (data.get('options') or {}).get('cv_source') or TEXT
    if way not in (LINKEDIN, FILE):
        return TEXT, [], ''
    notes = '' if data.get('revision') else (data.get('prompt') or '').strip()
    return way, file_names(draft.account, data.get('source_ids') or []), notes


def unread_of(draft):
    """What of a new CV's files could not be read (apps/studio/cv/sources.py): (files, pages).

    Files not read at all, and the pages left out of the others: past the
    pages OCR reads for one CV, or past the time its files are read in.
    """
    from apps.studio.domain import unpack
    data = unpack(draft.encrypted_data)
    if data.get('revision'):
        return 0, 0
    unread = [entry for entry in data.get('cv_unread') or [] if isinstance(entry, dict)]
    return (sum(1 for entry in unread if entry.get('whole')),
            sum(int(entry.get('pages') or 0) for entry in unread if not entry.get('whole')))


def cv_files(account, draft_id):
    """A new CV's way and files: {'way', 'source_ids', 'images'}, `images` when a photo or screenshot is one of them; None without it."""
    from apps.studio.domain import unpack
    draft = _cv_draft(account, draft_id, live=True)
    if draft is None:
        return None
    data = unpack(draft.encrypted_data)
    way = (data.get('options') or {}).get('cv_source') or TEXT
    ids = [str(identifier) for identifier in data.get('source_ids') or []] if way in (LINKEDIN, FILE) else []
    images = FileAsset.objects.filter(account=account, id__in=ids, mime_type__in=('image/jpeg', 'image/png')).exists()
    return {'way': way, 'source_ids': ids, 'images': images, 'revision': bool(data.get('revision'))}


def way_of(account, draft_id):
    """The way a CV draft of this account's was made ('text', 'linkedin' or 'file'); '' when there is none."""
    from apps.studio.domain import unpack
    draft = _cv_draft(account, draft_id)
    if draft is None:
        return ''
    return (unpack(draft.encrypted_data).get('options') or {}).get('cv_source') or TEXT


def written_again(account, draft_id):
    """What a CV's description written again starts from: None once the CV has gone.

    {'cv_source', 'source_ids', 'notes', 'portrait_asset_id'}: the way it was
    made, its files while the server still keeps them (24 hours), the notes
    written on top of them, and its photo while it can still go on a CV.
    """
    from apps.studio.domain import unpack
    draft = _cv_draft(account, draft_id)
    if draft is None:
        return None
    data = unpack(draft.encrypted_data)
    way = (data.get('options') or {}).get('cv_source') or TEXT
    ids = [str(identifier) for identifier in data.get('source_ids') or []] if way in (LINKEDIN, FILE) else []
    kept = {str(key) for key in FileAsset.objects.filter(account=account, id__in=ids, state='ready',
                                                         expires_at__gt=timezone.now()).values_list('id', flat=True)}
    notes = (data.get('prompt') or '').strip() if way in (LINKEDIN, FILE) and not data.get('revision') else ''
    return {'cv_source': way, 'source_ids': [identifier for identifier in ids if identifier in kept],
            'notes': [notes] if notes else [], 'portrait_asset_id': usable_portrait(account, portrait_of(draft))}


@transaction.atomic
def add_sources(account, draft_id, asset_ids, more=''):
    """A new CV made from files with more of them, and its new quote.

    Screenshots sent one at a time, or the end of an album that came late, are
    its files too: all of them are read again together. `more` is a caption
    sent with them, added to the notes.
    """
    from apps.studio.domain import unpack
    draft = _cv_draft(account, draft_id, live=True)
    if draft is None or unpack(draft.encrypted_data).get('revision'):
        raise DomainError('controls_expired', 409)
    text = (more or '').strip()

    def change(data):
        known = list(data.get('source_ids') or [])
        fields = {'source_ids': [*known, *[str(identifier) for identifier in asset_ids if str(identifier) not in known]]}
        if text:
            fields['prompt'] = f"{data.get('prompt') or ''}\n{text}".strip()
        return fields
    return _changed(account, draft_id, change)


def check_portrait(account, asset_id):
    """Refuse a photo that cannot go on a CV, as the server will when the CV is described.

    Asked as soon as the photo arrives, so a picture too large for a CV is
    said then, not as the refusal of the description written after it.
    """
    from apps.studio.cv.portrait import prepare
    prepare(account, CV, {'portrait_asset_id': str(asset_id)})


def usable_portrait(account, asset_id):
    """`asset_id` while it can still go on a CV, else '': a photo kept with an
    old button or question may have expired since, and is then left out."""
    if not asset_id:
        return ''
    try:
        check_portrait(account, asset_id)
    except DomainError:
        return ''
    return str(asset_id)


def kept_portrait(account, draft_id):
    """The photo of this account's CV draft, for its description written again; '' when there is none to keep."""
    draft = GenerationDraft.objects.filter(account=account, id=draft_id, feature_id=CV).first()
    return usable_portrait(account, portrait_of(draft)) if draft else ''


@transaction.atomic
def add_portrait(account, draft_id, asset_id):
    """A new CV on the review screen with the photo sent after its description, and its new quote."""
    if not GenerationDraft.objects.filter(account=account, id=draft_id, feature_id=CV).exists():
        raise DomainError('controls_expired', 409)
    return _changed(account, draft_id, lambda data: {
        'options': {**data['options'], 'portrait_asset_id': str(asset_id)}})


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


def service_of(account, draft_id):
    """The service a draft of this account's belongs to, or '' when there is none."""
    import uuid
    try:
        identifier = uuid.UUID(str(draft_id))
    except ValueError:
        return ''
    feature = GenerationDraft.objects.filter(account=account, id=identifier).values_list('feature_id', flat=True).first()
    return feature if feature in SERVICES else ''


def asked_format(account, draft_id, request):
    """(format, service) when a change to this document asks for nothing but
    the file as 'pdf' or 'pptx'; (None, None) when it asks for anything more.

    A CV is only ever a PDF: asked for as one it is sent again, and asked for
    as slides it goes to the server, which says a change does not convert
    (format_only_change).
    """
    from apps.studio.edits import asks_only_for_format, read
    feature = service_of(account, draft_id)
    if not feature:
        return None, None
    kind = asks_only_for_format(request or '')
    if kind is None:
        # Read as the server reads it too, so nothing it would refuse is priced.
        edit = read(request or '', fmt=FORMAT[feature], sections=[])
        kind = edit.format if edit.format_only else None
    if feature == CV and kind != 'pdf':
        return None, None
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
