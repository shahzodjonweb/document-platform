"""Interior dewarp: printed rules come out level, everything else is untouched.

The fixtures are procedural and anonymous. Rule positions are known on the
flat paper before it is bowed, folded and photographed, and their straightness
is measured by an independent column tracker, not by the module's own
structure extraction.
"""
import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw

from processors import page_dewarp, page_rectification
from processors.document_scan import _detect, _numeric
from tests.test_image_scanning_realistic import PAGE_SIZE, _desk, _font, _shipment_form
from tests.test_image_scanning_rectification import source_and_paper_mask

FORM_RULES = (170, 192, 238, 292, 345, 399, 452, 575)


def _shipment_form_with_rules():
    """The realistic shipment form plus a header and a signature rule.

    The table alone spans 38% of the height, below the 40% the dewarp needs
    before it trusts a page-wide field; two more ordinary form rules give the
    sheet the vertical extent of a real form.
    """
    paper = _shipment_form(exposure=17)
    draw = ImageDraw.Draw(paper)
    for top in (FORM_RULES[0], FORM_RULES[-1]):
        draw.line((29, top, 419, top), fill=(42, 42, 42), width=2)
    return paper


def _photograph(rgb, alpha, margin, paper_size, corners, size):
    width, height = paper_size
    source = np.array([(margin, margin), (width - 1 + margin, margin),
                       (width - 1 + margin, height - 1 + margin),
                       (margin, height - 1 + margin)], np.float32)
    transform = cv2.getPerspectiveTransform(source, np.asarray(corners, np.float32))
    warped = cv2.warpPerspective(rgb, transform, size, flags=cv2.INTER_LINEAR)
    coverage = cv2.warpPerspective(alpha, transform, size, flags=cv2.INTER_LINEAR).astype(np.float32) / 255
    shadow = cv2.GaussianBlur(coverage, (0, 0), 5)
    background = np.clip(_desk(size) - 9 * shadow[:, :, None] * (1 - coverage[:, :, None]), 0, 255)
    photograph = background * (1 - coverage[:, :, None]) + warped * coverage[:, :, None]
    photograph = cv2.GaussianBlur(np.clip(photograph, 0, 255).astype(np.uint8), (3, 3), .55)
    return Image.fromarray(photograph, 'RGB')


LEDGER_SIZE = (520, 720)
LEDGER_RULES = tuple(range(96, 690, 48))


def _ledger(columns=None):
    width, height = LEDGER_SIZE
    paper = Image.new('RGB', LEDGER_SIZE, (214, 213, 208))
    draw = ImageDraw.Draw(paper)
    draw.text((34, 30), 'GENERIC LEDGER SAMPLE', font=_font(22), fill=(25, 25, 25))
    for index, top in enumerate(LEDGER_RULES):
        draw.line((30, top, width - 30, top), fill=(38, 38, 38), width=2)
        if top + 46 < height:
            draw.text((40, top + 14), f'Line {index:02d} sample entry for review',
                      font=_font(16), fill=(34, 34, 34))
    for left in columns or (30, width - 30):
        draw.line((left, LEDGER_RULES[0], left, LEDGER_RULES[-1]), fill=(38, 38, 38), width=2)
    return paper


