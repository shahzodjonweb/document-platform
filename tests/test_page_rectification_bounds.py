"""Rectification samples original pixels once with bounded geometry and strips."""
import cv2
import numpy as np
import pytest
from PIL import Image

from processors.document_scan import _detect, _numeric
from processors import page_rectification
from tests.test_image_scanning_rectification import source_and_paper_mask


@pytest.mark.parametrize('curved', [False, True], ids=['flat', 'bowed'])
def test_high_resolution_rectification_uses_original_source_and_bounded_maps(monkeypatch, curved):
    # Upscale a genuine known-boundary photograph. Output must require several
    # strips; a silently skipped refinement cannot satisfy this test.
    photograph, _ = source_and_paper_mask(curved=curved)
    cv, _ = _numeric()
    details, detected = _detect(photograph, details=True)
    assert detected and details is not None
    source = photograph.resize((photograph.width * 4, photograph.height * 4),
                               Image.Resampling.LANCZOS)
    envelope = details['envelope'] * 4
    qualified_quad = details['quad'] * 4
    original_crop = Image.Image.crop
    original_remap = cv2.remap
    original_warp = cv2.warpPerspective
    source_crops = []
    sampling = []
    geometry = []

    def capture_crop(image, box=None):
        result = original_crop(image, box)
        if image is source:
            source_crops.append(np.asarray(result))
        return result

    def capture_geometry(array, matrix, destination, *args, **kwargs):
        geometry.append((array.shape[:2], destination))
        return original_warp(array, matrix, destination, *args, **kwargs)

    def capture_sampling(array, map_x, map_y, *args, **kwargs):
        assert source_crops, 'The sampling source must be a crop of the original image'
        assert np.array_equal(array, source_crops[0]), 'No thumbnail/intermediate warp may be resampled'
        assert map_x.shape == map_y.shape
        assert map_x.size <= page_rectification.STRIP_PIXELS
        assert np.isfinite(map_x).all() and np.isfinite(map_y).all()
        assert max(array.shape[:2]) < 32767
        assert float(map_x.min()) >= 0 and float(map_x.max()) < array.shape[1]
        assert float(map_y.min()) >= 0 and float(map_y.max()) < array.shape[0]
        sampling.append((id(array), map_x.shape))
        return original_remap(array, map_x, map_y, *args, **kwargs)

    monkeypatch.setattr(Image.Image, 'crop', capture_crop)
    monkeypatch.setattr(cv2, 'warpPerspective', capture_geometry)
    monkeypatch.setattr(cv2, 'remap', capture_sampling)
    # Exercise the output cap with a smaller real bound, avoiding an expensive
    # giant fixture while retaining the exact production sizing/render path.
    monkeypatch.setattr(page_rectification, 'MAX_PIXELS', 2_000_000)
    result = page_rectification.rectify_page(source, envelope, cv, np,
                                            qualified_quad=qualified_quad)
    assert result is not None, 'Bounded render must actually perform the curved-page correction'
    assert result.width * result.height <= page_rectification.MAX_PIXELS
    assert len(source_crops) == 1
    assert len(sampling) >= 2
    assert len({identifier for identifier, _ in sampling}) == 1
    assert sum(height * width for _, (height, width) in sampling) == result.width * result.height
    assert geometry and all(max(shape) <= page_rectification.POSE_SIDE for shape, _ in geometry)
    assert all(max(destination) <= page_rectification.POSE_SIDE for _, destination in geometry)
