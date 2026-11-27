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
from apps.studio.domain import CV, DOCUMENT, EXPORT, RENDER_IDS, SLIDES, create_draft, generation_quote, require
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
    assets = _live(account, file_ids)
    ordered = [assets[key] for key in file_ids if key in assets]
    return [str(asset.id) for asset in ordered if asset.metadata.get('kind') == 'pdf']


def _live(account, file_ids):
    """These files of the account's that a new document may take, by id: still kept, and none held only for changing an
    AI document past its own day (apps/studio/keeping.py), which is left out as a file that ran out is."""
    from apps.studio.keeping import held_past_its_day
    now = timezone.now()
    return {str(asset.id): asset for asset in FileAsset.objects.filter(account=account, id__in=list(file_ids), state='ready', expires_at__gt=now)
            if not held_past_its_day(asset, now)}


# The kinds of file a category draft reads (apps/studio/categories/sources.py KINDS):
# PDF, Word, old Word and text. Anything else staged in the chat, a photo for a
# file tool, is left out rather than refusing the draft.
CATEGORY_KINDS = ('pdf', 'docx', 'doc', 'text')


def category_sources(account, file_ids):
    """The files a category draft is made from, in the order they were sent, once each."""
    assets = _live(account, file_ids)
    ordered = list(dict.fromkeys(str(key) for key in file_ids))
    return [key for key in ordered if key in assets and assets[key].metadata.get('kind') in CATEGORY_KINDS]


@transaction.atomic
def stage(account, file_ids):
    """Put the PDFs among `file_ids` on the chat's file draft, after those already there.

    Files sent on the list of categories wait in the chat's state. Boshqa,
    chosen after them, is today's question, which reads the PDFs staged in the
    chat (sources): this puts them where it would have found them had they been
    sent to it. A Word or text file is never staged: it was taken as a
    category's source, and the file tools never meet one.
    """
    from apps.core.models import Account
    from .workflows import draft_for
    pdfs = sources(account, [str(key) for key in file_ids])
    if not pdfs:
        return
    Account.objects.select_for_update().get(pk=account.pk)
    draft = draft_for(account)
    added = [key for key in pdfs if key not in [str(item) for item in draft.input_ids]][:max(0, 50 - len(draft.input_ids))]
    if added:
        draft.input_ids = [*draft.input_ids, *added]
        draft.quote = None
        draft.version += 1
        draft.save(update_fields=['input_ids', 'quote', 'version', 'updated_at'])


# --- Categories ---------------------------------------------------------------
# AI PDF and AI Slides may open a list of categories before the description
# (apps/studio/categories). Off, or with nothing ticked, the list is never shown
# and every way in is today's question. Boshqa ('other') is today's question too.

OTHER = 'other'


def _switched_on():
    """Whether the categories switch is on with something ticked, read from its row before the catalogue is loaded.

    Off is the shipped default, and every AI PDF and AI Slides tap asks: importing the catalogue then builds and
    checks every entry and template for nothing, and one that failed to load would break today's question. The
    row is looked up on each call, as the catalogue's own switch read is, so a change takes effect at once.
    """
    import importlib
    try:
        settings = importlib.import_module('operations.categories_settings')
    except ModuleNotFoundError:
        return False
    switch = settings.get()
    return bool(switch.get('on') and switch.get('live'))


def category_menu(feature_id, group=None):
    """The buttons of a service's list (or of one group in it); [] when there is no list to show."""
    if feature_id not in (DOCUMENT, SLIDES) or not _switched_on():
        return []
    from apps.studio import categories
    return categories.menu(feature_id, group)


def category_live(feature_id, category):
    """The entry of `category` when customers may pick it for this service now, else None."""
    if not isinstance(category, str) or not category or category == OTHER or not _switched_on():
        return None
    from apps.studio import categories
    # Looked up among the live ones (only this service's), not with get(): with
    # the switch off, a button from an older list must not load the catalogue.
    return next((entry for entry in categories.live(feature_id) if entry.id == category), None)


