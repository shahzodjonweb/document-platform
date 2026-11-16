"""What a draft without a category sends the model, pinned byte for byte.

Categories (apps/studio/categories, ai-categories) change the code that writes
every request: the prompt builder, the provider, the draft. The owner's rule is
that a customer who picks no category, or picks "Boshqa", gets exactly today's
product, so these files were written before any of that code changed and every
later change must leave them as they are.

Each case is one fixture in tests/fixtures/prompt_golden/. It holds two things,
checked by two tests:

- `draft`: the draft as today's code makes it from what the customer sent (the
  bot's request to create_draft, a change through it, an outline's payload, a
  quality repair's request). Ids that are new on every run are written as
  fixed stand-ins, the same ones in every place they appear.
- `calls`: every request body provider.generate sends for that draft, in order:
  instructions, input, schema, token budget and cache key. The input is kept
  decoded so a difference reads as a diff; the test also holds that the wire
  form is that same JSON written compactly, so nothing is lost in keeping it so.

The model is a stub that answers each body from its own schema, so a later
part sees the same earlier parts every time and the bodies never vary.

Regenerating is for the lead only, after a change that is meant to alter what
a no-category draft sends, and runs the whole module:
    pytest tests/test_prompt_golden.py --update-golden
The draft test then writes each fixture's draft and the body test its calls,
from that written draft and in the body test's own state (no customer, no
saved admin settings), so a regenerated body is made exactly as it is checked.
Parts run one after another in both, whatever LOCAL_SYNC_JOBS the shell has,
so a deck written side by side records its bodies in a fixed order.
"""
import copy
import difflib
import json
import re
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.studio import provider
from apps.studio.domain import CV, DOCUMENT, SLIDES, create_draft, pack, unpack

pytestmark = pytest.mark.django_db

HERE = Path(__file__).with_name('fixtures') / 'prompt_golden'
# Fixed, so a body never depends on what an admin set: no tuning, no account's cache scope.
CONFIG = {'model': 'gpt-golden', 'api_key': 'offline-only'}
PARALLEL = {**CONFIG, 'parallel_parts': True}
# Premium's input budget today; it decides how much of the earlier parts a later part is shown.
TOKEN_LIMIT = 120_000
# provider.generate sets this from the job's account id; a draft here has no job.
SCOPE = '4242'
UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')

# What the stub writes, in each language: short, and the same on every run.
WRITTEN = {
    'uz': ('Asosiy g‘oya {n}', 'Bu bo‘limda mavzuning {n}-jihati qisqa va aniq yoritiladi. O‘quvchi uni oson tushunadi.'),
    'ru': ('Основная мысль {n}', 'В этом разделе кратко раскрывается {n}-я сторона темы. Читатель легко её поймёт.'),
    'en': ('Main idea {n}', 'This section briefly covers aspect {n} of the topic. A reader follows it easily.'),
}


# --- The stub model ----------------------------------------------------------------

def value(definition, key, section, n, locale):
    """One field as the strict schema asks for it, with fixed text."""
    kinds = definition.get('type', 'string')
    kind = next((k for k in kinds if k != 'null'), 'null') if isinstance(kinds, list) else kinds
    if 'enum' in definition:
        kept = section.get(key)
        if kept in definition['enum']:
            return kept
        return 'bullets' if 'bullets' in definition['enum'] else definition['enum'][0]
    if kind == 'array':
        return []
    if kind == 'boolean':
        return True
    if kind in ('integer', 'number'):
        return 0
    if kind == 'object':
        return {name: value(inner, name, {}, n, locale) for name, inner in definition.get('properties', {}).items()}
    if kind != 'string':
        return None
    heading, body = WRITTEN[locale]
    text = {'heading': heading, 'body': body}.get(key, '')
    return text.format(n=n)[:definition.get('maxLength', 10_000)]