def _folded_ledger_photograph():
    """Two flat panels meeting at a vertical fold: rules kink, they do not bow."""
    paper = _ledger()
    width, height = paper.size
    margin = 24
    yy, xx = np.mgrid[0:height + 2 * margin, 0:width + 2 * margin].astype(np.float32)
    fold = .55 * (width - 1)
    kink = .038 * np.maximum(0, xx - margin - fold)
    map_x = xx - margin
    map_y = yy - margin - kink
    rgb = cv2.remap(np.asarray(paper), map_x, map_y, cv2.INTER_LINEAR,
                    borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    alpha = cv2.remap(np.full((height, width), 255, np.uint8), map_x, map_y, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    corners = np.array([(120, 80), (680, 120), (650, 920), (90, 870)], np.float32)
    return _photograph(rgb, alpha, margin, paper.size, corners, (780, 1000))


TABLE_COLUMNS = (30, 250, 380, LEDGER_SIZE[0] - 30)
TABLE_CORNERS = np.array([(120, 80), (680, 120), (650, 920), (90, 870)], np.float32)


def _on_desk(rgb, map_x, map_y, margin, paper_size):
    width, height = paper_size
    sheet = cv2.remap(rgb, map_x, map_y, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0))
    alpha = cv2.remap(np.full((height, width), 255, np.uint8), map_x, map_y, cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return _photograph(sheet, alpha, margin, paper_size, TABLE_CORNERS, (780, 1000))


def _leaning_table_photograph(angle=1.2):
    """A table printed turned on its sheet: rows rise and columns lean together.

    The sheet itself is flat and its edges are straight, so the perimeter fit
    leaves the turn inside; only the rules show it, and they agree on it.
    """
    paper = _ledger(TABLE_COLUMNS)
    width, height = paper.size
    turned = paper.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=(214, 213, 208))
    margin = 24
    yy, xx = np.mgrid[0:height + 2 * margin, 0:width + 2 * margin].astype(np.float32)
    return _on_desk(np.asarray(turned), xx - margin, yy - margin, margin, paper.size)


FOLD_ROW = .42


def _fold_bump_photograph(depth=12, reach=80):
    """A sheet folded across: its columns kink sideways at the crease.

    The rows stay level and only move along themselves, so it is the
    vertical rules alone that show the fold, as a sharp bump.
    """
    paper = _ledger(TABLE_COLUMNS)
    width, height = paper.size
    margin = 24
    yy, xx = np.mgrid[0:height + 2 * margin, 0:width + 2 * margin].astype(np.float32)
    bump = depth * np.maximum(0, 1 - np.abs(yy - margin - FOLD_ROW * (height - 1)) / reach)
    return _on_desk(np.asarray(paper), xx - margin - bump, yy - margin, margin, paper.size)


def _traced(image, rules, paper_height, *, extent=(.15, .85)):
    """Each known rule's traced row per column over the middle of the page.

    A horizontal opening removes glyphs; each rule is then followed column by
    column from the middle within a small window, so tilt, bow or a kink are
    all measured, while a neighbouring rule is never jumped to.
    """
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    height, width = gray.shape
    paper = cv2.medianBlur(gray, 31).astype(np.int16)
    ink = ((paper - gray) > 45).astype(np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, 21), np.uint8)).astype(np.float32)
    columns = np.arange(round(extent[0] * width), round(extent[1] * width))
    middle = width // 2
    traces = []
    for rule in rules:
        expected = rule / (paper_height - 1) * (height - 1)
        window = np.arange(max(0, round(expected - 14)), min(height, round(expected + 15)))
        profile = ink[window, middle - 20:middle + 21].sum(axis=1)
        assert profile.max() > 0, f'rule {rule} not found near row {expected:.0f}'
        start = float(window[int(np.argmax(profile))])
        traced = {}
        for direction in (range(middle, columns[-1] + 1), range(middle - 1, columns[0] - 1, -1)):
            row = start
            for column in direction:
                low, high = max(0, round(row) - 3), min(height, round(row) + 4)
                weights = ink[low:high, column]
                if weights.sum() > 0:
                    row = float((weights * np.arange(low, high)).sum() / weights.sum())
                traced[column] = row
        traces.append((columns, np.array([traced[column] for column in columns])))
    return traces, width


def _rule_wander(image, rules, paper_height, *, extent=(.15, .85)):
    """Per known rule, the p95-p5 spread of its traced row, as a share of width."""
    traces, width = _traced(image, rules, paper_height, extent=extent)
    return np.array([float(np.percentile(rows, 95) - np.percentile(rows, 5)) / width for _, rows in traces])


def _upright_lean(image, columns, paper_width, *, extent=(.2, .8)):
    """Per known vertical rule, its lean in degrees and its kink: the spread
    (px) of its traced column about the straight line fitted through it."""
    turned = Image.fromarray(np.ascontiguousarray(np.asarray(image).transpose(1, 0, 2)))
    traces, _ = _traced(turned, columns, paper_width, extent=extent)
    leans, kinks = [], []
    for along, across in traces:
        slope, offset = np.polyfit(along, across, 1)
        residual = across - (offset + slope * along)
        leans.append(float(np.degrees(np.arctan(slope))))
        kinks.append(float(np.percentile(residual, 98) - np.percentile(residual, 2)))
    return np.array(leans), np.array(kinks)


