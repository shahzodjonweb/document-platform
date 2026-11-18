"""The helper every paper family's tests import (architecture 12: each template × 3 languages × 3 cases).

A family test names its templates and lets this draw each sample and read it back:

    from tests import paper_family

    @paper_family.each(['official_ariza', 'official_tushuntirish'])
    def test_every_template_reads_well(template_id, locale, case, tmp_path):
        paper_family.assert_reads_well(template_id, locale, case, tmp_path)

    def test_every_template_has_its_samples():
        paper_family.assert_has_samples(['official_ariza', 'official_tushuntirish'])

`assert_reads_well` draws the template's sample of that case in that
language (`apps.studio.paper.sample.draw`) and fails with everything
`check.problems` finds: the paper drawn by its template and not the
emergency fallback, no block drawn plain, its page rule held, every
verified fact and fixed label it draws present, nothing outside the frame,
no overlaps, Noto only, no Cyrillic in an Uzbek or English paper, no stub
last page. `allow` takes the start of a problem the family accepts for a
reason it states beside the call; `root` reads the samples from another
folder. Samples are the family's own, in `apps/studio/paper/samples/`.
"""
import pytest

from apps.studio.categories.catalogue import LOCALES
from apps.studio.paper import sample
from apps.studio.paper.sample import CASES


def matrix(templates, *, locales=LOCALES, cases=CASES):
    """pytest params (template_id, locale, case) for every template, language and case, with readable ids."""
    return [pytest.param(template_id, locale, case, id=f'{template_id}-{locale}-{case}')
            for template_id in templates for case in cases for locale in locales]


def each(templates, **narrowed):
    """`@pytest.mark.parametrize` over `matrix(templates, ...)`, as template_id, locale and case."""
    return pytest.mark.parametrize(('template_id', 'locale', 'case'), matrix(templates, **narrowed))


def draw(template_id, locale, case, folder, *, root=None):
    """The sample drawn: a `sample.Drawn` (its artifact, content, expect and `problems()`)."""
    return sample.draw(template_id, case, locale, folder, root=root)


def problems(template_id, locale, case, folder, *, root=None, allow=()):
    """What the checker finds in the drawn sample, less the problems starting with one of `allow`."""
    found = draw(template_id, locale, case, folder, root=root).problems()
    return [problem for problem in found if not any(problem.startswith(start) for start in allow)]


def assert_reads_well(template_id, locale, case, folder, *, root=None, allow=()):
    """Fail with every problem of the drawn sample; returns the Drawn when there is none."""
    drawn = draw(template_id, locale, case, folder, root=root)
    found = [problem for problem in drawn.problems() if not any(problem.startswith(start) for start in allow)]
    assert not found, f'{drawn.note()}:\n' + '\n'.join(found)
    return drawn


def assert_has_samples(templates, *, root=None):
    """Each template has a `full` sample with content in every language (the other cases may be derived)."""
    missing = []
    for template_id in templates:
        full = sample.load(template_id, 'full', root)
        if not full:
            missing.append(f'{template_id}: no full sample')
            continue
        missing += [f'{template_id}: no {locale} content' for locale in LOCALES if not isinstance(full.get(locale),
                                                                                                  dict)]
    assert not missing, '\n'.join(missing)
