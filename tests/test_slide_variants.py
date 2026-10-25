"""Two hundred ways to draw the content layouts, each one safe to choose.

A designed deck draws each content slide in one of its layout's variants
(apps/studio/variants). Every variant is held here to what a classic drawer
is held to — the longest content its layout's guide asks for, in English,
Russian and Uzbek, without a word cut and with running text at 12 pt or more —
and to what a composition is held to: readable text, on no picture, across no
line, overlapping nothing, inside the frame, in every theme.
"""
import pytest

from apps.studio import variants
from apps.studio.slides import render_pptx
from apps.studio.variants import CLASSIC, KINDS, bench, fixtures

CATALOGUE = variants.catalogue()
IDS = sorted(f'{kind}.{name}' for kind, pool in CATALOGUE.items() for name in pool if name != CLASSIC)


def test_every_variant_module_imports_and_there_are_two_hundred_variants():
    modules = [name for _, name in variants._modules()]
    assert modules, 'no variant modules found'
    for name in modules:
        assert variants.load_module(name), f'{name} does not import'
    assert len(IDS) >= 200, len(IDS)
    for kind in KINDS:
        assert CLASSIC in CATALOGUE[kind], f'{kind} has no classic drawer in its pool'
        assert len(CATALOGUE[kind]) >= 5, f'{kind} has only {len(CATALOGUE[kind])} variants'


@pytest.mark.parametrize('variant_id', IDS)
def test_a_variant_holds_its_layout_whole_and_readable(variant_id):
    found = bench.check(variant_id, quick=True)
    assert not found, '\n'.join(found)


def _deck(sections, title='Harbour logistics review'):
    return {'title': title, 'questions': [], 'citations': [], 'sections': sections}


def _slides(kind, copies, locale='en'):
    sections = [{**fixtures.section('statement', 1, locale), 'layout': 'cover', 'id': 's0'}]
    for copy in range(copies):
        sections.append({**fixtures.light(kind, fixtures.RANGES[kind][1], locale), 'id': f's{copy + 1}'})
    return sections


def test_a_designed_deck_does_not_repeat_a_variant_while_it_has_others(tmp_path):
    result = render_pptx(_deck(_slides('cards', 5)), tmp_path / 'deck.pptx', style={'deck_design': 'midnight'})
    chosen = result['metadata']['variants'][1:]
    assert all(chosen) and len(set(chosen)) == 5, chosen
    assert all(value.startswith('cards.') for value in chosen)


def test_the_same_deck_draws_the_same_way_and_another_deck_differently(tmp_path):
    first = render_pptx(_deck(_slides('process', 3)), tmp_path / 'one.pptx', style={'deck_design': 'midnight'})
    again = render_pptx(_deck(_slides('process', 3)), tmp_path / 'two.pptx', style={'deck_design': 'midnight'})
    assert first['metadata']['variants'] == again['metadata']['variants']
    others = {tuple(render_pptx(_deck(_slides('process', 3), title=f'Deck {n}'), tmp_path / 'other.pptx',
                                style={'deck_design': 'midnight'})['metadata']['variants']) for n in range(6)}
    assert len(others) > 1


def test_a_deck_without_a_design_is_drawn_only_by_the_classic_drawers(tmp_path):
    result = render_pptx(_deck(_slides('cards', 3)), tmp_path / 'deck.pptx', style={'accent': '#255e49'})
    assert result['metadata']['variants'] == [''] * 4


@pytest.mark.parametrize('locale', fixtures.LOCALES)
def test_a_full_designed_deck_keeps_every_word(locale, tmp_path, monkeypatch):
    sections = [{**fixtures.section('statement', 1, locale), 'layout': 'cover', 'id': 's0'}]
    for number, kind in enumerate(KINDS, 1):
        sections.append({**fixtures.section(kind, fixtures.RANGES[kind][1], locale), 'id': f's{number}'})
    from apps.studio.compositions.sample import photo
    photos = {f's{number}': photo() for number, kind in enumerate(KINDS, 1) if kind.startswith('image')}
    for design in ('midnight', 'boardroom', 'lagoon'):
        result = render_pptx(_deck(sections), tmp_path / 'deck.pptx', locale=locale, style={'deck_design': design},
                             photos=photos)
        assert all(result['metadata']['variants'][1:]), result['metadata']['variants']
        with monkeypatch.context() as patch:
            patch.setattr(variants, 'choose', lambda kind, *args, **kwargs: variants.load(kind)[CLASSIC])
            classic = render_pptx(_deck(sections), tmp_path / 'classic.pptx', locale=locale,
                                  style={'deck_design': design}, photos=photos)
        # A variant never cuts: the deck loses words only where the classic drawers would.
        assert not result['shortened'] or classic['shortened'], (design, result['metadata']['variants'])


def test_a_variant_that_would_cut_or_fails_is_passed_over(tmp_path, monkeypatch):
    calls = []

    def cuts(ctx, section, lines):
        calls.append('cuts')
        ctx.shortened = True

    def breaks(ctx, section, lines):
        calls.append('breaks')
        raise RuntimeError('a variant that cannot draw this slide')

    pool = variants.load('quote')
    monkeypatch.setitem(pool, 'zz_cuts', variants.Variant('quote', 'zz_cuts', cuts))
    monkeypatch.setitem(pool, 'zz_breaks', variants.Variant('quote', 'zz_breaks', breaks))
    # Rank the two broken ones first in this deck's order.
    monkeypatch.setattr(variants, '_rank', lambda seed, kind, name: ('0' if name.startswith('zz') else '1') + name)
    result = render_pptx(_deck(_slides('quote', 1)), tmp_path / 'deck.pptx', style={'deck_design': 'midnight'})
    assert set(calls) == {'cuts', 'breaks'}
    assert result['metadata']['variants'][1] not in ('quote.zz_cuts', 'quote.zz_breaks')
    assert not result['shortened']


def test_a_variant_named_by_a_client_is_never_kept():
    from apps.studio.layouts import clean_slide_fields
    assert '_variant' not in clean_slide_fields({'layout': 'cards', '_variant': 'cards.anything'})