def answer(body):
    """The model's reply to `body`: every field its schema asks for, sections in the order asked."""
    schema = body['text']['format']['schema']
    sent = json.loads(body['input'])
    locale = sent['output_locale']
    asked = sent['outline']['sections']
    reply = {}
    for name, definition in schema['properties'].items():
        if name == 'sections':
            fields = definition['items']['properties']
            reply[name] = [{key: section['id'] if key == 'id' else value(fields[key], key, section, number, locale)
                            for key in fields} for number, section in enumerate(asked, 1)]
        elif name == 'title':
            reply[name] = sent['outline'].get('title') or 'Untitled'
        elif name == 'answer_supported':
            reply[name] = True
        else:
            reply[name] = value(definition, name, {}, 0, locale)
    return reply


def sending(monkeypatch):
    """Every body provider.generate sends, recorded in order and answered by the stub."""
    bodies = []

    class Response:
        def __init__(self, result): self.result = result
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps(self.result).encode()

    class Opener:
        def open(self, request, timeout):
            body = json.loads(request.data)
            # The bytes on the wire are the body written compactly, as kept here.
            assert request.data == json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()
            bodies.append(body)
            return Response({'id': f'resp_golden_{len(bodies)}', 'model': CONFIG['model'], 'status': 'completed',
                             'output': [{'type': 'message', 'content': [
                                 {'type': 'output_text', 'text': json.dumps(answer(body), ensure_ascii=False)}]}],
                             'usage': {'input_tokens': 100, 'output_tokens': 100}})
    monkeypatch.setattr(provider.urllib.request, 'build_opener', lambda _: Opener())
    return bodies


def calls(monkeypatch, case, data):
    """The bodies a job for `data` sends, each with its input decoded."""
    bodies = sending(monkeypatch)
    from apps.studio.models import ProviderAttempt
    before = set(ProviderAttempt.objects.values_list('pk', flat=True))
    provider.generate(case['config'], copy.deepcopy(data), case['feature'], f'golden-{case["name"]}',
                      token_limit=TOKEN_LIMIT)
    # One body per call: a retry would pin a reply the stub got wrong, not what a job sends.
    statuses = list(ProviderAttempt.objects.exclude(pk__in=before).values_list('status', flat=True))
    assert statuses == ['succeeded'] * len(bodies), statuses
    readable = []
    for body in bodies:
        decoded = json.loads(body['input'])
        assert body['input'] == json.dumps(decoded, ensure_ascii=False, separators=(',', ':'))
        readable.append({**body, 'input': decoded})
    return readable


# --- Drafts, made by today's code ----------------------------------------------------

def customer(settings):
    from operations.integrations import save_config
    from tests.test_platform import account
    from tests.test_studio import paid
    settings.DEBUG = True
    who = paid(settings, account())
    save_config('ai', {'mode': 'openai', 'model': CONFIG['model'], 'api_key': CONFIG['api_key']})
    # Photos on, so a deck may ask for pictures as it does in production.
    save_config('pixabay', {'pixabay_key': '4242-0123456789abcdef0123', 'enabled': 'true'})
    return who


def build(who, feature, locale, description, files=()):
    """A new draft from one chat message, as telegram/generation.build asks for it."""
    fmt = 'pptx' if feature == SLIDES else 'pdf'
    data = {'feature_id': feature, 'source_ids': [str(asset.id) for asset in files], 'output_locale': locale,
            'output_format': fmt, 'prompt': description, 'source_text': ''}
    if feature != CV:
        data['title'] = description.split('\n')[0][:160]
    return create_draft(who, data)


