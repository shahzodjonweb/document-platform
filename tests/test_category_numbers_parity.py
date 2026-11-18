"""Numbers read as c491da9 read them: the customer's side gives exactly its values and place keys, and a paper's
figure is checked at least as it checked it (the owner's rule for stage 2: a leak c491da9 did not have is never
acceptable).

`fixtures/categories/numbers_c491da9.py` is c491da9's apps/studio/categories/numbers.py byte for byte (its git blob id
is checked), loaded with its two relative imports made absolute. The corpus is every text of the grounding matrix (its
string constants, and its cases' briefs, values, facts and parts) and every text numbers.values was called with across
the stage-2 audit probes that the matrix does not already hold (`fixtures/categories/numbers_corpus.json`).
"""
import ast
import hashlib
import json
import types
from pathlib import Path

import pytest

from apps.studio.categories import numbers

HERE = Path(__file__).parent
FIXTURES = HERE / 'fixtures' / 'categories'
# git rev-parse c491da9:apps/studio/categories/numbers.py
FIRST_BLOB = '4e362cbdc83927069b547a224b26cd64f5d59b1f'


@pytest.fixture(scope='module')
def first():
    """c491da9's numbers module."""
    path = FIXTURES / 'numbers_c491da9.py'
    source = path.read_bytes()
    assert hashlib.sha1(b'blob %d\0' % len(source) + source).hexdigest() == FIRST_BLOB, \
        'the fixture is c491da9\'s numbers.py, unchanged'
    text = source.decode('utf-8').replace('from ..language import', 'from apps.studio.language import') \
        .replace('from ..uzbek import', 'from apps.studio.uzbek import')
    module = types.ModuleType('numbers_c491da9')
    exec(compile(text, str(path), 'exec'), module.__dict__)  # noqa: S102 - the repository's own frozen source
    return module


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _matrix():
    import test_category_grounding_matrix as matrix
    return matrix


def _corpus():
    """Every text of the grounding matrix and of the probes' corpus, once."""
    matrix = _matrix()
    source = (HERE / 'test_category_grounding_matrix.py').read_text('utf-8')
    texts = {node.value for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for case in matrix.CASES:
        texts.update(_strings((case.brief, case.value, case.facts, case.parts, case.row)))
    for change in matrix.CHANGES:
        texts.update(_strings((change.brief, change.first, change.request, change.second, change.value)))
    for cover in matrix.COVERS:
        texts.update((cover.line, cover.said))
    texts.update(json.loads((FIXTURES / 'numbers_corpus.json').read_text('utf-8')))
    return sorted(text for text in texts if text.strip())


def test_the_first_reading_is_c491da9s_own(first):
    """The first reading's ordinals are c491da9's patterns, character for character."""
    for now, then in (('FIRST_PLACE', 'ORDINAL_PLACE'), ('FIRST_SPOT', 'ORDINAL_SPOT'), ('FIRST_RANK', 'ORDINAL_RANK'),
                      ('FIRST_CONTEST', 'CONTEST'), ('FIRST_ORDINAL_DATE', 'ORDINAL_DATE'),
                      ('SPOT_EXEMPT', 'SPOT_EXEMPT')):
        assert (getattr(numbers, now).pattern, getattr(numbers, now).flags) == \
            (getattr(first, then).pattern, getattr(first, then).flags), now
    assert numbers.FIRST_RU_ORDINAL_ENDING == first.RU_ORDINAL_ENDING


def _first_values(first, text):
    """c491da9's values of `text`, or None where it failed: an ordinal's words that make no ordinal ("kechinchi
    o‘rinni") stopped its reading."""
    try:
        return first.values(text)
    except StopIteration:
        return None


def test_the_customers_values_are_c491da9s_with_place_keys_alone(first):
    corpus = _corpus()
    assert len(corpus) > 3000
    differ, places = [], 0
    for text in corpus:
        before = _first_values(first, text)
        if before is None:
            continue
        now = numbers.values(text)
        added = now - before
        places += bool(added)
        if before - now or any(not key.startswith(numbers.PLACE) for key in added):
            differ.append((text, sorted(before - now), sorted(key for key in added if not key.startswith('place:'))))
    assert not differ, f'{len(differ)} texts give other values than c491da9 (text, missing, added): {differ[:5]}'
    assert places > 100, 'the placings read since give their place keys'


def test_a_place_key_is_never_a_figure():
    for text in ('U olimpiadada birinchi bo‘ldi.', 'I was first in sales last year.', 'Она стала третьей на олимпиаде.',
                 'Она вошла в тройку лучших на олимпиаде.', 'Bu tanlov u uchun birinchi edi.'):
        keys = numbers.values(text)
        assert keys and all(key.startswith(numbers.PLACE) for key in keys), (text, keys)


def _papers():
    """{the paper's text: the briefs it is read under}: each matrix case's brief for every text of its value, and every
    corpus text under a few briefs that name placings, figures and dates."""
    matrix = _matrix()
    papers = {}
    for case in matrix.CASES:
        for text in _strings((case.value, case.facts, case.parts, case.row)):
            papers.setdefault(text, set()).add(case.brief)
    briefs = sorted({case.brief for case in matrix.CASES if numbers.ORDINAL_HINT.search(case.brief)
                     or any(character.isdigit() for character in case.brief)})[::25]
    briefs += ['', 'Bu tanlov u uchun birinchi edi.', 'She was not first in the ranking, but she improved a lot.',
               'Эта олимпиада стала третьей в её жизни.', 'Она вошла в тройку лучших.']
    for text in _corpus():
        papers.setdefault(text, set()).update(briefs)
    return papers


def test_a_papers_figure_is_blanked_wherever_c491da9_blanked_it(first):
    """Every number c491da9 reads in a paper and does not find in the customer's values lies inside a number read now
    that is not found either: blanked whole, whatever was read since."""
    missed, values = [], {}
    for paper, briefs in sorted(_papers().items()):
        for words in (False, True):
            for uzbek_cyrillic in (False, True):
                try:
                    before = first.found(paper, words=words, uzbek_cyrillic=uzbek_cyrillic)
                except StopIteration:
                    continue
                if not before:
                    continue
                now = numbers.found(paper, words=words, uzbek_cyrillic=uzbek_cyrillic)
                for brief in sorted(briefs):
                    if brief not in values:
                        values[brief] = (_first_values(first, brief), numbers.values(brief))
                    before_values, now_values = values[brief]
                    if before_values is None:
                        continue
                    blanked = [number for number in now if not numbers.known(number, now_values)]
                    for number in before:
                        if not first.known(number, before_values) and not any(
                                held.start <= number.start and number.end <= held.end for held in blanked):
                            missed.append((brief, paper, words, paper[number.start:number.end]))
    assert not missed, f'{len(missed)} figures c491da9 blanked are kept (brief, paper, words, figure): {missed[:5]}'