def _detected(image):
    cv, _ = _numeric()
    details, detected = _detect(image, details=True)
    assert detected and details is not None
    return cv, details


def _documents(image, **options):
    cv, details = _detected(image)
    arguments = dict(qualified_quad=details['quad'], material_edges=details.get('material_edges'))
    return (page_rectification.rectify_page(image, details['envelope'], cv, np, **arguments),
            page_rectification.rectify_document(image, details['envelope'], cv, np,
                                                **arguments, **options))


def _field_used(monkeypatch):
    found = []
    original = page_dewarp.estimate_field

    def capture(*args, **kwargs):
        result = original(*args, **kwargs)
        found.append(result[0] is not None)
        return result

    monkeypatch.setattr(page_dewarp, 'estimate_field', capture)
    return found


def test_bowed_shipment_form_rules_come_out_level(monkeypatch):
    found = _field_used(monkeypatch)
    image, _ = source_and_paper_mask(curved=True, paper=_shipment_form_with_rules())
    baseline, (dewarped, _, _) = _documents(image)
    assert found == [True]
    assert dewarped.size == baseline.size
    before = _rule_wander(baseline, FORM_RULES, PAGE_SIZE[1])
    after = _rule_wander(dewarped, FORM_RULES, PAGE_SIZE[1])
    # The fixture must bite: the perimeter fit alone leaves the bow inside.
    assert np.median(before) > .008, before
    assert after.max() <= .005, after


def test_folded_page_kink_is_reduced(monkeypatch):
    found = _field_used(monkeypatch)
    baseline, (dewarped, _, _) = _documents(_folded_ledger_photograph())
    assert found == [True]
    rules = LEDGER_RULES[1:-1]
    before = _rule_wander(baseline, rules, LEDGER_SIZE[1])
    after = _rule_wander(dewarped, rules, LEDGER_SIZE[1])
    assert np.median(before) > .006, before
    assert np.median(after) <= .5 * np.median(before), (before, after)
    assert (after <= before + 1 / dewarped.width).all()


def test_leaning_table_comes_out_upright_and_level(monkeypatch):
    # The rules agree on a turn, so it is undone right up to the edges: the
    # outer columns run within a few percent of the sheet's sides, where
    # anchoring the field to the traced edge would leave them leaning.
    found = _field_used(monkeypatch)
    baseline, (dewarped, _, _) = _documents(_leaning_table_photograph())
    assert found == [True]
    before, _ = _upright_lean(baseline, TABLE_COLUMNS, LEDGER_SIZE[0])
    after, kinks = _upright_lean(dewarped, TABLE_COLUMNS, LEDGER_SIZE[0])
    assert np.abs(before).min() > .9, before
    assert np.abs(after).max() <= .3, after
    assert kinks.max() <= 3, kinks
    rows = _rule_wander(dewarped, LEDGER_RULES[1:-1], LEDGER_SIZE[1])
    assert np.median(_rule_wander(baseline, LEDGER_RULES[1:-1], LEDGER_SIZE[1])) > .01
    assert rows.max() <= .005, rows


def test_fold_across_the_sheet_is_straightened_out_of_the_columns(monkeypatch):
    # The rows are level, so only the columns show the fold, as a sharp
    # bump that a smooth grid between pinned edges could only round off.
    found = _field_used(monkeypatch)
    baseline, (dewarped, _, _) = _documents(_fold_bump_photograph())
    assert found == [True]
    leans, before = _upright_lean(baseline, TABLE_COLUMNS, LEDGER_SIZE[0])
    after_leans, after = _upright_lean(dewarped, TABLE_COLUMNS, LEDGER_SIZE[0])
    assert np.median(before) > 10, before
    assert after.max() <= 4 and np.median(after) <= .25 * np.median(before), (before, after)
    assert np.abs(after_leans).max() <= .3, after_leans
    rows = LEDGER_RULES[1:-1]
    assert (_rule_wander(dewarped, rows, LEDGER_SIZE[1])
            <= _rule_wander(baseline, rows, LEDGER_SIZE[1]) + 1 / dewarped.width).all()


