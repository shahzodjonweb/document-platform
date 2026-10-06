"""Partial-page work stays bounded and failures preserve customer pixels."""
import cv2
import numpy as np

from processors.document_scan import prepare_image
from scripts.operations.partial_scan_fixtures import partial_document_fixture


def test_failed_partial_segmentation_does_not_loop_or_modify_the_photo(monkeypatch):
    source = partial_document_fixture().image
    calls = []

    def fail_segmentation(rgb, mask, rectangle, background, foreground, iterations, mode):
        calls.append((rgb.shape, iterations, mode))
        raise cv2.error('Deliberate model failure')

    monkeypatch.setattr(cv2, 'grabCut', fail_segmentation)
    result, metadata = prepare_image(source)
    assert 1 <= len(calls) <= 2, 'Complete and clipped proposals each have one bounded attempt'
    assert sum(iterations for _, iterations, _ in calls) <= 6
    for shape, iterations, mode in calls:
        assert max(shape[:2]) <= 512 and iterations <= 3
    assert len([call for call in calls if call[2] == cv2.GC_INIT_WITH_MASK]) <= 1
    assert result.size == source.size and result.tobytes() == source.tobytes()
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': False}


def test_partial_cleanup_bounds_segmentation_and_full_resolution_work(monkeypatch):
    source = partial_document_fixture().image
    original_grabcut, original_divide, original_remap = cv2.grabCut, cv2.divide, cv2.remap
    segments, strips = [], []

    def grabcut(rgb, mask, rectangle, background, foreground, iterations, mode):
        segments.append((rgb.shape, iterations))
        return original_grabcut(rgb, mask, rectangle, background, foreground, iterations, mode)

    def divide(left, right, **kwargs):
        strips.append(left.size)
        return original_divide(left, right, **kwargs)

    def remap(source, map_x, map_y, *args, **kwargs):
        assert max(source.shape[:2]) <= 512, 'Enhancement geometry must stay on its thumbnail'
        strips.append(map_x.size)
        return original_remap(source, map_x, map_y, *args, **kwargs)

    monkeypatch.setattr(cv2, 'grabCut', grabcut)
    monkeypatch.setattr(cv2, 'divide', divide)
    monkeypatch.setattr(cv2, 'remap', remap)
    result, flags = prepare_image(source)
    assert flags['document_detected'] and flags['enhanced']
    assert 1 <= len(segments) <= 2 and sum(item[1] for item in segments) <= 6
    assert all(max(shape[:2]) <= 512 and iterations <= 3 for shape, iterations in segments)
    assert strips and max(strips) <= 1_000_000
    assert result.width * result.height <= source.width * source.height
    assert np.any(np.asarray(result) > 240), 'The bounded path still improves paper readability'
