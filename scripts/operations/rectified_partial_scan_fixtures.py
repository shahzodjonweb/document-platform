"""Independent anonymous geometry/ink oracle for rectified, clipped documents.

The known page, marks and camera projection exist before the scanner runs.
Registration uses printed body features, never scanner flags or its chosen pose.
"""
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

try:
    from service_audit_partial_scan_fixtures_py import PAGE_SIZE, PHOTO_SIZE, _paper, partial_document_fixture
except ModuleNotFoundError:
    from scripts.operations.partial_scan_fixtures import PAGE_SIZE, PHOTO_SIZE, _paper, partial_document_fixture


@dataclass
class RectifiedFixture:
    image: Image.Image
    flat_image: Image.Image
    flat_marks: dict
    visible_flat: np.ndarray
    paper_mask: np.ndarray
    camera_marks: dict


def rectified_partial_fixture():
    """A shaded, bowed generic page leaving the camera on three sides."""
    fixture = partial_document_fixture()
    flat, _, marks = _paper()
    width, height = PAGE_SIZE
    yy, xx = np.mgrid[:height, :width].astype(np.float32)
    # Invert the simulated camera's coupled sinusoidal remap. This describes
    # camera visibility only; it is not used to choose or flatten output edges.
    bx, by = xx + 46, yy + 46
    for _ in range(8):
        bx = xx + 46 + 12 * np.sin(np.pi * np.clip((by - 46) / (height - 1), 0, 1))
        by = yy + 46 + 34 * np.sin(np.pi * np.clip((bx - 46) / (width - 1), 0, 1))
    source = np.array(((46, 46), (width - 1 + 46, 46),
                       (width - 1 + 46, height - 1 + 46), (46, height - 1 + 46)), np.float32)
    camera = np.array(((-45, 181), (1008, 191), (1035, 1430), (-68, 1441)), np.float32)
    transform = cv2.getPerspectiveTransform(source, camera)
    projected = cv2.perspectiveTransform(np.dstack((bx, by)).reshape(-1, 1, 2), transform).reshape(height, width, 2)
    visible = ((projected[:, :, 0] >= 1) & (projected[:, :, 0] < PHOTO_SIZE[0] - 1)
               & (projected[:, :, 1] >= 1) & (projected[:, :, 1] < PHOTO_SIZE[1] - 1))
    return RectifiedFixture(fixture.image, Image.fromarray(flat), marks, visible,
                            fixture.main_paper, fixture.marks)


