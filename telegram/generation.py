"""AI generation driven from the chat.

Synchronous and transaction-safe, with no Telegram network calls, like
workflows.py. The studio's rules live in apps.studio.domain and are not
restated here: this module decides only what a chat can reasonably ask for and
in what order, then hands over to the same create_draft → quote → submit_job
path the web app uses.
"""
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from apps.core.errors import DomainError
from apps.core.models import FileAsset, Job
from apps.core.services import submit_job
from apps.studio.domain import GENERATION_IDS, allowed, create_draft, generation_quote, require
from apps.studio.models import GenerationDraft

# Curated order: what a customer is most likely to want comes first, because a
# chat shows a handful of buttons at a time rather than a searchable grid.
GROUPS = {
    'documents': ['ai.pdf_topic', 'ai.pptx', 'ai.pdf_text', 'ai.pdf_sources', 'ai.source_to_slides',
                  'ai.images', 'ai.rewrite', 'ai.regenerate_slide'],
    'study': ['study.summary', 'study.quiz', 'study.flashcards', 'study.definitions', 'study.pdf_qa',
              'study.handwriting', 'study.answer_key', 'study.exam_pack', 'study.revision_plan',
              'study.report_format', 'study.references', 'study.writing_feedback'],
    'school': ['school.explain', 'school.hints', 'school.examples', 'school.similar_problems',
               'school.worksheets', 'school.reading', 'school.vocabulary', 'school.weekly_pack',
               'school.check_attempt', 'school.project_outline', 'school.project_slides',
               'school.poster', 'school.adaptive'],
    'teacher': ['teacher.lesson_plan', 'teacher.worksheet', 'teacher.mcq', 'teacher.written_test',
                'teacher.homework', 'teacher.answer_key', 'teacher.lesson_pack', 'teacher.variants',
                'teacher.differentiated', 'teacher.rubric', 'teacher.reading_level',
                'teacher.syllabus', 'teacher.feedback', 'teacher.suggest_marks'],
}

# These build on something authored earlier in the web app — a saved draft with
# its sections, or a project with recorded practice. A chat has nowhere to pick
# that from, so they are listed and explained rather than silently dropped.
WEB_ONLY = {'ai.rewrite', 'ai.regenerate_slide', 'school.adaptive'}
# These read a document when one is attached, and work from typed or pasted
# material when it is not. Nothing here forces an upload.
PREFERS_PDF = {'ai.pdf_sources', 'ai.source_to_slides', 'study.pdf_qa'}
# Transcription is the exception: there is nothing to read without the picture.
NEEDS_PHOTO = {'study.handwriting'}
# Tools whose input is the customer's own writing rather than an instruction:
# the message becomes source text, not a prompt. Mirrors `sourceFirst` in the
# web app's StudioView so the same tool behaves the same on both surfaces.
SOURCE_FIRST = {'ai.pdf_text', 'ai.pdf_sources', 'ai.source_to_slides', 'study.summary',
                'study.definitions', 'study.answer_key', 'study.report_format',
                'study.references', 'study.writing_feedback', 'study.flashcards',
                'teacher.answer_key', 'teacher.syllabus', 'teacher.feedback'}
PAGE = 6


def source_first(feature_id, mode):
    """Local authoring has no model to write with, so the text must be yours."""
    if feature_id in SOURCE_FIRST:
        return True
    # A question is always an instruction, never the material, so pdf_qa is
    # excluded here exactly as it is in the web app's StudioView.
    return mode == 'local_fixture' and feature_id not in NEEDS_PHOTO | WEB_ONLY | {'study.pdf_qa'}


def group_of(feature_id):
    for name, ids in GROUPS.items():
        if feature_id in ids:
            return name
    raise DomainError('feature_unavailable', 409)


def page_of(account, group, page=0):
    """One screen of a group: the rows to draw and whether more follow."""
    ids = GROUPS.get(group)
    if ids is None:
        raise DomainError('invalid_parameters')
    start = max(0, int(page)) * PAGE
    rows = [(fid, allowed(account, fid), fid in WEB_ONLY) for fid in ids[start:start + PAGE]]
    return rows, start + PAGE < len(ids)


def kind_for(feature_id):
    return 'image' if feature_id in NEEDS_PHOTO else 'pdf'


def sources(account, feature_id, file_ids):
    """The staged files this feature can actually use, in the order sent."""
    wanted = kind_for(feature_id)
    assets = {
        str(asset.id): asset
        for asset in FileAsset.objects.filter(account=account, id__in=file_ids, state='ready',
                                              expires_at__gt=timezone.now())
    }
    ordered = [assets[key] for key in file_ids if key in assets]
    return [str(asset.id) for asset in ordered if asset.metadata.get('kind') == wanted]


def available(account, feature_id):
    """Raise the reason this feature cannot be started here, if there is one."""
    if feature_id not in GENERATION_IDS:
        raise DomainError('feature_unavailable', 409)
    if feature_id in WEB_ONLY:
        raise DomainError('generation_web_only', 409)
    require(account, feature_id)


def throttle(account, limit=10):
    """Authoring is uncharged but not free of work; cap it per account."""
    key = f'rate:bot_generation:{account.pk}'
    count = cache.get(key, 0)
    if count >= limit:
        raise DomainError('rate_limited', 429, retryable=True)
    cache.set(key, count + 1, 60)


@transaction.atomic
def build(account, feature_id, prompt, file_ids=()):
    """Author a generation draft from one chat message. Nothing is charged."""
    available(account, feature_id)
    text = (prompt or '').strip()
    ids = sources(account, feature_id, list(file_ids))
    if feature_id in NEEDS_PHOTO:
        ids = ids[-1:]  # One page at a time, as on the web.
        if not ids:
            raise DomainError('source_required')
    elif not text:
        # Everything else works from a typed message alone.
        raise DomainError('prompt_required')
    throttle(account)
    from operations.integrations import ai_config
    written = source_first(feature_id, ai_config()['mode']) and feature_id not in NEEDS_PHOTO
    question, material = text, ''
    if feature_id == 'study.pdf_qa' and not ids:
        # One message has to carry both halves the web asks for in two fields.
        # The blank line people naturally type between them is the split; with
        # no blank line the message serves as question and material alike.
        question, _, rest = text.partition('\n\n')
        material = rest.strip() or text
    data = {'feature_id': feature_id, 'source_ids': ids, 'output_locale': account.locale,
            'prompt': '' if written else question,
            'source_text': text if written else material}
    # Leave the title to the studio's own default when there is nothing to take
    # it from; an explicit None would be stringified into the document.
    if text:
        data['title'] = text.split('\n')[0][:160]
    return create_draft(account, data)


def title_of(draft):
    """Drafts are encrypted at rest; the review screen needs the title back."""
    from apps.studio.domain import unpack
    return unpack(draft.encrypted_data).get('title', '')


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
