"""Conservative processing of confidently written, frame-clipped matte paper.

prequalify uses <=1280px evidence only, without segmentation.
refine performs one <=512px, three-iteration MASK-initialized GrabCut.
This route never constructs a missing corner, homography, or whitening mask.
The returned mask can govern enhancement; the crop is only an empty-band trim.
"""
from PIL import Image
from processors import document_scan as ds


def _glyphs(gray, mask, cv, np):
    background = cv.morphologyEx(gray, cv.MORPH_CLOSE,
        cv.getStructuringElement(cv.MORPH_ELLIPSE, (31, 31)))
    residual = background.astype(np.int16) - gray.astype(np.int16)
    ink = ((residual > 25) & (mask > 0)).astype(np.uint8)
    _, labels, stats, _ = cv.connectedComponentsWithStats(ink, connectivity=8)
    h, w = gray.shape
    marks = []
    for label, (x, y, cw, ch, area) in enumerate(stats[1:], 1):
        if (3 <= area <= mask.sum() / 255 * .015 and 3 <= ch <= h * .12
                and 3 <= cw <= min(w * .15, ch * 4) and ch <= cw * 5
                and area / (cw * ch) < .70):
            padding = max(8, round(max(cw, ch) * .5))
            left, top = max(0, x - padding), max(0, y - padding)
            context = gray[top:y + ch + padding, left:x + cw + padding]
            context_ink = ink[top:y + ch + padding, left:x + cw + padding] > 0
            surrounding = context[~context_ink]
            if surrounding.size < 20 or float(np.median(surrounding)) < 115:
                continue
            if float(np.percentile(np.abs(surrounding.astype(np.float32)
                    - np.median(surrounding)), 85)) > 25:
                continue  # A physical edge/clothing fragment is not a glyph.
            marks.append((int(x), int(y), int(cw), int(ch), int(label)))
    return marks, ink, labels


def _layout(marks, shape, cv, np):
    h, w = shape
    if len(marks) < 20:
        return False
    support = np.zeros(h, np.int32)
    for x, y, cw, ch, label in marks:
        support[y:y + ch] += 1
    rows = (support >= 4).astype(np.uint8)[:, None]
    rows = cv.dilate(rows, np.ones((5, 1), np.uint8))[:, 0] > 0
    row_count = int((np.diff(np.r_[False, rows, False].astype(np.int8)) == 1).sum())
    centers = np.array([[x + cw / 2, y + ch / 2] for x, y, cw, ch, label in marks])
    span = np.ptp(centers, axis=0) / [w, h]
    return row_count >= 3 and span[0] >= .20 and span[1] >= .25