def generated(monkeypatch, who, draft, feature):
    """`draft` as it stands once a job wrote it with the stub, so a change can be asked of it.

    It keeps what execution.py keeps after the model's reply: the look the model
    chose, in the draft's style, and none of the seed. A deck's render pins are
    not made, as that needs the renderer; a change today reads them only for a
    design the style lacks, and the style has it here.
    """
    from apps.studio import deck_designs, doc_designs
    from apps.studio.domain import validate_content
    data = unpack(draft.encrypted_data)
    sending(monkeypatch)
    reply, _ = provider.generate(CONFIG, data, feature, 'golden-original', token_limit=TOKEN_LIMIT)
    data['content'] = validate_content(who, {key: reply[key] for key in ('title', 'sections', 'questions', 'citations')},
                                       data['output_format'], feature=feature)
    (deck_designs if data['output_format'] == 'pptx' else doc_designs).remember(data, reply)
    data.pop('_source_seed', None)
    data.pop('_render', None)
    draft.encrypted_data = pack(data)
    draft.save(update_fields=['encrypted_data'])
    return draft, data


def changed(monkeypatch, who, draft, data, request, **options):
    """A change request against a written `draft`, as telegram/generation.revise asks for it."""
    from apps.studio import domain
    # Whether the document was made is the allowance's question, asked again at the quote.
    monkeypatch.setattr(domain, 'revision_source', lambda account, identifier: (draft, data))
    return create_draft(who, {'prompt': request, 'options': {'revise_draft_id': str(draft.id), **options}})


def pdf(lines_by_page):
    """A text PDF, one list of lines per page."""
    import io
    from reportlab.pdfgen.canvas import Canvas
    out = io.BytesIO()
    page = Canvas(out, pagesize=(595, 842))
    for lines in lines_by_page:
        page.setFont('Helvetica', 12)
        for row, line in enumerate(lines):
            page.drawString(60, 780 - row * 18, line)
        page.showPage()
    page.save()
    return out.getvalue()


NOTES = [
    ['Greenfield Orchard Cooperative, field notes, spring.',
     'Twelve rows of apple trees were pruned in the first week.',
     'Drip irrigation was laid along the four eastern rows.',
     'Frost covers were used on two nights in early April.'],
    ['Bloom started in the third week, about five days late.',
     'Bees from three hives were moved to the western edge.',
     'Two rows show leaf curl and were sprayed with copper.',
     'The team plans a soil test before the summer harvest.'],
]


def make(name, settings, monkeypatch):
    """The draft for case `name`, from today's code."""
    who = customer(settings)
    if name in ('document_uz', 'document_ru', 'document_en'):
        return unpack(build(who, DOCUMENT, name[-2:], DESCRIPTIONS[name]).encrypted_data)
    if name == 'document_long':
        return unpack(build(who, DOCUMENT, 'ru', DESCRIPTIONS[name]).encrypted_data)
    if name == 'document_sources':
        from django.core.files.uploadedfile import SimpleUploadedFile
        from apps.core.services import upload_file
        notes = upload_file(who, SimpleUploadedFile('field-notes.pdf', pdf(NOTES), 'application/pdf'))
        return unpack(build(who, DOCUMENT, 'en', DESCRIPTIONS[name], files=[notes]).encrypted_data)
    if name in ('deck_photos', 'deck_outline', 'deck_change'):
        deck = build(who, SLIDES, 'uz', DESCRIPTIONS['deck_photos'])
        if name == 'deck_photos':
            return unpack(deck.encrypted_data)
        if name == 'deck_outline':
            from apps.studio.outlines import _payload
            return _payload(unpack(deck.encrypted_data))
        deck, data = generated(monkeypatch, who, deck, SLIDES)
        return unpack(changed(monkeypatch, who, deck, data, DESCRIPTIONS[name]).encrypted_data)
    if name == 'deck_parallel':
        return unpack(build(who, SLIDES, 'en', DESCRIPTIONS[name]).encrypted_data)
    if name == 'document_selected':
        document, data = generated(monkeypatch, who, build(who, DOCUMENT, 'en', DESCRIPTIONS['document_short_en']),
                                   DOCUMENT)
        return unpack(changed(monkeypatch, who, document, data, DESCRIPTIONS[name], revise_section_ids=['s4', 's2'],
                              revise_base_version=document.version).encrypted_data)
    if name == 'document_repair':
        from apps.studio import models, quality
        document, data = generated(monkeypatch, who, build(who, DOCUMENT, 'ru', DESCRIPTIONS['document_short_ru']),
                                   DOCUMENT)
        report = quality.Report()
        report.add('wrong_language', 's3')
        report.add('empty_section', 's5')
        handed = []

        def generate(config, fix, feature, request_id, **kwargs):
            handed.append(fix)
            raise RuntimeError('captured')
        monkeypatch.setattr(provider, 'generate', generate)
        monkeypatch.setattr(models.ProviderUsage.objects, 'create', lambda **fields: None)
        job = SimpleNamespace(id='golden', feature_id=DOCUMENT, account=who,
                              quote=SimpleNamespace(policy={'generation_bounds': {'input_tokens': TOKEN_LIMIT}}))
        assert quality.repair(CONFIG, data, data['content'], report, job=job) == (data['content'], 'failed')
        return handed[0]
    if name == 'cv':
        return unpack(build(who, CV, 'en', DESCRIPTIONS[name]).encrypted_data)
    raise KeyError(name)