def _inset_table_photograph(angle):
    """Level header, paragraph and closing text around one table pasted turned."""
    width, height = LEDGER_SIZE
    paper = Image.new('RGB', LEDGER_SIZE, (214, 213, 208))
    draw = ImageDraw.Draw(paper)
    draw.text((34, 24), 'GENERIC REPORT SAMPLE', font=_font(22), fill=(25, 25, 25))
    for index in range(5):
        draw.text((34, 60 + 22 * index), f'Paragraph line {index} with level running text across it here',
                  font=_font(15), fill=(30, 30, 30))
    table = Image.new('RGB', (440, 380), (214, 213, 208))
    table_draw = ImageDraw.Draw(table)
    for index, top in enumerate(range(10, 370, 45)):
        table_draw.line((10, top, 430, top), fill=(38, 38, 38), width=2)
        if top + 40 < 370:
            table_draw.text((20, top + 12), f'Row {index:02d} inset value', font=_font(15), fill=(34, 34, 34))
    for left in (10, 230, 330, 430):
        table_draw.line((left, 10, left, 10 + 45 * 7), fill=(38, 38, 38), width=2)
    paper.paste(table.rotate(angle, resample=Image.Resampling.BICUBIC, fillcolor=(214, 213, 208)), (40, 180))
    for index in range(5):
        draw.text((34, 590 + 22 * index), f'Closing line {index} with level running text across it here',
                  font=_font(15), fill=(30, 30, 30))
    margin = 24
    yy, xx = np.mgrid[0:height + 2 * margin, 0:width + 2 * margin].astype(np.float32)
    return _on_desk(np.asarray(paper), xx - margin, yy - margin, margin, paper.size)


@pytest.mark.parametrize('angle', (.5, 1.2, 2.))
def test_table_printed_askew_among_level_text_is_left_alone(monkeypatch, angle):
    # The table's rules agree on a turn, but the text above and below it is
    # level: turning or bending the page for the table would tilt the text.
    found = _field_used(monkeypatch)
    baseline, (dewarped, _, _) = _documents(_inset_table_photograph(angle))
    assert found == [False]
    assert np.array_equal(np.asarray(dewarped), np.asarray(baseline))


def _hand_ruled_ledger(amplitude):
    """A flat printed ledger with two hand-drawn dividers wobbling on their own."""
    paper = _ledger()
    draw = ImageDraw.Draw(paper)
    rows = np.arange(LEDGER_RULES[0], LEDGER_RULES[-1] + 1, 2)
    for left, phase in ((250, 0.), (380, 1.3)):
        draw.line([(left + amplitude * np.sin(y / 70. + phase) + .6 * amplitude * np.sin(y / 23. + 2 * phase), y)
                   for y in rows], fill=(30, 30, 70), width=2)
    width, height = paper.size
    margin = 24
    yy, xx = np.mgrid[0:height + 2 * margin, 0:width + 2 * margin].astype(np.float32)
    return _on_desk(np.asarray(paper), xx - margin, yy - margin, margin, paper.size)


@pytest.mark.parametrize('amplitude', (2., 5.))
def test_hand_drawn_dividers_on_a_flat_page_are_not_straightened(monkeypatch, amplitude):
    # Paper moves neighbouring columns together; two pen lines wobbling
    # independently are drawn that way, and the print beside them stays put.
    found = _field_used(monkeypatch)
    baseline, (dewarped, _, _) = _documents(_hand_ruled_ledger(amplitude))
    assert found == [False]
    assert np.array_equal(np.asarray(dewarped), np.asarray(baseline))