def door(feature_id, category=None):
    """Where a way into a service leads, as (kind, value, gone).

    `category` is what the button named: nothing (a service button, every old
    one included), a group, a category, or Boshqa. The answer is ('prompt',
    None) for today's question, ('list', group or None) for the list or one of
    its groups, and ('category', id) for a category's own question. `gone` is
    True when the list is shown because the category named cannot be picked
    now: unticked, retired or rolled back since its button was drawn. With the
    switch off, or nothing ticked for this service, every way is today's
    question, so a button from a list drawn while it was on still opens one.
    """
    if feature_id not in (DOCUMENT, SLIDES) or category == OTHER or not category_menu(feature_id):
        return 'prompt', None, False
    if not category:
        return 'list', None, False
    if category_live(feature_id, category) is not None:
        return 'category', category, False
    if isinstance(category, str) and category_menu(feature_id, category):
        return 'list', category, False
    from apps.studio import categories
    entry = categories.get(category) if isinstance(category, str) else None
    parent = entry.raw.get('parent') if entry is not None and entry.feature_id == feature_id else None
    return 'list', parent if parent and category_menu(feature_id, parent) else None, True


def category_of(draft):
    """The category a draft was made in, '' for none."""
    from apps.studio.domain import unpack
    return (unpack(draft.encrypted_data).get('options') or {}).get('category') or ''


def chosen(account, category):
    """Record that a customer opened a category's question in the bot (categories/chosen.py). Never raises."""
    from apps.studio.categories.chosen import record
    record(account, category, 'bot')


# A category's one extra question (its entry's `ask`) is a button on the
# review of a new draft, answered at most once with text, files or both, and
# always skippable: Generate makes the draft as it stands. The answer goes the
# way every review change goes (_changed): the server re-seeds and re-quotes,
# and marks it answered (options.details_added), never the bot.
#
# A deck's answer for its title slide (`ask.cover`) is written under a header
# title_lines.BLOCK reads, so title_lines.place puts its lines on the cover as
# the customer's own. The header is in the deck's language.
COVER_HEADERS = {'uz': 'Titul slaydga:', 'ru': 'На титульном слайде:', 'en': 'Title slide:'}
# A generation that ended without making anything leaves the draft on its first
# review: Generate is tapped again from there, and the question still helps.
# Every other state, a status added later included, closes the question.
UNMADE = ('failed', 'canceled', 'expired')


def _asked(draft, data):
    """The entry whose question this draft's review offers now, or None.

    Only a new category draft's review offers it, while it is unanswered, when
    its entry has a question wanted for what was written and sent
    (categories.asking.wanted), and before anything was generated from the
    draft (UNMADE: a failed or canceled generation made nothing): the question
    belongs to the first review.
    """
    options = data.get('options') or {}
    if not options.get('category') or data.get('revision') or options.get('details_added'):
        return None
    # A deck drawn already is made, as _changed holds: only ✏️ Edit changes it.
    if draft.feature_id == SLIDES and data.get('_render'):
        return None
    from apps.studio import categories
    from apps.studio.categories import asking
    from apps.studio.domain import GENERATION_IDS
    entry = categories.get(options['category'])
    if entry is None or not entry.raw.get('ask'):
        return None
    if not asking.wanted(entry, brief_of(data), bool(data.get('source_ids'))):
        return None
    generated = Job.objects.filter(account=draft.account, feature_id__in=GENERATION_IDS,
                                   quote__parameters__generation_draft_id=str(draft.id)).exclude(status__in=UNMADE)
    return None if generated.exists() else entry


def category_review(draft):
    """What a category draft's review says beyond today's, or None for a draft without a category (and a CV).

    {'entry', 'asked': the entry when its question is offered, 'unread': files
    that gave no text, 'cut': whether only each file's ends were read,
    'bounds': (fewest, most) of a count the stepper may choose, None when the
    entry's length is not a count: an ariza is always one page (`fixed`) and a
    test as long as its questions (`derived`), so the review offers no stepper
    whose taps the server would answer with the same number}. A category the
    catalogue no longer holds has nothing to say: its job fails before the
    provider (category_unknown).
    """
    from apps.studio import categories
    from apps.studio.domain import unpack
    if draft.feature_id not in (DOCUMENT, SLIDES):
        return None
    data = unpack(draft.encrypted_data)
    options = data.get('options') or {}
    entry = categories.get(options.get('category')) if options.get('category') else None
    if entry is None:
        return None
    length = entry.length
    return {'entry': entry, 'asked': _asked(draft, data), 'unread': len(options.get('unread_sources') or []),
            'cut': bool(options.get('sources_cut')),
            'bounds': (length['min'], length['max']) if length['mode'] == 'count' else None}