DESCRIPTIONS = {
    'document_uz': 'Suv aylanishi va uning tabiatdagi ahamiyati haqida 10 betlik referat yozib bering',
    'document_ru': 'Реферат на 10 страниц о круговороте воды в природе и его значении для сельского хозяйства',
    'document_en': 'A 10 page report on the water cycle and why it matters for farming',
    'document_long': 'Курсовая работа на 14 страниц о том, как небольшая пекарня планирует закупки муки',
    'document_sources': 'Summarise the attached field notes as a 3 page report for the cooperative board',
    'deck_photos': 'O‘zbekistonning tog‘ daryolari haqida taqdimot, 12 ta slayd, har bir slaydda rasm bo‘lsin',
    'deck_change': 'Oxiriga xulosa slaydini qo‘shing va 3-slayddagi matnni soddaroq qiling',
    'deck_parallel': 'A 10 slide presentation on how a small bakery plans its week',
    'document_short_en': 'A 5 page guide to keeping bees in a city garden',
    'document_selected': 'Make these two pages more concrete, with one practical example each.',
    'document_short_ru': 'Доклад на 5 страниц о пользе утренней зарядки для школьников',
    'cv': ('Javlon Tursunov, accountant in Samarkand. Phone +998 00 000 00 00. Accountant at Example Trade LLC '
           'since 2021. BSc Accounting, 2016 - 2020. Excel, 1C, IFRS reporting.'),
}

# name: what it pins, the service it is sent as, and the call settings.
CASES = {
    'document_uz': ('a new 10-page document in Uzbek: one call', DOCUMENT, CONFIG),
    'document_ru': ('a new 10-page document in Russian: one call', DOCUMENT, CONFIG),
    'document_en': ('a new 10-page document in English: one call', DOCUMENT, CONFIG),
    'document_long': ('a 14-page document: two calls, the second shown what the first wrote', DOCUMENT, CONFIG),
    'document_sources': ('a document made from an uploaded PDF: its pages travel as excerpts', DOCUMENT, CONFIG),
    'deck_photos': ('a new 12-slide deck with photos: two calls', SLIDES, CONFIG),
    'deck_outline': ("that deck's outline, before the paid run", 'ai.outline', CONFIG),
    'deck_parallel': ('a 10-slide deck with parts side by side on: the plan call, then its parts', SLIDES, PARALLEL),
    'deck_change': ('a change to a written deck that adds a slide and rewords another', SLIDES, CONFIG),
    'document_selected': ('a change to two selected pages of a written document', DOCUMENT, CONFIG),
    'document_repair': ('a quality repair of two flagged pages of a written document', DOCUMENT, CONFIG),
    'cv': ('a new CV', CV, CONFIG),
}


# --- Fixtures -------------------------------------------------------------------------