@pytest.mark.parametrize('angle', (.6, 1.2))
def test_turned_table_on_a_coloured_desk_leaves_no_desk_on_the_page(monkeypatch, angle):
    # Turning the content back reaches past the traced edge at the corners;
    # a wooden desk there must be masked like a neutral one, not printed.
    import sys
    from processors.document_scan import prepare_image

    def wood(size, **_):
        yy, xx = np.mgrid[0:size[1], 0:size[0]].astype(np.float32)
        grain = 4 * np.sin((yy + .16 * xx) * np.pi / 12)
        return np.stack([150 + grain, 98 + grain, 60 + grain], axis=2)

    monkeypatch.setattr(sys.modules[__name__], '_desk', wood)
    page, _ = prepare_image(_leaning_table_photograph(angle), render_long_edge=2339)
    rgb = np.asarray(page).astype(int)
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    for band in (chroma[:, :80], chroma[:, -80:], chroma[:80], chroma[-80:]):
        assert int((band > 20).sum()) == 0


def _slanted_columns():
    """A flat ledger whose middle bay carries two printed slanted strokes."""
    paper = _ledger(TABLE_COLUMNS)
    draw = ImageDraw.Draw(paper)
    for left in (275, 320):
        draw.line((left, LEDGER_RULES[1], left + 20, LEDGER_RULES[-2]), fill=(38, 38, 38), width=2)
    return paper


def test_printed_slanted_columns_on_a_flat_page_are_not_straightened(monkeypatch):
    # Upright rules on both sides over the same rows show the slant is print.
    found = _field_used(monkeypatch)
    image, _ = source_and_paper_mask(curved=False, paper=_slanted_columns())
    baseline, (dewarped, _, _) = _documents(image)
    assert found == [False]
    assert np.array_equal(np.asarray(dewarped), np.asarray(baseline))


@pytest.mark.parametrize('turn', [Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_270],
                         ids=['quarter', 'three_quarters'])
def test_sideways_bowed_form_is_dewarped_like_an_upright_one(monkeypatch, turn):
    found = _field_used(monkeypatch)
    image, _ = source_and_paper_mask(curved=True, paper=_shipment_form_with_rules())
    baseline, (dewarped, _, _) = _documents(image.transpose(turn))
    assert found == [True]
    upright = Image.Transpose.ROTATE_270 if turn == Image.Transpose.ROTATE_90 else Image.Transpose.ROTATE_90
    before = _rule_wander(baseline.transpose(upright), FORM_RULES, PAGE_SIZE[1])
    after = _rule_wander(dewarped.transpose(upright), FORM_RULES, PAGE_SIZE[1])
    assert np.median(before) > .008, before
    assert after.max() <= .005, after


def _trend_chart(slope, series):
    """A flat chart page: level header rule and axis, rising series between."""
    paper = Image.new('RGB', (450, 680), (228, 226, 220))
    draw = ImageDraw.Draw(paper)
    draw.text((30, 25), 'TREND CHART SAMPLE', font=_font(20), fill=(25, 25, 25))
    draw.line((25, 70, 425, 70), fill=(40, 40, 40), width=2)
    draw.line((40, 120, 40, 560), fill=(40, 40, 40), width=2)
    draw.line((40, 560, 420, 560), fill=(40, 40, 40), width=2)
    for index in range(series):
        top = 180 + 55 * index
        draw.line((60, top, 410, top - slope * 350), fill=(40, 40, 40), width=2)
    draw.text((40, 600), 'Figure 1: series rise steadily', font=_font(13), fill=(30, 30, 30))
    return paper


@pytest.mark.parametrize('slope,series', [(.02, 4), (.03, 4), (.03, 6), (.045, 4)])
def test_printed_sloped_lines_on_a_flat_page_are_not_levelled(monkeypatch, slope, series):
    # Tilted series outnumber the level rules, so a fit that took every
    # long line as a rule to level would straighten the chart's content.
    found = _field_used(monkeypatch)
    image, _ = source_and_paper_mask(curved=False, paper=_trend_chart(slope, series))
    baseline, (dewarped, _, _) = _documents(image)
    assert found == [False]
    assert np.array_equal(np.asarray(dewarped), np.asarray(baseline))