def details_open(account, draft_id):
    """(draft, entry) when this account's draft still offers its category's question; (None, None) when it does not."""
    from apps.studio.domain import unpack
    try:
        identifier = uuid.UUID(str(draft_id))
    except ValueError:
        return None, None
    draft = GenerationDraft.objects.filter(account=account, id=identifier, expires_at__gt=timezone.now()).first()
    entry = _asked(draft, unpack(draft.encrypted_data)) if draft is not None else None
    return (draft, entry) if entry is not None else (None, None)


@transaction.atomic
def add_details(account, draft_id, text='', file_ids=()):
    """A new category draft with the answer to its review question added, and its new quote.

    The text is written after the description, under the title-slide header
    for a deck whose question is for its cover; the files (PDF, Word or text,
    the customer's own) join its sources. Answered once: the server marks it
    (options.details_added) and refuses a second answer. The review button is
    offered only while the question is open, so a button from an older review
    is controls_expired here.
    """
    from apps.studio.domain import unpack
    draft, entry = details_open(account, draft_id)
    if entry is None:
        raise DomainError('controls_expired', 409)
    words = (text or '').strip()
    ids = category_sources(account, [str(identifier) for identifier in file_ids])
    if not words and not ids:
        raise DomainError('prompt_required')
    data = unpack(draft.encrypted_data)
    if words and draft.feature_id == SLIDES and entry.ask.get('cover'):
        words = f"{COVER_HEADERS.get(data.get('output_locale'), COVER_HEADERS['en'])}\n{words}"
    # The description is the prompt, or the source text where there is no model
    # to write with (build's `written`): the answer goes where the description is.
    if data.get('prompt') or data.get('source_text'):
        field = 'prompt' if data.get('prompt') else 'source_text'
    else:
        from operations.integrations import ai_config
        field = 'source_text' if ai_config()['mode'] == 'local_fixture' else 'prompt'

    def change(data):
        fields = {}
        if words:
            fields[field] = f"{data.get(field) or ''}\n\n{words}".strip()
        if ids:
            known = [str(identifier) for identifier in data.get('source_ids') or []]
            fields['source_ids'] = [*known, *[identifier for identifier in ids if identifier not in known]]
        return fields
    return _changed(account, draft.id, change, details=True)


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
READ_REFUSALS = ('topic_required', 'convert_requested', 'cv_missing', 'cv_file_required', 'cv_file_kind',
                 'cv_linkedin_link')


@transaction.atomic
def build(account, feature_id, description, file_ids=(), topic_given=False, portrait_asset_id='', cv_source='',
          category=''):
    """Author a draft from one chat message. Nothing is counted yet.

    `topic_given` is the customer's answer to the topic question taken as it
    is (apps.studio.domain.create_draft): a topic the check does not know
    must not keep them asking. For a CV it is the question for what is
    missing answered a second time, and `portrait_asset_id` the photo sent for
    it in the chat.
    A CV made from the customer's LinkedIn profile or old CV (`cv_source`
    'linkedin' or 'file') is made from `file_ids`, the files sent for it,
    and `description` is the notes on top of them, which may be empty.
    `category` is the one chosen in the chat's list, '' for none. One that
    can no longer be picked (the switch turned off, or the category unticked,
    while the customer was writing) is left out: they still get a document,
    today's. A category draft reads Word and text files as well as PDFs.
    """
    available(account, feature_id)
    if category and category_live(feature_id, category) is None:
        category = ''
    text = (description or '').strip()
    files = feature_id == CV and cv_source in (LINKEDIN, FILE)
    ids = ([str(identifier) for identifier in file_ids] if files
           else category_sources(account, file_ids) if category else sources(account, list(file_ids), feature_id))
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
    # description (apps/studio/cv/content.require_facts): its first line is as
    # often a phone number or "Hello", and would be the file's name. Only when
    # the customer insisted and no name was seen is the first line, their own
    # answer, the best there is.
    if text and (feature_id != CV or topic_given):
        data['title'] = text.split('\n')[0][:160]
    options = {'topic_given': True} if topic_given else {}
    if files:
        options['cv_source'] = cv_source
    if feature_id == CV and portrait_asset_id:
        # The server checks it is the customer's own JPEG or PNG and pins it.
        options['portrait_asset_id'] = str(portrait_asset_id)
    if category:
        options['category'] = category
    if options:
        data['options'] = options
    try:
        return create_draft(account, data)
    except DomainError as exc:
        # A CV from files asked for what it lacks has had its files read: that
        # build counts, so answers that give nothing cannot read them again and again.
        if exc.code in READ_REFUSALS and not (files and exc.code == 'cv_missing'):
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
    # A category paper's sections are its parts, not its pages: a one-page
    # ariza has seven, and its change read "7 → 1". Its pages are its stored
    # length (categories.skeleton.pages, the one reader of the number). A deck
    # in a category keeps one section a slide, so it is read as today's.
    if (original.get('options') or {}).get('category'):
        from apps.studio.categories import skeleton
        try:
            pages = skeleton.pages(original)
        except DomainError:
            return None
        if pages is not None:
            return pages
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


