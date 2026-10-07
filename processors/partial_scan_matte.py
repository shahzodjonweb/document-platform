"""White canvas outside an observed, clipped document without changing its ink.

The independently qualified surface is only a proposal. Native pixels refine
its visible boundary and protect reference marks before any exterior is removed.
No missing corner, page ratio, perspective transform or hidden content is used.
"""
from PIL import Image

from processors import document_scan as ds


def _marks(rgb, gray, exterior, cv, np):
    """Protect native writing within the observed paper uncertainty region."""
    background = cv.medianBlur(rgb, 31)
    difference = np.max(np.abs(rgb.astype(np.int16)
                              - background.astype(np.int16)), axis=2)
    gray_background = cv.cvtColor(background, cv.COLOR_RGB2GRAY)
    gray_difference = np.abs(gray.astype(np.int16)
                             - gray_background.astype(np.int16))
    short = cv.medianBlur(rgb, 5)
    fine_color = np.max(np.abs(rgb.astype(np.int16) - short.astype(np.int16)), axis=2)
    fine_gray = np.abs(gray.astype(np.int16)
                      - cv.cvtColor(short, cv.COLOR_RGB2GRAY).astype(np.int16))
    fine = (fine_color >= 6) | (fine_gray >= 3)
    possible = (((difference >= 6) | (gray_difference >= 3)) & exterior).astype(np.uint8)
    _, labels, stats, _ = cv.connectedComponentsWithStats(possible, connectivity=8)
    protected = np.zeros(gray.shape, np.uint8)
    height, width = gray.shape
    for label, (x, y, w, h, area) in enumerate(stats[1:], 1):
        if area < 5 or max(w, h) < 4:
            continue
        component = labels[y:y + h, x:x + w] == label
        credible = component & fine[y:y + h, x:x + w]
        count = int(credible.sum())
        if count < 3:
            continue
        weak = (float(np.percentile(gray_difference[y:y + h, x:x + w][component], 95)) <= 12
                and float(np.percentile(difference[y:y + h, x:x + w][component], 95)) <= 30)
        if not weak and count / area < .25:
            continue
        # Written strokes have a smooth local substrate. Cloth weave and
        # scenery generally lack that independently observed context. Do not
        # limit a mark's length/aspect: a faint signature can cross a tile.
        padding = max(8, min(64, round(max(w, h) * .5)))
        left, top = max(0, x - padding), max(0, y - padding)
        right, bottom = min(width, x + w + padding), min(height, y + h + padding)
        context = gray[top:bottom, left:right]
        if not exterior[top:bottom, left:right].all():
            continue
        quiet = ((possible[top:bottom, left:right] == 0)
                 & exterior[top:bottom, left:right])
        substrate = context[quiet]
        if substrate.size < 20 or float(np.percentile(np.abs(
                substrate.astype(np.float32) - np.median(substrate)), 85)) > 9:
            continue
        # Protect the whole supported native component and its substrate,
        # not a rectangular component box (which turns a soft physical glint
        # into an artificial black square). One-character references and long
        # signatures do not need neighboring glyphs to survive. Caller limits
        # this evidence to the observed page; exterior scene annotations are
        # intentionally removed by document cropping.
        protected[y:y + h, x:x + w][component] = 255
    return cv.dilate(protected, cv.getStructuringElement(cv.MORPH_ELLIPSE, (7, 7)))


def _sample(mask, bounds, image_size, cv, np):
    left, top, right, bottom = bounds
    width, height = image_size
    columns = ((np.arange(left, right, dtype=np.float32) + .5)
               * mask.shape[1] / width - .5)
    rows = ((np.arange(top, bottom, dtype=np.float32) + .5)
            * mask.shape[0] / height - .5)
    shape = (bottom - top, right - left)
    return cv.remap(mask, np.broadcast_to(columns, shape),
                    np.broadcast_to(rows[:, None], shape), cv.INTER_LINEAR,
                    borderMode=cv.BORDER_REPLICATE)