@pytest.mark.parametrize('paper', [None, 'ruled'], ids=['form', 'ruled_form'])
@pytest.mark.parametrize('material_edges', [False, True], ids=['luminance', 'material'])
def test_flat_pages_are_byte_identical_with_and_without_dewarp(monkeypatch, paper, material_edges):
    found = _field_used(monkeypatch)
    image, _ = source_and_paper_mask(curved=False,
                                     paper=_shipment_form_with_rules() if paper else None)
    cv, details = _detected(image)
    arguments = dict(qualified_quad=details['quad'], material_edges=material_edges)
    baseline = page_rectification.rectify_page(image, details['envelope'], cv, np, **arguments)
    fit = page_rectification._fit(image, details['envelope'], cv, np, **arguments)
    rendered = page_rectification._render(image, fit, fit['size'])
    dewarped, _, _ = page_rectification.rectify_document(image, details['envelope'], cv, np, **arguments)
    assert found == [False]
    assert np.array_equal(np.asarray(rendered), np.asarray(baseline))
    assert np.array_equal(np.asarray(dewarped), np.asarray(baseline))


def _never_rendered(field):
    raise AssertionError('A page without enough level structure must not be re-rendered')


def _paper(seed):
    rng = np.random.default_rng(seed)
    light = 205 + 12 * np.linspace(0, 1, 700)[None, :] + rng.normal(0, 1.4, (900, 700))
    return np.repeat(np.clip(light, 0, 255).astype(np.uint8)[:, :, None], 3, axis=2)


def _identity_donor(u, v):
    return [np.broadcast_to(u * 699, np.broadcast(u, v).shape).astype(np.float32),
            np.broadcast_to(v * 899, np.broadcast(u, v).shape).astype(np.float32)]


def test_text_free_page_skips():
    preview = np.ascontiguousarray(_paper(5))
    field, rendered = page_dewarp.estimate_field(preview, cv2, np, render=_never_rendered,
                                                 donor=_identity_donor, pose_shape=(900, 700))
    assert field is None and rendered is None


def test_random_blob_page_skips():
    preview = _paper(9)
    rng = np.random.default_rng(31)
    for _ in range(160):
        center = (int(rng.integers(20, 680)), int(rng.integers(20, 880)))
        axes = (int(rng.integers(3, 40)), int(rng.integers(3, 40)))
        cv2.ellipse(preview, center, axes, float(rng.uniform(0, 180)), 0, 360,
                    tuple(int(value) for value in rng.integers(20, 120, 3)), -1)
    field, rendered = page_dewarp.estimate_field(preview, cv2, np, render=_never_rendered,
                                                 donor=_identity_donor, pose_shape=(900, 700))
    assert field is None and rendered is None


def test_level_rules_skip_without_rendering():
    preview = _paper(11)
    for top in range(120, 820, 60):
        cv2.line(preview, (40, top), (660, top), (40, 40, 40), 2)
    field, _ = page_dewarp.estimate_field(preview, cv2, np, render=_never_rendered,
                                          donor=_identity_donor, pose_shape=(900, 700))
    assert field is None


def test_long_edge_upsamples_and_exterior_matches_output():
    image, _ = source_and_paper_mask(curved=True, paper=_shipment_form_with_rules())
    baseline, (larger, exterior, _) = _documents(image, long_edge=2339)
    scale = larger.height / baseline.height
    # A 665-pixel page may grow at most threefold, keeping its aspect ratio.
    assert 2.9 <= scale <= 3.01
    assert abs(larger.width / larger.height - baseline.width / baseline.height) < .01
    if exterior is not None:
        assert exterior.dtype == np.uint8 and exterior.shape == (larger.height, larger.width)
    # A target below the natural size never shrinks the page.
    _, (natural, _, _) = _documents(image)
    _, (unchanged, _, _) = _documents(image, long_edge=100)
    assert np.array_equal(np.asarray(unchanged), np.asarray(natural))


def test_edge_exterior_marks_a_desk_rim_but_not_a_printed_bar():
    preview = np.full((800, 600, 3), 228, np.uint8)
    preview[:, :4] = 95                     # neutral desk left along the left edge
    preview[:30, 100:500] = 20              # a printed header bar touching the top
    mask = page_dewarp.edge_exterior(preview, cv2, np)
    assert mask is not None and mask.dtype == np.uint8
    assert (mask[100:700, :5] > 0).all()    # the rim plus one blended pixel
    assert not (mask[100:700, 6:] > 0).any()
    assert not (mask[:40, 150:450] > 0).any()
    # Coloured paper edges are not desk.
    tinted = np.full((800, 600, 3), 228, np.uint8)
    tinted[:, :4] = (150, 60, 60)
    assert page_dewarp.edge_exterior(tinted, cv2, np) is None
    assert page_dewarp.edge_exterior(np.full((800, 600, 3), 228, np.uint8), cv2, np) is None


