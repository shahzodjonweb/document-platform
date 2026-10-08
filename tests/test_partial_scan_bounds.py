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
    assert result.size == source.size
    assert metadata == {'document_detected': False, 'cropped': False, 'enhanced': True}
    calls.clear()
    crop_only, flags = prepare_image(source, enhance_text=False)
    assert 1 <= len(calls) <= 2
    assert crop_only.tobytes() == source.tobytes()
    assert flags == {'document_detected': False, 'cropped': False, 'enhanced': False}


def test_partial_cleanup_bounds_segmentation_and_full_resolution_work(monkeypatch):
    source = partial_document_fixture().image
    original_grabcut, original_divide, original_remap = cv2.grabCut, cv2.divide, cv2.remap
    segments, strips, warps = [], [], []

    def grabcut(rgb, mask, rectangle, background, foreground, iterations, mode):
        segments.append((rgb.shape, iterations))
        return original_grabcut(rgb, mask, rectangle, background, foreground, iterations, mode)

    def divide(left, right, **kwargs):
        strips.append(left.size)
        return original_divide(left, right, **kwargs)

    def remap(source, map_x, map_y, *args, **kwargs):
        if source.ndim == 3 and max(source.shape[:2]) > 512:
            assert source.shape[:2] == (image.height, image.width), 'Rectification must sample the original RGB once'
            assert np.array_equal(source, np.asarray(image)), 'Never resample an already reduced camera image'
            warps.append(map_x.size)
        elif source.ndim == 2 and max(source.shape[:2]) > 512:
            assert max(source.shape[:2]) <= 1280, 'Paper pose must stay on its geometry thumbnail'
            assert max(map_x.shape) <= 512, 'Cleanup selections must return to their bounded mask'
        else:
            assert max(source.shape[:2]) <= 512, 'Mask/illumination fields must stay on their thumbnail'
        strips.append(map_x.size)
        return original_remap(source, map_x, map_y, *args, **kwargs)

    monkeypatch.setattr(cv2, 'grabCut', grabcut)
    monkeypatch.setattr(cv2, 'divide', divide)
    monkeypatch.setattr(cv2, 'remap', remap)
    image = source
    result, flags = prepare_image(image)
    assert flags['document_detected'] and flags['enhanced']
    assert 1 <= len(segments) <= 2 and sum(item[1] for item in segments) <= 6
    assert all(max(shape[:2]) <= 512 and iterations <= 3 for shape, iterations in segments)
    assert strips and max(strips) <= 1_000_000
    assert flags['rectified'] is True
    assert sum(warps) == result.width * result.height
    assert result.width * result.height <= 16_000_000
    assert np.any(np.asarray(result) > 240), 'The bounded path still improves paper readability'
