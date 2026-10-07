"""The anonymous live oracle must reject white matte without rectification."""
import numpy as np
import pytest
from PIL import Image

from scripts.operations.rectified_partial_scan_fixtures import (
    RectifiedFailure, rectified_partial_fixture, validate_rectified_partial_output,
)


@pytest.fixture(scope='module')
def fixture():
    return rectified_partial_fixture()


def reference_rectangle(fixture):
    pixels = np.asarray(fixture.flat_image).copy()
    pixels[~fixture.visible_flat] = 255
    # Only the independently observed camera portion is present. Missing
    # continuation carries white paper, never invented document text.
    bottom = np.flatnonzero(fixture.visible_flat.any(axis=1))[-1] + 1
    return Image.fromarray(pixels[:bottom])


def test_oracle_accepts_independent_flat_visible_document(fixture):
    image = reference_rectangle(fixture)
    flags = validate_rectified_partial_output(fixture, image, enhanced=False)
    assert flags['rectified_page_verified'] and flags['visible_marks_preserved']
    assert flags['rectangular_paper_edges_verified'] and flags['colored_ink_preserved']


def test_oracle_rejects_unchanged_curved_photo(fixture):
    with pytest.raises(RectifiedFailure):
        validate_rectified_partial_output(fixture, fixture.image, enhanced=False)


def test_oracle_rejects_white_matte_that_leaves_the_paper_edge_curved(fixture):
    pixels = np.asarray(fixture.image).copy()
    pixels[fixture.paper_mask < 248] = 255
    image = Image.fromarray(pixels[156:])
    with pytest.raises(RectifiedFailure) as error:
        validate_rectified_partial_output(fixture, image, enhanced=False)
    assert 'rectified_document_' in str(error.value)


@pytest.mark.parametrize('mark', ['field_3', 'blue_note', 'signature', 'reference'])
def test_oracle_rejects_erased_visible_writing(fixture, mark):
    image = reference_rectangle(fixture)
    pixels = np.asarray(image).copy()
    mask = fixture.flat_marks[mark][:image.height] > 0
    # Remove a whole visible entry, preserving the remainder for registration.
    pixels[mask] = (235, 238, 240)
    with pytest.raises(RectifiedFailure) as error:
        validate_rectified_partial_output(fixture, Image.fromarray(pixels), enhanced=False)
    assert 'mark_erased_' in str(error.value) or 'colored_ink_' in str(error.value)


def test_oracle_rejects_erasing_one_narrow_stripe_even_when_shape_tolerance_covers_it(fixture):
    image = reference_rectangle(fixture)
    pixels = np.asarray(image).copy()
    # The generic code's fifth bar is exactly one pre-camera pixel wide. Its
    # adjacent bars fall within the glyph guard's antialiasing allowance.
    cursor = 408 + sum(width + 3 for width in (2, 4, 2, 3))
    pixels[90:128, cursor] = (235, 238, 240)
    with pytest.raises(RectifiedFailure) as error:
        validate_rectified_partial_output(fixture, Image.fromarray(pixels), enhanced=False)
    assert str(error.value) == 'rectified_document_complete_stripe_code'


def test_oracle_rejects_color_loss_without_erasing_blue_pen_strokes(fixture):
    image = reference_rectangle(fixture).convert('L').convert('RGB')
    with pytest.raises(RectifiedFailure) as error:
        validate_rectified_partial_output(fixture, image, enhanced=False)
    assert 'colored_ink_' in str(error.value)


def test_oracle_rejects_a_clipped_body_entry(fixture):
    image = reference_rectangle(fixture)
    with pytest.raises(RectifiedFailure):
        validate_rectified_partial_output(fixture, image.crop((0, 0, image.width, image.height - 150)), enhanced=False)


def test_oracle_rejects_enhancement_that_changes_geometry(fixture):
    image = reference_rectangle(fixture)
    with pytest.raises(RectifiedFailure) as error:
        validate_rectified_partial_output(fixture, image.resize((image.width - 1, image.height)),
                                          enhanced=True, crop_only=image)
    assert 'enhancement_geometry' in str(error.value)


def test_actual_default_rectifies_and_preserves_the_known_visible_document(fixture):
    from processors.document_scan import prepare_image
    crop_only, crop_flags = prepare_image(fixture.image, auto_crop=True, enhance_text=False)
    enhanced, enhanced_flags = prepare_image(fixture.image)
    assert crop_flags.get('rectified') is True and enhanced_flags.get('rectified') is True
    validate_rectified_partial_output(fixture, crop_only, enhanced=False)
    assert validate_rectified_partial_output(fixture, enhanced, enhanced=True,
                                              crop_only=crop_only)['effect_verified'] is True