def test_exposed_exterior_masks_desk_past_the_trace_but_not_paper_or_print():
    # A field reaching 8 px past the left edge: a wooden desk there is
    # masked whatever its colour; where the trace cut into the sheet, the
    # paper and a table rule printed on it stay.
    width, height = 600, 800
    shift = 8 / (width - 1)
    field = page_dewarp.Field(np.full((4, 4), -shift), np.zeros((4, 4)), np)
    preview = np.full((height, width, 3), 228, np.uint8)
    preview[:400, :8] = (150, 98, 60)        # desk beside the upper half
    preview[400:, 4:6] = 30                  # a rule on paper beside the lower half
    mask = page_dewarp.exposed_exterior(preview, field, cv2, np)
    assert mask is not None
    assert (mask[20:380, :8] > 0).all()
    assert not (mask[420:780, 4:] > 0).any(), 'Paper and print past the trace stay'
    assert not (mask[:, 10:] > 0).any()
    still = page_dewarp.Field(np.zeros((4, 4)), np.zeros((4, 4)), np)
    assert page_dewarp.exposed_exterior(preview, still, cv2, np) is None


def test_edge_exterior_covers_a_desk_wedge_deeper_than_the_cap():
    # A bowed sheet edge leaves a desk wedge that ramps out of the rim and
    # peaks just past the cap (9 px here); its deepest part must not be
    # mistaken for a printed bar and left to print black.
    height, width = 800, 600
    cap = round(min(height, width) * page_dewarp.EXTERIOR_CAP)
    rows = np.arange(height)
    depth = 4 + np.round(np.clip(1 - np.abs(rows - 400) / 150, 0, None) * (1.1 * cap + 1 - 4)).astype(int)
    assert depth.max() > cap
    preview = np.full((height, width, 3), 228, np.uint8)
    for row in rows:
        preview[row, width - depth[row]:] = 30
    preview[:20, 100:500] = 20              # a printed header bar still touches the top
    preview[:3, :] = 95                     # inside a thin desk rim along that edge
    mask = page_dewarp.edge_exterior(preview, cv2, np)
    assert mask is not None
    for row in range(30, height - 30):
        assert (mask[row, width - depth[row]:] > 0).all(), row
    assert not (mask[100:700, :width - 2 * cap - 2] > 0).any()
    assert not (mask[5:40, 150:450] > 0).any()