def _changed(account, draft_id, change, *, details=False):
    """The draft redone with `change(data)` applied to its fields, and its new quote.

    `details`: the change is the answer to a category's review question, which
    the server marks answered (domain.update_draft) so it is asked only once.
    """
    from apps.studio.domain import draft_jobs, unpack, update_draft
    draft = GenerationDraft.objects.filter(account=account, id=draft_id, expires_at__gt=timezone.now()).first()
    if not draft:
        raise DomainError('controls_expired', 409)
    data = unpack(draft.encrypted_data)
    # A change is decided by its request alone. ➖/➕ and language buttons left
    # on a review sent before they were taken off a change are old buttons.
    if data.get('revision'):
        raise DomainError('controls_expired', 409)
    # A deck already made is changed with ✏️ Edit under its file. A review of it
    # still in the chat would build it anew, over the slides edited since.
    if draft.feature_id == SLIDES and (data.get('_render') or draft_jobs(account, draft.id, ('succeeded', 'no_op'))):
        raise DomainError('generation_finished', 409)
    fields = change(data)
    draft = update_draft(account, draft.id, {'version': draft.version, **fields}, **({'details': True} if details else {}))
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


def facts_of(draft):
    """What a new CV gives and lacks: {'given', 'missing', 'optional_missing'} (apps/studio/cv/content.require_facts).

    {} for a change, which is decided by its request alone, and for a draft
    made before this was kept.
    """
    from apps.studio.domain import unpack
    data = unpack(draft.encrypted_data)
    found = data.get('cv_facts')
    return {} if data.get('revision') or not isinstance(found, dict) else found


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


def cv_reading(account, ids, way=''):
    """Where a new CV's files stand with the reader while the chat waits for them: None once none of them waits.

    Each file is read by `runreader` (apps/studio/cv/reads.py), never here.
    {'reading': True, 'ahead': 0} while one of them is being read, else
    {'reading': False, 'ahead': n}: the reads of other files that finish
    before the first of them still queued, the accounts taking turns. Its
    own files are not counted: they are not ahead of the customer. With
    `way`, as the chat begins to wait, the files are checked for that way
    and one without a read is queued for one (an upload from before the
    queue). That is done here, outside the draft's transaction, which would
    take a read queued in it back with its refusal (reads.ensure_ids). None
    as well for files refused before any is read: the draft says why.
    """
    from apps.studio.cv import reads, sources as cv_sources
    from apps.studio.models import CvSourceRead
    try:
        ids = [str(uuid.UUID(str(identifier))) for identifier in ids or []]
    except ValueError:
        return None
    if not ids:
        return None
    if way:
        if way not in cv_sources.KINDS:
            return None
        try:
            assets, _ = cv_sources.checked(account, ids, way)
        except DomainError:
            return None
        rows = list(reads.ensure(account, assets, results=False).values())
    else:
        rows = list(CvSourceRead.objects.filter(account=account, asset_id__in=ids).defer('encrypted_result'))
    left = [row for row in rows if row.status in reads.WAITING]
    if not left:
        return None
    if any(row.status == reads.READING for row in left):
        return {'reading': True, 'ahead': 0}
    order, reading = reads.queue()
    place = reads.places(order, reading)
    return {'reading': False, 'ahead': min(reads.ahead_of(row, place, len(order) + reading) for row in left)}