def stand_ins(data):
    """`data` with every run's new ids written as fixed stand-ins, the same one wherever an id recurs."""
    from apps.studio.revisions import provider_content, source_seed
    seen = {}

    def fixed(match):
        seen.setdefault(match.group(0), f'00000000-0000-4000-8000-{len(seen) + 1:012d}')
        return seen[match.group(0)]

    def substituted(value):
        return json.loads(UUID.sub(fixed, json.dumps(value, ensure_ascii=False)))
    if '_source_seed' not in data:
        return substituted(data)
    # The seed's fingerprint covers the files' ids, so it has to be taken again over the stand-ins; left as it
    # was, it would no longer match and the body would carry the seeded pages a real job's never does. Taken
    # again, though, it would hide a wrong seed from create_draft: so the seed written is first held to the one
    # its draft calls for, and the pages blanked for the model to be the same before and after the stand-ins.
    assert data['_source_seed'] == source_seed(data), 'create_draft wrote a seed that is not its draft\'s'
    data, sent = substituted([data, provider_content(data)])
    data['_source_seed'] = source_seed(data)
    assert provider_content(data) == sent, 'the stand-ins changed which pages the model is sent'
    return data


def written(value):
    return json.dumps(value, ensure_ascii=False, indent=1) + '\n'


def case(name):
    what, feature, config = CASES[name]
    return {'name': name, 'what': what, 'feature': feature, 'config': config}


def fixture(name):
    path = HERE / f'{name}.json'
    assert path.exists(), f'{path} is missing; the lead makes it with --update-golden'
    return json.loads(path.read_text(encoding='utf-8'))


def same(expected, actual, label):
    """Byte equality of two JSON values, failing with a short diff of where they part."""
    want, got = written(expected), written(actual)
    if want == got:
        return
    diff = ''.join(list(difflib.unified_diff(want.splitlines(True), got.splitlines(True), 'golden', 'now', n=2))[:60])
    pytest.fail(f'{label} changed for a draft without a category:\n{diff}', pytrace=False)


def rewrite(name, **fields):
    """The fixture for `name` with `fields` replaced; the calls of an older one stay until the body test runs."""
    HERE.mkdir(parents=True, exist_ok=True)
    path = HERE / f'{name}.json'
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    what = case(name)
    path.write_text(written({'case': what['what'], 'feature': what['feature'],
                             'parallel_parts': 'parallel_parts' in what['config'],
                             'draft': old.get('draft'), 'calls': old.get('calls', []), **fields}), encoding='utf-8')


@pytest.fixture
def update(request):
    return request.config.getoption('--update-golden')


@pytest.fixture(autouse=True)
def parts_in_order(settings):
    # provider.side_by_side runs a deck's parts on threads without this, and the stub would record their bodies
    # in the order they finish.
    settings.LOCAL_SYNC_JOBS = True


@pytest.mark.parametrize('name', list(CASES))
def test_a_draft_without_a_category_is_made_as_before(name, settings, monkeypatch, update):
    data = stand_ins(make(name, settings, monkeypatch))
    data['_cache_scope'] = SCOPE
    if update:
        rewrite(name, draft=data)
        return
    same(fixture(name)['draft'], data, 'The draft')


@pytest.mark.parametrize('name', list(CASES))
def test_a_draft_without_a_category_sends_the_same_request_bodies(name, monkeypatch, update):
    golden = fixture(name)
    what = case(name)
    sent = calls(monkeypatch, what, golden['draft'])
    if update:
        rewrite(name, draft=golden['draft'], calls=sent)
        return
    assert golden['feature'] == what['feature']
    assert len(sent) == len(golden['calls']), f'{name}: {len(sent)} calls, {len(golden["calls"])} pinned'
    for number, (expected, actual) in enumerate(zip(golden['calls'], sent), 1):
        same(expected, actual, f'{name}, call {number} of {len(sent)}')


def test_every_case_has_its_fixture_and_no_fixture_is_left_over():
    assert sorted(path.stem for path in HERE.glob('*.json')) == sorted(CASES)