@pytest.mark.parametrize('photograph', ['bowed_form', 'leaning_table'])
@pytest.mark.parametrize('material_edges', [False, True], ids=['luminance', 'material'])
def test_dewarped_render_samples_the_original_once_in_bounded_strips(monkeypatch, material_edges, photograph):
    # The leaning table's field also moves content sideways, up to the edges.
    found = _field_used(monkeypatch)
    if photograph == 'bowed_form':
        photograph, _ = source_and_paper_mask(curved=True, paper=_shipment_form_with_rules())
    else:
        photograph = _leaning_table_photograph()
    cv, details = _detected(photograph)
    source = photograph.resize((photograph.width * 4, photograph.height * 4), Image.Resampling.LANCZOS)
    envelope = details['envelope'] * 4
    qualified_quad = details['quad'] * 4
    original_crop = Image.Image.crop
    original_remap = cv2.remap
    original_warp = cv2.warpPerspective
    original_median = cv2.medianBlur
    source_crops = []
    sampling = []
    previews = []
    geometry = []

    def portable_median(array, kernel, *args, **kwargs):
        if kernel > 5:
            assert array.dtype == np.uint8, 'Use the portable OpenCV median input type'
        return original_median(array, kernel, *args, **kwargs)

    def capture_crop(image, box=None):
        result = original_crop(image, box)
        if image is source:
            source_crops.append(np.asarray(result))
        return result

    def capture_geometry(array, matrix, destination, *args, **kwargs):
        geometry.append((array.shape[:2], destination))
        return original_warp(array, matrix, destination, *args, **kwargs)

    def capture_sampling(array, map_x, map_y, *args, **kwargs):
        assert map_x.shape == map_y.shape
        assert np.isfinite(map_x).all() and np.isfinite(map_y).all()
        if source_crops and array.shape == source_crops[0].shape and np.array_equal(array, source_crops[0]):
            assert map_x.size <= page_rectification.STRIP_PIXELS
            assert float(map_x.min()) >= 0 and float(map_x.max()) < array.shape[1]
            assert float(map_y.min()) >= 0 and float(map_y.max()) < array.shape[0]
            sampling.append((id(array), map_x.shape))
        else:
            # Evidence is read on the bounded pose only, never on the source.
            assert max(array.shape[:2]) <= page_rectification.POSE_SIDE
            assert max(map_x.shape) <= page_rectification.POSE_SIDE
            previews.append(map_x.shape)
        return original_remap(array, map_x, map_y, *args, **kwargs)

    monkeypatch.setattr(Image.Image, 'crop', capture_crop)
    monkeypatch.setattr(cv2, 'warpPerspective', capture_geometry)
    monkeypatch.setattr(cv2, 'remap', capture_sampling)
    monkeypatch.setattr(cv2, 'medianBlur', portable_median)
    monkeypatch.setattr(page_rectification, 'MAX_PIXELS', 2_000_000)
    result, exterior, _ = page_rectification.rectify_document(
        source, envelope, cv, np, qualified_quad=qualified_quad,
        material_edges=material_edges, long_edge=4000)
    assert found == [True], 'The bounded render must carry an actual dewarp field'
    assert result.width * result.height <= page_rectification.MAX_PIXELS
    assert len(source_crops) == 1
    assert len(sampling) >= 2
    assert len({identifier for identifier, _ in sampling}) == 1
    assert sum(height * width for _, (height, width) in sampling) == result.width * result.height
    assert previews
    assert geometry and all(max(shape) <= page_rectification.POSE_SIDE for shape, _ in geometry)
    if exterior is not None:
        assert exterior.shape == (result.height, result.width)


def test_render_reaching_past_the_pose_still_reads_one_bounded_crop(monkeypatch):
    # A field may sample a little outside the traced sheet, beyond the pose's
    # own margin; the single source crop grows to cover it and every map
    # stays inside that crop.
    photograph = _leaning_table_photograph()
    cv, details = _detected(photograph)
    fit = page_rectification._fit(photograph, details['envelope'], cv, np, qualified_quad=details['quad'],
                                  material_edges=details.get('material_edges'))
    nodes = page_dewarp._grid(fit['pose'].shape[:2])
    shift = -.9 * page_dewarp.MAX_SHIFT
    field = page_dewarp.Field(np.full(nodes, shift), np.full(nodes, shift), np)
    original_crop = Image.Image.crop
    original_remap = cv2.remap
    boxes, maps = [], []

    def capture_crop(image, box=None):
        if image is photograph:
            boxes.append(box)
        return original_crop(image, box)

    def capture_remap(array, map_x, map_y, *args, **kwargs):
        maps.append((array.shape, float(map_x.min()), float(map_x.max()), float(map_y.min()), float(map_y.max())))
        return original_remap(array, map_x, map_y, *args, **kwargs)

    monkeypatch.setattr(Image.Image, 'crop', capture_crop)
    monkeypatch.setattr(cv2, 'remap', capture_remap)
    rendered = page_rectification._render(photograph, fit, fit['size'], field=field)
    assert rendered.size == fit['size']
    assert len(boxes) == 1
    pose_low = np.floor(fit['pose_quad'].min(axis=0) - 4)
    assert boxes[0][0] < pose_low[0] and boxes[0][1] < pose_low[1], (boxes, pose_low)
    for shape, low_x, high_x, low_y, high_y in maps:
        assert 0 <= low_x and high_x <= shape[1] - 1 and 0 <= low_y and high_y <= shape[0] - 1