def cv_readable(account, ids, way):
    """Whether a new CV's files, as the reader read them, have words enough for a CV.

    True when they will be refused for something else before any is read:
    the draft says why. A file the reader could not read gives no words.
    """
    from apps.studio.cv import reads, sources as cv_sources
    try:
        assets, kinds = cv_sources.checked(account, [str(identifier) for identifier in ids], way)
    except (DomainError, KeyError):
        return True
    rows = reads.ensure(account, assets)
    try:
        cv_sources.excerpts_of(cv_sources.entries(assets, kinds, account),
                               [reads.result_of(rows[str(asset.id)]) for asset in assets])
    except DomainError:
        return False
    return True


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
    kept = set(_live(account, ids))
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


def is_example(description, category=''):
    """Whether a description is one of the bot's own examples, sent back unchanged.

    In a category's flow (`category`) the catalogue's examples are ours too:
    its question shows them, and its pool holds more of the same. Without one
    only the services' own examples are looked at, as before categories.
    """
    import difflib
    from .ux_copy import PROMPT_EXAMPLES
    text = ' '.join((description or '').lower().split())
    if len(text) < 40:
        return False
    known = [example for examples in PROMPT_EXAMPLES.values() for translations in examples for example in translations]
    # A category that can no longer be picked (the switch turned off or the
    # category unticked while the customer wrote) is dropped when the draft is
    # made (build), so its examples are not ours either; and with nothing
    # live, nothing here loads the catalogue.
    if category and (category_live(DOCUMENT, category) or category_live(SLIDES, category)):
        from apps.studio import categories
        known += sorted(categories.examples())
    for example in known:
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


def _made_from(account, draft_id):
    return Job.objects.filter(account=account, feature_id__in=(*SERVICES, *RENDER_IDS), status='succeeded',
                              parameters__generation_draft_id=str(draft_id)).order_by('-created_at')


def delivered(account, draft_id, kind=None):
    """(job, file) last made from this draft, as `kind` or else as its service makes it, while the server still keeps the file; else (None, None).

    A deck sent again is the deck from then on, as PowerPoint when it was sent as
    one. An older file lacks what was edited, so a send without one ends the search.
    """
    from apps.studio.keeping import held_past_its_day
    now = timezone.now()
    for job in _made_from(account, draft_id):
        made = FORMAT.get(job.feature_id, 'pptx')
        for artifact in job.artifacts.select_related('file'):
            asset = artifact.file
            # A file kept only as another document's source is not sent again after its day (keeping.py).
            if (asset.state == 'ready' and asset.expires_at > now and asset.metadata.get('kind') == (kind or made)
                    and not held_past_its_day(asset, now)):
                return job, asset
        if job.feature_id in RENDER_IDS or made != (kind or made):
            break
    return None, None


def sent_edited(account, draft_id):
    """Whether the newest file of this draft is the customer's own edit sent again: a file older than it is not the same."""
    return _made_from(account, draft_id).values_list('feature_id', flat=True).first() in RENDER_IDS


def in_chat(account, draft_id, kind=None, older=False):
    """Whether a file made from this draft went to the chat as itself (delivery.sent_in_chat), as `kind` when one is
    named; `older`, one older than its newest file. What the chat says of a copy there is said only then: a document
    made on the web, or sent as a link, has none."""
    from .delivery import sent_in_chat
    jobs = _made_from(account, draft_id)
    newest = jobs.values_list('pk', flat=True).first() if older else None
    if newest is not None:
        jobs = jobs.exclude(pk=newest)
    return sent_in_chat(jobs, kind)


def logo_gone(account, draft):
    """Whether the logo the draft names is no longer stored: a change of a document whose logo was deleted comes without it."""
    from apps.studio.branding import logo_kept
    from apps.studio.domain import unpack
    return not logo_kept(account, unpack(draft.encrypted_data))


def kept_draft(account, job):
    """The id of the kept draft an AI document, deck or CV of this task was made from, which ✏️ Make changes still changes; else ''.

    A deck sent from its editor (RENDER_IDS) names the deck it sent, kept as the deck it was made as is.
    """
    from apps.studio.domain import GENERATION_IDS, RENDER_IDS
    from apps.studio.keeping import KEPT_UNTIL
    draft_id = (job.parameters or {}).get('generation_draft_id')
    if job.feature_id not in GENERATION_IDS | RENDER_IDS or (job.parameters or {}).get('stage') == 'outline' or not draft_id:
        return ''
    kept = GenerationDraft.objects.filter(account=account, pk=draft_id, expires_at__gte=KEPT_UNTIL).exists()
    return str(draft_id) if kept else ''


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
    if asset is None or job.feature_id not in (SLIDES, EXPORT):
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
