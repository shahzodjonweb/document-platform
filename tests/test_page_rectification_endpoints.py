"""A visible paper corner must bound an unsupported polynomial tail."""
import cv2
import numpy as np
from processors.page_rectification import _select_curve, _retains_writing


def _visible_wavy_edge():
    width = 300
    positions = np.linspace(width * .045, width * .955, 65).astype(int)
    # A shallow wavy perimeter remains inside the pose everywhere. The final
    # ten percent has no usable photometric peaks, although its corner is
    # independently visible and qualified by the contour detector.
    depth = 8 + 7 * np.sin(3 * np.pi * positions / (width - 1))
    rows = [[(float(y), 50., 20., 3., 100., 1.)] if x / width <= .90 else []
            for x, y in zip(positions, depth)]
    return width, positions, rows


def test_qualified_visible_corner_limits_negative_extrapolation_without_moving_body():
    width, positions, rows = _visible_wavy_edge()
    baseline = _select_curve(positions, rows, width, 53, np, stable_fit=True)
    assert baseline is not None and baseline[-1] < 1
    anchored = _select_curve(positions, rows, width, 53, np, stable_fit=True,
                             endpoint_anchors=np.array(((0., 8.), (width - 1., 8.))))
    assert anchored is not None and anchored[-1] >= 8
    assert np.array_equal(anchored[30:250], baseline[30:250])
    assert np.max(anchored - baseline) <= min(width * .04, 53 * .25)
    # A pre-known raster material boundary distinguishes the true corner from
    # desk. Clipping the negative polynomial to zero keeps background there.
    true_edge = 8 + 7 * np.sin(3 * np.pi * np.arange(width) / (width - 1))
    raster = np.indices((40, width))[0] >= true_edge[None, :]
    baseline_corner = raster[np.round(baseline[-1] + np.arange(7)).astype(int), -1]
    anchored_corner = raster[np.round(anchored[-1] + np.arange(7)).astype(int), -1]
    assert not baseline_corner.any() and anchored_corner.all()


def test_an_incorrect_qualified_corner_cannot_discard_visible_margin_glyphs():
    width, positions, rows = _visible_wavy_edge()
    baseline = _select_curve(positions, rows, width, 53, np, stable_fit=True)
    anchored = _select_curve(positions, rows, width, 53, np, stable_fit=True,
                             endpoint_anchors=np.array(((0., 8.), (width - 1., 8.))))
    # A detected corner is supporting evidence, not permission to erase ink.
    # This generic colored L makes the proposed corner adjustment unsafe.
    paper = np.full((70, width, 3), 220, np.uint8)
    paper[3:12, 290:292] = (20, 50, 145)
    paper[10:12, 290:298] = (20, 50, 145)
    assert not _retains_writing(paper, baseline, anchored, 0, cv2, np)


def test_out_of_pose_corner_evidence_is_ignored():
    width, positions, rows = _visible_wavy_edge()
    baseline = _select_curve(positions, rows, width, 53, np, stable_fit=True)
    invalid = _select_curve(positions, rows, width, 53, np, stable_fit=True,
                            endpoint_anchors=np.array(((-1., 8.), (width, 8.))))
    assert np.array_equal(invalid, baseline)