def remove_exterior(image, details):
    """Return source RGB on observed paper and white on its exterior scene.

    Working tiles are at most 864 + 2*64 = 992 pixels per side (984064
    pixels). There is no native-sized CV mask or float RGB allocation. The
    output is the same size and every retained source pixel is byte-exact.
    """
    cv, np = ds._numeric()
    mask = details.get('paper_foreground')
    evidence = details.get('protected_evidence')
    if (mask is None or details.get('kind') != 'partial'
            or details.get('source_size') != image.size
            or image.width * image.height > 40_000_000):
        return image, False
    mask = np.asarray(mask, np.uint8)
    if mask.ndim != 2 or min(mask.shape) < 2 or max(mask.shape) > 512:
        return image, False
    if evidence is None:
        evidence = np.zeros_like(mask)
    evidence = np.asarray(evidence, np.uint8)
    if evidence.shape != mask.shape:
        return image, False
    # A convex envelope of observed surface pixels is a conservative protection
    # region, not inferred page corners or a proposed transform. It permits
    # native validation of frame-connected print/shadow notches while excluding
    # isolated lettering/glints elsewhere in the source scene.
    envelope = details.get('surface_envelope')
    if envelope is None:
        return image, False
    envelope = np.asarray(envelope, np.uint8)
    if envelope.shape != mask.shape:
        return image, False
    mask = cv.bitwise_and(mask, envelope)
    width, height = image.size
    output = image.copy()
    changed = False
    retained_box = [width, height, 0, 0]
    step, halo = 864, 64
    # A boundary may move by one thumbnail cell. Check that native neighborhood
    # against actually photographed material instead of snapping to a staircase.
    boundary_width = max(3, round(max(width / mask.shape[1], height / mask.shape[0])) + 2)
    boundary_width = min(48, boundary_width)
    paper_guard = max(3, min(48, round(max(width / mask.shape[1],
                                          height / mask.shape[0]) * 1.5)))
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE,
                                      (boundary_width * 2 + 1, boundary_width * 2 + 1))
    for top in range(0, height, step):
        for left in range(0, width, step):
            right, bottom = min(width, left + step), min(height, top + step)
            bounds = (max(0, left - halo), max(0, top - halo),
                      min(width, right + halo), min(height, bottom + halo))
            tile = np.asarray(image.crop(bounds), np.uint8)
            gray = cv.cvtColor(tile, cv.COLOR_RGB2GRAY)
            proposed = _sample(mask, bounds, image.size, cv, np) > 0
            known = _sample(evidence, bounds, image.size, cv, np) > 0
            observed = _sample(envelope, bounds, image.size, cv, np) > 0
            neighborhood = cv.dilate(proposed.astype(np.uint8), kernel) > 0
            interior = cv.erode(proposed.astype(np.uint8), kernel) > 0
            # A light native surface just outside a quantized edge is real
            # paper/antialias until proven otherwise. Retain it and its tiny
            # print; only darker confirmed exterior beyond the observed
            # material transition may be removed in this uncertainty band.
            boundary = neighborhood & ~interior
            native_paper = (gray >= 90) | (np.max(tile, axis=2) >= 115)
            retained = interior | (boundary & native_paper & observed) | known
            # Print connected to a clipped frame can be an open notch in the
            # thumbnail segmentation. Independently observed bright matte
            # substrate at native resolution protects that whole surface,
            # including the dark glyph pixels in such a notch. Bright/gray
            # uncertain neighboring surfaces remain intact conservatively.
            substrate = cv.medianBlur(gray, 31)
            retained |= (substrate >= 110) & observed
            # Close dark printed holes within the visible boundary. This is a
            # source-pixel protection mask, never synthesized page content.
            retained = cv.morphologyEx(retained.astype(np.uint8), cv.MORPH_CLOSE,
                cv.getStructuringElement(cv.MORPH_ELLIPSE, (5, 5))) > 0
            retained |= proposed & (gray >= 60)
            # Pixels far inside the segmented page can include black ink.
            # Everything there stays exact; uncertain dark edge ink receives
            # the same independent native mark protection as exterior notes.
            notes = _marks(tile, gray, ~retained & neighborhood, cv, np) > 0
            retained |= notes
            retained = cv.dilate(retained.astype(np.uint8),
                cv.getStructuringElement(cv.MORPH_ELLIPSE,
                    (paper_guard * 2 + 1, paper_guard * 2 + 1))) > 0
            y0, x0 = top - bounds[1], left - bounds[0]
            core = tile[y0:y0 + bottom - top, x0:x0 + right - left].copy()
            remove = ~retained[y0:y0 + bottom - top, x0:x0 + right - left]
            coordinates = np.argwhere(~remove)
            if coordinates.size:
                retained_box[0] = min(retained_box[0], left + int(coordinates[:, 1].min()))
                retained_box[1] = min(retained_box[1], top + int(coordinates[:, 0].min()))
                retained_box[2] = max(retained_box[2], left + int(coordinates[:, 1].max()) + 1)
                retained_box[3] = max(retained_box[3], top + int(coordinates[:, 0].max()) + 1)
            if np.any(remove & np.any(core != 255, axis=2)):
                core[remove] = 255
                changed = True
            output.paste(Image.fromarray(core), (left, top))
    if changed and retained_box[0] < retained_box[2] and retained_box[1] < retained_box[3]:
        details['matte_crop_box'] = (max(0, retained_box[0] - 3), max(0, retained_box[1] - 3),
                                   min(width, retained_box[2] + 3), min(height, retained_box[3] + 3))
    return (output if changed else image), changed