class RectifiedFailure(AssertionError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _require(condition, code):
    if not condition:
        raise RectifiedFailure(code)


def _registration(fixture, image):
    visible_y, visible_x = np.where(fixture.visible_flat)
    sx = image.width / (int(visible_x.max() - visible_x.min()) + 1)
    sy = image.height / (int(visible_y.max() - visible_y.min()) + 1)
    reference = cv2.cvtColor(np.asarray(fixture.flat_image), cv2.COLOR_RGB2GRAY)
    reference = cv2.resize(reference, (round(reference.shape[1] * sx), round(reference.shape[0] * sy)))
    actual = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    detector = cv2.SIFT_create(nfeatures=3500)
    before, bd = detector.detectAndCompute(reference, None)
    after, ad = detector.detectAndCompute(actual, None)
    _require(bd is not None and ad is not None, 'rectified_document_print_registration')
    matches = cv2.BFMatcher().knnMatch(bd, ad, k=2)
    pairs = [pair[0] for pair in matches if len(pair) == 2 and pair[0].distance < .72 * pair[1].distance]
    _require(len(pairs) >= 25, 'rectified_document_print_registration')
    old = np.float32([before[p.queryIdx].pt for p in pairs]) / (sx, sy)
    old = old.astype(np.float32)
    new = np.float32([after[p.trainIdx].pt for p in pairs])
    transform, inliers = cv2.findHomography(old, new, cv2.RANSAC, 8)
    _require(transform is not None and inliers is not None and int(inliers.sum()) >= 22,
             'rectified_document_print_registration')
    supported = old[inliers.ravel() > 0]
    _require(np.ptp(supported[:, 0]) > fixture.flat_image.width * .55
             and np.ptp(supported[:, 1]) > fixture.flat_image.height * .60,
             'rectified_document_print_registration_spread')
    predicted = cv2.perspectiveTransform(old.reshape(-1, 1, 2), transform)[:, 0]
    consistent = np.linalg.norm(predicted - new, axis=1) < 35
    return transform, old[consistent], new[consistent]


def _mark_projection(mask, registration, size, supported=None):
    """Local printed feature registration tolerates the observed page's bends.

    Every local mapping is constrained to the global body registration. Ink
    itself is still required at all expected positions; erased entries cannot
    borrow an unrelated row or a scanner-provided mapping.
    """
    transform, old, new = registration
    expected = np.zeros((size[1], size[0]), np.uint8)
    yy, xx = np.where(mask)
    if not len(xx):
        return expected > 0, np.empty((0, 2))
    projected_points = []
    for top in range(int(yy.min()), int(yy.max()) + 1, 100):
        for left in range(int(xx.min()), int(xx.max()) + 1, 140):
            part = mask.copy()
            part[:, :left] = False
            part[:, left + 140:] = False
            part[:top] = False
            part[top + 100:] = False
            py, px = np.where(part)
            if not len(px):
                continue
            selected = ((old[:, 0] >= left - 100) & (old[:, 0] <= left + 240)
                        & (old[:, 1] >= top - 55) & (old[:, 1] <= top + 155))
            local = transform
            if int(selected.sum()) >= 8:
                affine, inliers = cv2.estimateAffine2D(old[selected], new[selected],
                    method=cv2.RANSAC, ransacReprojThreshold=3)
                if affine is not None and inliers is not None and int(inliers.sum()) >= 6:
                    candidate = np.vstack((affine, (0., 0., 1.)))
                    probes = np.float32(((left, top), (left + 140, top + 100))).reshape(-1, 1, 2)
                    if np.max(np.linalg.norm(cv2.perspectiveTransform(probes, candidate)
                                             - cv2.perspectiveTransform(probes, transform), axis=2)) < 35:
                        local = candidate
            warped = cv2.warpPerspective(part.astype(np.uint8), local, size, flags=cv2.INTER_NEAREST)
            points = cv2.perspectiveTransform(np.column_stack((px, py)).astype(np.float32).reshape(-1, 1, 2), local)[:, 0]
            if supported is not None and warped.any():
                wy, wx = np.where(warped > 0)
                x1, x2, y1, y2 = int(wx.min()), int(wx.max()) + 1, int(wy.min()), int(wy.max()) + 1
                dx, dy = 10, 15
                l, r = max(0, x1 - dx), min(size[0], x2 + dx)
                t, b = max(0, y1 - dy), min(size[1], y2 + dy)
                scores = cv2.matchTemplate(supported[t:b, l:r].astype(np.float32),
                    warped[y1:y2, x1:x2].astype(np.float32), cv2.TM_CCORR)
                _, _, _, location = cv2.minMaxLoc(scores)
                shift_x, shift_y = l + location[0] - x1, t + location[1] - y1
                warped = cv2.warpAffine(warped, np.float32(((1, 0, shift_x), (0, 1, shift_y))), size)
            expected = np.maximum(expected, warped)
            projected_points.append(points)
    return expected > 0, np.concatenate(projected_points)


def _writing(fixture, image, registration):
    pixels = np.asarray(image).astype(np.int16)
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    # The procedural print is at most64 RGB before photography; its paper is
    # at least140. A 120-level bound therefore distinguishes known dark writing
    # from a white replacement or shaded paper without processor thresholds.
    dark = gray < 120
    colored = pixels.max(axis=2) - pixels.min(axis=2) > 35
    ink = dark | colored
    supported = cv2.dilate(ink.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    checked = 0
    for name, mask in fixture.flat_marks.items():
        visible = (mask > 190) & fixture.visible_flat
        if int(visible.sum()) < 25:
            continue
        expected, projected = _mark_projection(visible, registration, image.size, supported)
        # Independent source-visible marks must not disappear beyond output.
        # Local feature poses carry at most3px fitting uncertainty plus camera
        # antialiasing. This is not permission to remove a written entry.
        allowance = 5
        inside = ((projected[:, 0] >= -allowance) & (projected[:, 0] <= image.width + allowance)
                  & (projected[:, 1] >= -allowance) & (projected[:, 1] <= image.height + allowance))
        _require(float(inside.mean()) >= .985 and int(expected.sum()) > 20,
                 'rectified_document_visible_mark_clipped_' + name)
        _require(float(supported[expected].mean()) >= .83,
                 'rectified_document_visible_mark_erased_' + name)
        if name in ('blue_note', 'signature'):
            blue = (pixels[:, :, 2] > pixels[:, :, 0] + 35) & (pixels[:, :, 2] > pixels[:, :, 1] + 25)
            supported_blue = cv2.dilate(blue.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
            _require(float(supported_blue[expected].mean()) >= .82,
                     'rectified_document_colored_ink_' + name)
        checked += 1
    _require(checked >= 12, 'rectified_document_visible_mark_count')
    return {'visible_marks_preserved': True, 'colored_ink_preserved': True,
            'body_print_registered': True}


def _stripe_scanlines(image, bounds):
    """Count separate stripes along individual rows, preserving camera skew."""
    gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
    left, top, right, bottom = bounds
    barcode = gray[max(0, top):min(image.height, bottom), max(0, left):min(image.width, right)]
    _require(min(barcode.shape) >= 12, 'rectified_document_stripe_region')
    barcode = barcode[len(barcode) // 4:3 * len(barcode) // 4]
    low, high = np.percentile(barcode, 15, axis=1), np.percentile(barcode, 90, axis=1)
    counts = []
    for fraction in (.35, .45, .55, .65):
        threshold = low + fraction * (high - low)
        counts.append(np.count_nonzero(np.diff((barcode < threshold[:, None]).astype(np.int8), axis=1), axis=1))
    transitions = np.max(counts, axis=0)
    transitions[high - low < 50] = 0
    return int(np.median(transitions)), int(transitions.max())


def _stripe_bounds(mask):
    y, x = np.where(mask)
    _require(x.size > 20, 'rectified_document_stripe_region')
    return int(x.min()) - 2, int(y.min()) - 3, int(x.max()) + 3, int(y.max()) + 4


def _complete_stripes(fixture, image, registration):
    # The prior camera already determines what narrow bars remain resolvable;
    # no output is required to recover detail missing from the uploaded image.
    before = _stripe_scanlines(fixture.image, _stripe_bounds(fixture.camera_marks['stripe_code'] > 190))
    visible = (fixture.flat_marks['stripe_code'] > 190) & fixture.visible_flat
    expected, _ = _mark_projection(visible, registration, image.size)
    after = _stripe_scanlines(image, _stripe_bounds(expected))
    _require(before[1] >= 30 and after[1] >= before[1] and after[0] >= before[0] - 2,
             'rectified_document_complete_stripe_code')
    return {'complete_stripe_code_verified': True}


def _straight_boundary(image):
    rgb = np.asarray(image)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # The generator's photographed desk is below 60. These are fixture facts,
    # independent of the detector. The crop-only paper is gray-blue below248.
    _require(float((gray < 75).mean()) < .19, 'rectified_document_exterior_removed')
    # Interior print is dark; broad dark exterior wedges are identified using
    # spatial support rather than a total dark-ink threshold.
    dark = (gray < 75).astype(np.uint8)
    wedges = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((17, 17), np.uint8))
    _require(float(wedges.mean()) < .002, 'rectified_document_exterior_removed')
    lo, hi = int(image.width * .08), int(image.width * .92)
    paper = (gray > 100) & (gray < 248)
    profile = []
    for x in range(lo, hi):
        positions = np.flatnonzero(paper[:max(20, image.height // 8), x])
        _require(positions.size > 0, 'rectified_document_top_paper_edge')
        profile.append(int(positions[0]))
    profile = np.asarray(profile)
    tolerance = max(4, image.height * .006)
    _require(float(np.percentile(profile, 98) - np.percentile(profile, 2)) <= tolerance
             and float(np.percentile(profile, 98)) <= tolerance,
             'rectified_document_curved_photo_edge_removed')
    return {'rectangular_paper_edges_verified': True, 'exterior_background_removed': True}


def validate_rectified_partial_output(fixture, image, *, enhanced, crop_only=None):
    """Validate actual worker pixels; enhancement shares crop-only geometry."""
    image = image.convert('RGB')
    if enhanced:
        _require(crop_only is not None and image.size == crop_only.size,
                 'rectified_document_enhancement_geometry')
        registration = _registration(fixture, crop_only)
    else:
        registration = _registration(fixture, image)
    flags = _writing(fixture, image, registration)
    flags.update(_complete_stripes(fixture, image, registration))
    if enhanced:
        # Shared dimensions alone cannot prove that an enhancement kept the
        # body in place. Independently measured source ink must remain at its
        # exact coordinates, allowing only camera/cleanup antialiasing.
        before_rgb = np.asarray(crop_only).astype(np.int16)
        before_gray = cv2.cvtColor(np.asarray(crop_only), cv2.COLOR_RGB2GRAY)
        after_gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
        known_ink = (before_gray < 100) | (before_rgb.max(axis=2) - before_rgb.min(axis=2) > 35)
        after_rgb = np.asarray(image).astype(np.int16)
        actual_ink = (after_gray < 150) | (after_rgb.max(axis=2) - after_rgb.min(axis=2) > 35)
        supported = cv2.dilate(actual_ink.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        _require(int(known_ink.sum()) > 5000 and float(supported[known_ink].mean()) >= .96,
                 'rectified_document_enhancement_geometry')
        flags.update(_straight_boundary(crop_only))
        gray = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2GRAY)
        before = cv2.cvtColor(np.asarray(crop_only), cv2.COLOR_RGB2GRAY)
        source_paper = cv2.cvtColor(np.asarray(fixture.image), cv2.COLOR_RGB2GRAY)[fixture.paper_mask > 248]
        _require(float(np.percentile(gray, 70)) > max(220, float(np.percentile(source_paper, 70)) + 20)
                 and float(np.percentile(gray, 30)) > float(np.percentile(before, 30)) + 12,
                 'rectified_document_shaded_paper_cleaned')
    else:
        flags.update(_straight_boundary(image))
    return {**flags, 'crop_verified': True, 'rectified_page_verified': True,
            'effect_verified': enhanced}