def _sources(rgb, gray, saturation, lab, cv, np):
    # Closing ordinary print before thresholding is important for a dark/tinted
    # sheet on a bright desk: raw Otsu can otherwise split ink from all paper.
    close = cv.morphologyEx(gray, cv.MORPH_CLOSE,
        cv.getStructuringElement(cv.MORPH_ELLIPSE, (31, 31)))
    for tone in (gray, close):
        _, bright = cv.threshold(cv.GaussianBlur(tone, (5, 5), 0),
                                 0, 255, cv.THRESH_BINARY + cv.THRESH_OTSU)
        for source in (bright, 255 - bright):
            source = source.copy()
            source[saturation > 140] = 0
            yield cv.morphologyEx(source, cv.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    # Coherent tint supplies a proposal when black print dominates brightness
    # thresholding. Quantized thumbnail samples are bounded and deterministic.
    sample = lab[::8, ::8, 1:].astype(np.int16)
    usable = (gray[::8, ::8] >= 135) & (saturation[::8, ::8] <= 105)
    if usable.sum() < 100:
        return
    colors = sample[usable]
    keys, counts = np.unique((colors // 8)[:, 0] * 32 + (colors // 8)[:, 1], return_counts=True)
    for key in keys[np.argsort(counts)[-6:]][::-1]:
        center = np.median(colors[(colors[:, 0] // 8) * 32 + colors[:, 1] // 8 == key], axis=0)
        separation = np.linalg.norm(lab[:, :, 1:].astype(np.float32) - center, axis=2)
        source = ((separation <= 10) & (gray >= 110) & (saturation <= 120)).astype(np.uint8) * 255
        yield cv.morphologyEx(source, cv.MORPH_CLOSE, np.ones((11, 11), np.uint8))


def _surface(source, rgb, gray, saturation, lab, cv, np):
    h, w = gray.shape
    contours, _ = cv.findContours(source, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    significant = sorted((c for c in contours if cv.contourArea(c) >= h * w * .04),
                         key=cv.contourArea, reverse=True)
    if len(significant) != 1:
        return None
    mask = np.zeros((h, w), np.uint8)
    cv.drawContours(mask, significant[:1], -1, 255, -1)
    fraction = float((mask > 0).mean())
    contacts = [float((mask[:3] > 0).mean()), float((mask[-3:] > 0).mean()),
                float((mask[:, :3] > 0).mean()), float((mask[:, -3:] > 0).mean())]
    if not .60 <= fraction <= .96 or not any(value >= .25 for value in contacts):
        return None
    interior = cv.erode(mask, np.ones((7, 7), np.uint8)) > 0
    material = ds._matte_material(gray[interior], saturation[interior], lab[interior][:, 1:])
    if material is None:
        return None
    marks, ink, labels = _glyphs(gray, mask, cv, np)
    if not _layout(marks, gray.shape, cv, np):
        return None
    # Source-frame brightness alone can be a desk or windshield around a
    # complete page. The clipped surface must carry credible document print
    # near one of its actual camera-frame contacts, on the same matte material.
    local_paper = cv.morphologyEx(gray, cv.MORPH_CLOSE,
        cv.getStructuringElement(cv.MORPH_ELLIPSE, (31, 31)))
    paper_tone = float(np.percentile(gray[interior], 75))
    local_color = np.linalg.norm(lab[:, :, 1:].astype(np.float32) - material, axis=2)
    credible = ((local_paper.astype(np.int16) - gray.astype(np.int16) > 25)
                & (mask > 0) & (local_paper >= 115)
                & (local_paper <= paper_tone + 35) & (local_color <= 15))
    band = max(12, round(min(h, w) * .03))
    contact_ink = [credible[:band], credible[-band:],
                   credible[:, :band], credible[:, -band:]]
    required = max(20, round(min(h, w) * .10))
    # A camera can clip a blank margin or a printed rule without clipping any
    # compact letters. Credible same-material print near that contact, together
    # with the independently qualified body layout, remains sufficient.
    if not any(contact >= .25 and int(ink.sum()) >= required
               for contact, ink in zip(contacts, contact_ink)):
        return None
    # Only observed boundaries away from the camera frame qualify. Independently
    # eroded exterior is used for contrast; printed strokes cannot stand in for
    # a source-frame edge, and a similar matte parent cannot be ignored.
    eroded = cv.erode(mask, np.ones((17, 17), np.uint8))
    inner = (mask > 0) & (eroded == 0)
    near = cv.dilate(mask, np.ones((17, 17), np.uint8))
    far = cv.dilate(mask, np.ones((33, 33), np.uint8))
    outer = (far > 0) & (near == 0)
    exclusion = max(3, round(min(h, w) * .008))
    for region in (inner, outer):
        region[:exclusion] = False; region[-exclusion:] = False
        region[:, :exclusion] = False; region[:, -exclusion:] = False
    if inner.sum() < 100 or outer.sum() < 100:
        return None
    light = abs(float(np.median(gray[inner])) - float(np.median(gray[outer])))
    color = float(np.linalg.norm(np.median(lab[inner][:, 1:], axis=0)
                                 - np.median(lab[outer][:, 1:], axis=0)))
    if light < 8 and color < 5:
        return None
    observed = cv.Canny(cv.GaussianBlur(gray, (5, 5), 0), 5, 15)
    supported = cv.dilate(observed, np.ones((5, 5), np.uint8)) > 0
    boundary = (mask > 0) & (cv.erode(mask, np.ones((3, 3), np.uint8)) == 0)
    boundary[:exclusion] = False; boundary[-exclusion:] = False
    boundary[:, :exclusion] = False; boundary[:, -exclusion:] = False
    if boundary.sum() < min(h, w) * .25 or float(supported[boundary].mean()) < .30:
        return None
    return {'mask': mask, 'material': material, 'ink': ink, 'labels': labels,
            'marks': marks, 'contacts': contacts, 'fraction': fraction,
            'gray': gray, 'rgb': rgb, 'saturation': saturation,
            'edge_contrast': light, 'edge_chroma': color}


def prequalify(image):
    cv, np = ds._numeric()
    small = ds._thumbnail(image, 1280)
    rgb = np.asarray(small, np.uint8)
    gray = cv.cvtColor(rgb, cv.COLOR_RGB2GRAY)
    saturation = cv.cvtColor(rgb, cv.COLOR_RGB2HSV)[:, :, 1]
    lab = cv.cvtColor(rgb, cv.COLOR_RGB2LAB)
    qualified = []
    for source in _sources(rgb, gray, saturation, lab, cv, np):
        hint = _surface(source, rgb, gray, saturation, lab, cv, np)
        if hint is None:
            continue
        duplicate = next((item for item in qualified if float(
            np.sum((item['mask'] > 0) & (hint['mask'] > 0))) / float(
            np.sum((item['mask'] > 0) | (hint['mask'] > 0))) > .80
            or float(np.sum((item['mask'] > 0) & (hint['mask'] > 0))) / float(
            min(np.sum(item['mask'] > 0), np.sum(hint['mask'] > 0))) >= .95), None)
        if duplicate is None:
            qualified.append(hint)
        # A later material proposal may lose shaded portions or include
        # extra texture. Keep the first independently qualified physical
        # threshold proposal; refinement must still preserve its writing.
    if len(qualified) != 1:
        return None
    hint = qualified[0]
    hint['image_size'] = image.size
    return hint


def _protected_exterior(gray, paper, cv, np):
    # uint8 input makes >5 median kernels portable across OpenCV builds.
    median = cv.medianBlur(gray, 31)
    residual = np.abs(median.astype(np.int16) - gray.astype(np.int16))
    binary = ((residual > 10) & ~paper).astype(np.uint8)
    _, labels, stats, _ = cv.connectedComponentsWithStats(binary, connectivity=8)
    protected = np.zeros(gray.shape, bool)
    limit = min(gray.shape) * .06
    for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
        if not (area >= 5 and 3 <= w <= min(limit, h * 4)
                and 3 <= h <= min(limit, w * 5) and area / (w * h) < .70):
            continue
        pixels = labels[y:y + h, x:x + w] == label
        if float(np.median(residual[y:y + h, x:x + w][pixels])) < 15:
            continue
        padding = max(8, round(max(w, h) * .5))
        left, top = max(0, x - padding), max(0, y - padding)
        context = gray[top:y + h + padding, left:x + w + padding]
        surface = context[residual[top:y + h + padding, left:x + w + padding] < 8]
        if surface.size < 20 or float(np.percentile(
                np.abs(surface.astype(np.float32) - np.median(surface)), 85)) > 12:
            continue
        protected[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2] = True
    return protected


def _crop_box(hint, region, cv, np):
    gray = hint['gray']; h, w = gray.shape
    # A low gray threshold alone is not an empty-band proof. Dark/colored print
    # and a dark secondary page with visible writing also protect its band.
    protected = _protected_exterior(gray, region > 0, cv, np)
    empty = (gray < 75) & (region == 0) & ~protected
    box = [0, 0, w, h]
    for axis, forward in ((0, True), (0, False), (1, True), (1, False)):
        lines = empty.all(axis=1 - axis)
        if not forward:
            lines = lines[::-1]
        stop = int(np.flatnonzero(~lines)[0]) if (~lines).any() else len(lines)
        if stop <= max(4, round(min(h, w) * .015)):
            continue
        if axis == 0:
            box[1 if forward else 3] = stop if forward else h - stop
        else:
            box[0 if forward else 2] = stop if forward else w - stop
    # Floor inward-removal bounds/ceil retained endpoints avoid losing a source
    # row to rounding. Root must confirm every removed original-pixel strip is
    # still below gray75 and contains no region before applying this crop.
    scale = np.array([hint['image_size'][0] / w, hint['image_size'][1] / h])
    return (int(np.floor(box[0] * scale[0])), int(np.floor(box[1] * scale[1])),
            int(np.ceil(box[2] * scale[0])), int(np.ceil(box[3] * scale[1])))



def _supported_interior(mask, cv, np, *, outward=False):
    """Keep enhancement inside independently supported visible paper edges.

    Profiles use only actually observed, non-frame edges. Robust cubic fits
    tolerate a narrow spare sheet while rejecting broad abrupt/T-shaped merges.
    A broad abrupt merge rejects the region. Smaller uncertain protrusions
    remain in the crop-protected region but receive no paper enhancement.
    These fits never generate hidden geometry or change source coordinates.
    """
    h, w = mask.shape
    present = mask > 0
    interior = mask.copy()
    if outward:
        # A protection envelope is not a transform or a proposed hidden page.
        # Fill observed print notches, then constrain this region by the same
        # visible, supported physical boundaries used for enhancement.
        points = cv.findNonZero(mask)
        if points is None:
            return None
        interior[:] = 0
        cv.fillConvexPoly(interior, cv.convexHull(points), 255)
    tolerance = max(3., min(h, w) * .006)
    margin = max(3, round(min(h, w) * .008))
    rng = np.random.default_rng(0)
    qualified = 0
    for transposed in (False, True):
        pixels = present.T if transposed else present
        ph, pw = pixels.shape
        exists = pixels.any(axis=0)
        for reverse in (False, True):
            values = np.argmax(pixels[::-1] if reverse else pixels, axis=0)
            if reverse:
                values = ph - 1 - values
            valid = exists & (values > margin) & (values < ph - 1 - margin)
            coordinates = np.flatnonzero(valid)
            if coordinates.size < min(h, w) * .35 or np.ptp(coordinates) < min(h, w) * .35:
                continue
            # At most160 observations and64 proposals per visible edge.
            indices = np.linspace(0, len(coordinates) - 1, min(160, len(coordinates))).astype(int)
            x = coordinates[indices].astype(np.float64) / max(1, pw - 1)
            y = values[coordinates[indices]].astype(np.float64)
            best = 0.
            best_coefficients = None
            for _ in range(64):
                sample = rng.choice(len(x), 4, replace=False)
                if np.ptp(x[sample]) < .25:
                    continue
                coefficients = np.polyfit(x[sample], y[sample], 3)
                error = np.abs(np.polyval(coefficients, x) - y)
                support = float((error <= tolerance).mean())
                if support > best:
                    best = support
                    best_coefficients = coefficients
            if best_coefficients is not None:
                # Four-point proposals can overfit pixel stair steps. Refit
                # their independently supported observations, still with the
                # same bounded samples and error allowance.
                for _ in range(2):
                    error = np.abs(np.polyval(best_coefficients, x) - y)
                    inliers = error <= tolerance
                    if int(inliers.sum()) < 4:
                        break
                    coefficients = np.polyfit(x[inliers], y[inliers], 3)
                    support = float((np.abs(np.polyval(coefficients, x) - y)
                                     <= tolerance).mean())
                    if support < best:
                        break
                    best, best_coefficients = support, coefficients
            if best < .70:
                return None
            # Constrain only the already visible span; no off-frame endpoint
            # or hidden corner is extrapolated. Move inward by the fit error
            # allowance so a coherent gray desk extension cannot be whitened
            # merely because most of the paper edge supports the curve.
            boundaries = np.polyval(best_coefficients,
                coordinates.astype(np.float64) / max(1, pw - 1))
            target = interior.T if transposed else interior
            for coordinate, value in zip(coordinates, boundaries):
                allowance = -tolerance if outward else tolerance
                if reverse:
                    cutoff = max(0, min(ph, int(np.floor(value - allowance)) + 1))
                    target[cutoff:, coordinate] = 0
                else:
                    cutoff = max(0, min(ph, int(np.ceil(value + allowance))))
                    target[:cutoff, coordinate] = 0
            qualified += 1
    return interior if qualified > 0 else None


def refine(hint):
    """Return bounded mask/crop_box; failure must leave the full source intact."""
    cv, np = ds._numeric()
    rgb = hint['rgb']; h, w = rgb.shape[:2]
    ratio = min(1., 512 / max(w, h))
    sw, sh = max(2, round(w * ratio)), max(2, round(h * ratio))
    source = cv.resize(rgb, (sw, sh), interpolation=cv.INTER_AREA)
    proposal = cv.resize(hint['mask'], (sw, sh), interpolation=cv.INTER_NEAREST)
    gray = cv.cvtColor(source, cv.COLOR_RGB2GRAY)
    saturation = cv.cvtColor(source, cv.COLOR_RGB2HSV)[:, :, 1]
    lab = cv.cvtColor(source, cv.COLOR_RGB2LAB)
    interior = cv.erode(proposal, np.ones((7, 7), np.uint8)) > 0
    exterior = cv.erode((proposal == 0).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    if interior.sum() < 100 or exterior.sum() < sw * sh * .01:
        return None
    seeds = np.full((sh, sw), cv.GC_PR_BGD, np.uint8)
    seeds[proposal > 0] = cv.GC_PR_FGD
    material_distance = np.linalg.norm(lab[:, :, 1:].astype(np.float32) - hint['material'], axis=2)
    paper_tone = float(np.percentile(hint['gray'][hint['mask'] > 0], 75))
    compatible = ((material_distance <= 10) & (saturation <= 120)
                  & (gray >= max(110, paper_tone - 85)) & (gray <= paper_tone + 35))
    seeds[compatible] = cv.GC_PR_FGD
    true_exterior = exterior & ((material_distance > 15)
        | (gray < max(75, paper_tone - 85)) | (gray > paper_tone + 35))
    if true_exterior.sum() < sw * sh * .005:
        return None
    seeds[true_exterior] = cv.GC_BGD
    clean = (gray >= max(115, paper_tone - 35))
    sure = interior & clean & (saturation <= 120) & (material_distance <= 10)
    if sure.sum() < sw * sh * .1:
        return None
    seeds[sure | compatible] = cv.GC_FGD
    cv.setRNGSeed(0)
    try:
        cv.grabCut(source, seeds, None, np.zeros((1, 65)), np.zeros((1, 65)),
                   3, cv.GC_INIT_WITH_MASK)
    except cv.error:
        return None
    foreground = np.isin(seeds, [cv.GC_FGD, cv.GC_PR_FGD]).astype(np.uint8) * 255
    foreground = cv.morphologyEx(foreground, cv.MORPH_OPEN,
        cv.getStructuringElement(cv.MORPH_ELLIPSE, (3, 3)))
    contours, _ = cv.findContours(foreground, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
    significant = [c for c in contours if cv.contourArea(c) >= sw * sh * .04]
    if len(significant) != 1:
        return None
    foreground[:] = 0
    cv.drawContours(foreground, significant, -1, 255, -1)
    required_ink = np.zeros((h, w), np.uint8)
    for x, y, cw, ch, label in hint['marks']:
        region = required_ink[y:y + ch, x:x + cw]
        region[hint['labels'][y:y + ch, x:x + cw] == label] = 255
    # Edge-touching ink can be an open notch rather than a contour hole. It is
    # independently qualified writing, and must remain in the visible region.
    protected_ink = (cv.resize(required_ink, (sw, sh), interpolation=cv.INTER_AREA) > 0).astype(np.uint8) * 255
    foreground = cv.bitwise_or(foreground, protected_ink)
    refined = cv.resize(foreground, (w, h), interpolation=cv.INTER_NEAREST)
    original = hint['mask'] > 0; result = refined > 0
    retained = float((original & result).sum()) / max(1, int(original.sum()))
    extra = float((result & ~original).sum()) / max(1, int(original.sum()))
    # Printed strokes are not a different surface. Close only small gaps in
    # the independently qualified material mask before validating shaded
    # growth; this cannot bridge a broad unrelated desk/clothing region.
    compatible_print = cv.morphologyEx(compatible.astype(np.uint8),
        cv.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    compatible_large = cv.resize(compatible_print, (w, h), interpolation=cv.INTER_NEAREST) > 0
    added = result & ~original
    # Thresholding may miss a broad same-color cast shadow. Growth is only
    # allowed into observed compatible matte pixels; no hidden content exists.
    if retained < .95 or extra > .35 or (extra > .05 and added.any() and
            float(compatible_large[added].mean()) < .95):
        return None
    # Both dark and saturated colored visible marks in the original proposal
    # must remain members. Isolated physical edge shadow fragments are not ink.
    safe = cv.dilate(refined, np.ones((5, 5), np.uint8)) > 0
    for x, y, cw, ch, label in hint['marks']:
        ink = hint['labels'][y:y + ch, x:x + cw] == label
        if float(safe[y:y + ch, x:x + cw][ink].mean()) < .98:
            return None
    contacts = [float(result[:3].mean()), float(result[-3:].mean()),
                float(result[:, :3].mean()), float(result[:, -3:].mean())]
    if any(old >= .25 and new < old * .9 for old, new in zip(hint['contacts'], contacts)):
        return None
    supported_interior = _supported_interior(refined, cv, np)
    if supported_interior is None:
        return None
    crop = _crop_box(hint, refined, cv, np)
    conservative = (cv.resize(supported_interior, (sw, sh),
        interpolation=cv.INTER_AREA) >= 254).astype(np.uint8) * 255
    enhancement_mask = cv.erode(conservative, np.ones((5, 5), np.uint8))
    supported_envelope = _supported_interior(refined, cv, np, outward=True)
    if supported_envelope is None:
        return None
    visible_envelope = (cv.resize(supported_envelope, (sw, sh),
        interpolation=cv.INTER_AREA) > 0).astype(np.uint8) * 255
    # A narrow written secondary sheet is observed content, rather than a
    # blank desk extension. Independently qualified glyphs protect its whole
    # connected visible surface; gray/material-compatible blank outgrowths do
    # not regain paper status merely because they touch the dominant sheet.
    unsupported = ((foreground > 0) & (visible_envelope == 0)).astype(np.uint8)
    _, components, stats, _ = cv.connectedComponentsWithStats(unsupported, connectivity=8)
    for label, (x, y, cw, ch, area) in enumerate(stats[1:], 1):
        component = components[y:y + ch, x:x + cw] == label
        evidence = protected_ink[y:y + ch, x:x + cw] > 0
        if int((component & evidence).sum()) >= 12:
            visible_envelope[y:y + ch, x:x + cw][component] = 255
    # Matting must never invert the deliberately inset enhancement region.
    # Retain the independently segmented visible surface and mark evidence
    # separately; the native matte still verifies its uncertain boundary.
    return {'partial_mask': enhancement_mask, 'cleanup_foreground': conservative.copy(),
            'paper_foreground': foreground.copy(),
            'surface_envelope': visible_envelope,
            'protected_evidence': protected_ink, 'crop_box': crop, 'kind': 'partial',
            'mask_size': (sw, sh), 'source_size': hint['image_size']}


def _native_safe_depth(image, side, wanted):
    """Find a prefix of truly empty native pixels with <=1M-pixel work tiles."""
    cv, np = ds._numeric()
    width, height = image.size
    if wanted <= 0:
        return 0
    if side == 'top': bounds = (0, 0, width, wanted)
    elif side == 'bottom': bounds = (0, height - wanted, width, height)
    elif side == 'left': bounds = (0, 0, wanted, height)
    else: bounds = (width - wanted, 0, width, height)
    left, top, right, bottom = bounds
    safe = wanted
    # 960+2*16 = 992, hence the largest working tile is 984064 pixels.
    step, halo = 960, 16
    for y in range(top, bottom, step):
        for x in range(left, right, step):
            end_x, end_y = min(right, x + step), min(bottom, y + step)
            tile_left, tile_top = max(0, x - halo), max(0, y - halo)
            tile_right, tile_bottom = min(width, end_x + halo), min(height, end_y + halo)
            pixels = np.asarray(image.crop((tile_left, tile_top, tile_right, tile_bottom)), np.uint8)
            # Native RGB contrast protects tiny colored/low-luma references
            # which may disappear completely when resized to a1280 thumbnail.
            median = cv.medianBlur(pixels, 31)
            difference = np.max(np.abs(pixels.astype(np.int16)
                                       - median.astype(np.int16)), axis=2)
            gray = cv.cvtColor(pixels, cv.COLOR_RGB2GRAY)
            gray_difference = np.abs(gray.astype(np.int16)
                - cv.medianBlur(gray, 31).astype(np.int16))
            # Strong changes/material boundaries are uncertain immediately.
            # Weak print is retained using connected stroke evidence, while
            # isolated dark JPEG/color speckles do not impersonate a reference.
            uncertain = ((np.max(pixels, axis=2) >= 75)
                         | (gray_difference >= 12) | (difference >= 24))
            short_rgb = cv.medianBlur(pixels, 5)
            short_color_difference = np.max(np.abs(pixels.astype(np.int16)
                - short_rgb.astype(np.int16)), axis=2)
            short_gray_difference = np.abs(gray.astype(np.int16)
                - cv.medianBlur(gray, 5).astype(np.int16))
            strokes = (short_gray_difference >= 3) | (short_color_difference >= 6)
            weak = ((gray_difference >= 6) | (difference >= 12)).astype(np.uint8)
            _, labels, stats, _ = cv.connectedComponentsWithStats(weak, connectivity=8)
            for label, (mx, my, mw, mh, area) in enumerate(stats[1:], 1):
                if not (area >= 5 and max(mw, mh) >= 3 and min(mw, mh) >= 1):
                    continue
                component = labels[my:my + mh, mx:mx + mw] == label
                fine = strokes[my:my + mh, mx:mx + mw]
                # Smooth cloth ripples have broad low contrast but no written
                # edge support. A connected signature can be long; retain its
                # whole component once any credible sharp strokes support it.
                if int((component & fine).sum()) < 3:
                    continue
                pad = max(4, round(max(mw, mh) * .5))
                lx, ty = max(0, mx - pad), max(0, my - pad)
                context = gray[ty:my + mh + pad, lx:mx + mw + pad]
                background = context[weak[ty:my + mh + pad, lx:mx + mw + pad] == 0]
                if background.size < 10 or float(np.percentile(np.abs(
                        background.astype(np.float32) - np.median(background)), 85)) > 6:
                    continue
                section = uncertain[my:my + mh, mx:mx + mw]
                section |= labels[my:my + mh, mx:mx + mw] == label
            # Protect low-contrast antialias tails around supported strokes.
            uncertain = cv.dilate(uncertain.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
            core = uncertain[y - tile_top:end_y - tile_top, x - tile_left:end_x - tile_left]
            points = np.argwhere(core)
            if not points.size:
                continue
            if side == 'top': depth = y + int(points[:, 0].min())
            elif side == 'bottom': depth = height - 1 - y - int(points[:, 0].max())
            elif side == 'left': depth = x + int(points[:, 1].min())
            else: depth = width - 1 - x - int(points[:, 1].max())
            safe = min(safe, depth)
    return max(0, safe)


def native_safe_crop_box(image, details):
    """Conservatively verify tentative trim against original pixels, tilewise.

    There is no native-sized mask/gray allocation and no resizing. Any possible
    paper, tiny print, colored reference or material boundary stops that band.
    Uniform unseen/dark content is never reconstructed or rectified.
    """
    width, height = image.size
    crop = details.get('crop_box', (0, 0, width, height))
    if (not isinstance(crop, (list, tuple)) or len(crop) != 4
            or any(type(value) is not int for value in crop)):
        return (0, 0, width, height)
    left, top, right, bottom = crop
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        return (0, 0, width, height)
    result = [0, 0, width, height]
    minimum = max(4, round(min(image.size) * .015))
    for side, wanted in (('left', left), ('top', top),
                         ('right', width - right), ('bottom', height - bottom)):
        safe = _native_safe_depth(image, side, wanted)
        if safe < minimum:
            continue
        if side == 'left': result[0] = safe
        elif side == 'top': result[1] = safe
        elif side == 'right': result[2] = width - safe
        else: result[3] = height - safe
    return tuple(result)
