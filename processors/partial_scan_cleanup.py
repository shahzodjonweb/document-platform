"""Bounded paper illumination and neutral-stroke cleanup for clipped scans."""
from PIL import Image


def enhance_paper(image, region_mask, cv, np, *, feather=True):
    rgb = np.asarray(image, np.uint8)
    small = image.copy()
    small.thumbnail((512, 512), Image.Resampling.LANCZOS)
    source = np.asarray(small, np.uint8).copy()
    region = cv.resize(np.asarray(region_mask, np.uint8), small.size,
                       interpolation=cv.INTER_NEAREST)
    if not (region > 0).any():
        return image
    # Replicate observed paper into the field's exterior before estimating
    # illumination. A dark desk must not bias the paper's edge exposure.
    outside = (region == 0).astype(np.uint8)
    _, labels = cv.distanceTransformWithLabels(outside, cv.DIST_L2, 5,
                                               labelType=cv.DIST_LABEL_PIXEL)
    paper_pixels = source[region > 0]
    source[outside > 0] = paper_pixels[labels[outside > 0] - 1]
    kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (17, 17))
    field = np.empty_like(source)
    for channel in range(3):
        closed = cv.morphologyEx(source[:, :, channel], cv.MORPH_CLOSE, kernel)
        field[:, :, channel] = cv.GaussianBlur(closed, (0, 0), 7)
    if feather:
        distance = cv.distanceTransform((region > 0).astype(np.uint8), cv.DIST_L2, 3)
        region = np.clip(distance * (255 / 3), 0, 255).astype(np.uint8)
    table = np.clip((np.arange(256, dtype=np.float32) - 25) * (255 / 220),
                    0, 255).astype(np.uint8)
    result = np.empty_like(rgb)
    width, height = image.size
    # Closing31px needs a30px halo (dilation followed by erosion).940px cores
    # keep each working tile at most one million
    # pixels. Fields/masks remain thumbnail-sized; no full-resolution float
    # illumination field or alpha mask is allocated.
    step, halo = 940, 30
    ink_kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (31, 31))
    for top in range(0, height, step):
        bottom = min(height, top + step)
        for left in range(0, width, step):
            right = min(width, left + step)
            shape = (bottom - top, right - left)
            columns = ((np.arange(left, right, dtype=np.float32) + .5)
                       * small.width / width - .5)
            rows = ((np.arange(top, bottom, dtype=np.float32) + .5)
                    * small.height / height - .5)
            map_x = np.broadcast_to(columns, shape)
            map_y = np.broadcast_to(rows[:, None], shape)
            illumination = cv.remap(field, map_x, map_y, cv.INTER_LINEAR,
                                   borderMode=cv.BORDER_REPLICATE)
            pixels = rgb[top:bottom, left:right]
            adjusted = np.empty_like(pixels)
            for channel in range(3):
                normalized = cv.divide(pixels[:, :, channel],
                    np.maximum(illumination[:, :, channel], 75), scale=245)
                adjusted[:, :, channel] = cv.LUT(normalized, table)
            l, t = max(0, left - halo), max(0, top - halo)
            r, b = min(width, right + halo), min(height, bottom + halo)
            gray = cv.cvtColor(rgb[t:b, l:r], cv.COLOR_RGB2GRAY)
            local_paper = cv.morphologyEx(gray, cv.MORPH_CLOSE, ink_kernel)
            residual = (local_paper.astype(np.int16) - gray.astype(np.int16))[
                top - t:bottom - t, left - l:right - l]
            neutral = cv.cvtColor(adjusted, cv.COLOR_RGB2GRAY).astype(np.float32)
            chroma = np.ptp(adjusted.astype(np.int16), axis=2)
            weight = np.clip((40 - chroma) / 20, 0, 1)
            # Strongly colored ink receives no extra gain. Native fine-stroke
            # evidence gates the gain so blank, broad folds are not darkened.
            illumination_gray = cv.cvtColor(illumination, cv.COLOR_RGB2GRAY)
            stroke = (1.6 * np.maximum(residual.astype(np.float32) - 1, 0)
                      * 245 / np.maximum(illumination_gray, 75))
            deficit = np.minimum(np.minimum(.9 * (255 - neutral), 90), stroke) * weight
            adjusted = np.clip(adjusted.astype(np.float32) - deficit[:, :, None],
                               0, 255).astype(np.uint8)
            alpha = cv.remap(region, map_x, map_y, cv.INTER_LINEAR,
                             borderMode=cv.BORDER_REPLICATE).astype(np.uint16)
            result[top:bottom, left:right] = ((adjusted.astype(np.uint16)
                * alpha[:, :, None] + pixels.astype(np.uint16)
                * (255 - alpha[:, :, None]) + 127) // 255).astype(np.uint8)
    return Image.fromarray(result)


def cleanup_paper(image, *, paper_mask=None, cv=None, np=None):
    """Clean a selected rectangular document without recreating its writing.

    Broad illumination and fine neutral paper texture become white. Dark and
    colored source strokes receive a monotonic contrast adjustment. This API
    is for a rectified document canvas; enhancement-only photos keep using
    ``enhance_paper`` so their surrounding scene remains unchanged.
    """
    if cv is None or np is None:
        from processors.document_scan import _numeric
        cv, np = _numeric()
    if image.width * image.height > 40_000_000:
        return image
    rgb = np.asarray(image, np.uint8)
    small = image.copy()
    small.thumbnail((512, 512), Image.Resampling.LANCZOS)
    source = np.asarray(small, np.uint8).copy()
    if paper_mask is None:
        region = np.full((small.height, small.width), 255, np.uint8)
    else:
        # Accept a native caller mask without passing its full canvas to an
        # OpenCV operation. Only the bounded selection is needed below.
        region = np.asarray(Image.fromarray(np.asarray(paper_mask, np.uint8))
                            .resize(small.size, Image.Resampling.NEAREST)).copy()
    if not (region > 0).any():
        return Image.new('RGB', image.size, 'white')
    outside = (region == 0).astype(np.uint8)
    _, labels = cv.distanceTransformWithLabels(outside, cv.DIST_L2, 5,
                                               labelType=cv.DIST_LABEL_PIXEL)
    source[outside > 0] = source[region > 0][labels[outside > 0] - 1]
    # A printed solid cell can cover the illumination footprint completely.
    # Keep independently dark source ink rather than letting that cell become
    # its own "paper" reference and normalize to white.
    paper_reference = np.percentile(source[region > 0], 75, axis=0)
    neutral_reference = float(np.dot(paper_reference, (.299, .587, .114)))
    illumination = np.empty_like(source)
    field_kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (17, 17))
    for channel in range(3):
        closed = cv.morphologyEx(source[:, :, channel], cv.MORPH_CLOSE, field_kernel)
        illumination[:, :, channel] = cv.GaussianBlur(closed, (0, 0), 5)
    result = np.empty_like(rgb)
    width, height = image.size
    # Bilateral radius2 + closing radius30 + smoothing radius2 + ink support
    # radius2 requires36px
    # context.928+2*36=1000, so every native OpenCV array remains <=1M pixels.
    step, halo = 928, 36
    # The smaller field follows crease texture instead of amplifying it as ink.
    # Its footprint scales with the document canvas, so high-resolution source
    # glyphs are not lost merely because their strokes span more pixels.
    footprint = max(9, min(31, round(min(width, height) / 100) | 1))
    ink_kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (footprint, footprint))
    for top in range(0, height, step):
        bottom = min(height, top + step)
        for left in range(0, width, step):
            right = min(width, left + step)
            l, t = max(0, left - halo), max(0, top - halo)
            r, b = min(width, right + halo), min(height, bottom + halo)
            native_shape = (b - t, r - l)
            native_columns = ((np.arange(l, r, dtype=np.float32) + .5)
                              * small.width / width - .5)
            native_rows = ((np.arange(t, b, dtype=np.float32) + .5)
                           * small.height / height - .5)
            native_maps = (np.broadcast_to(native_columns, native_shape),
                           np.broadcast_to(native_rows[:, None], native_shape))
            observed = cv.remap(region, *native_maps, cv.INTER_NEAREST,
                                borderMode=cv.BORDER_REPLICATE) > 0
            if not observed.any():
                result[top:bottom, left:right] = 255
                continue
            working = rgb[t:b, l:r]
            if not observed.all():
                # Unknown white canvas is not an illumination measurement.
                # Replicating nearest photographed paper before native closing
                # prevents a paper/frame transition from becoming a fake ink
                # outline; the same pixels are made white again on output.
                exterior = (~observed).astype(np.uint8)
                # A bounded mask cell may overlap a few already-white donor
                # pixels at a missing-source boundary. Those pixels provide no
                # photographic illumination either. Limit this correction to
                # pure white right beside independently unknown canvas.
                beside_unknown = cv.dilate(exterior, np.ones((7, 7), np.uint8)) > 0
                pure_white = np.all(working == 255, axis=2)
                field_region = observed & ~(beside_unknown & pure_white)
                if not field_region.any():
                    result[top:bottom, left:right] = 255
                    continue
                exterior = (~field_region).astype(np.uint8)
                _, nearest = cv.distanceTransformWithLabels(exterior, cv.DIST_L2,
                    5, labelType=cv.DIST_LABEL_PIXEL)
                working = working.copy()
                working[~field_region] = working[field_region][nearest[~field_region] - 1]
            # Small edge-preserving color neighborhoods reduce camera grain.
            # No opening/erosion/connected-component removal is applied to ink.
            smooth = cv.bilateralFilter(working, 5, 11, 2)
            gray = cv.cvtColor(smooth, cv.COLOR_RGB2GRAY)
            reference = smooth
            if paper_mask is not None and not observed.all():
                # Color/gray fields need the same observed-material donors.
                # Remove only a2px boundary band from the reference, never
                # from the source strokes being rendered.
                core = cv.erode(field_region.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
                if core.any():
                    _, nearest = cv.distanceTransformWithLabels((~core).astype(np.uint8),
                        cv.DIST_L2, 5, labelType=cv.DIST_LABEL_PIXEL)
                    reference = smooth.copy()
                    reference[~core] = reference[core][nearest[~core] - 1]
            reference_gray = cv.cvtColor(reference, cv.COLOR_RGB2GRAY)
            local_paper = cv.morphologyEx(reference_gray, cv.MORPH_CLOSE, ink_kernel)
            local_paper = cv.GaussianBlur(local_paper, (5, 5), .8)
            native_color_field = None
            if paper_mask is not None:
                native_color_field = np.empty_like(reference)
                for channel in range(3):
                    closed = cv.morphologyEx(reference[:, :, channel], cv.MORPH_CLOSE, ink_kernel)
                    native_color_field[:, :, channel] = cv.GaussianBlur(closed, (5, 5), .8)
            strong_support = cv.dilate(((local_paper.astype(np.int16)
                - gray.astype(np.int16) >= 60)
                | (gray < neutral_reference * .45)).astype(np.uint8),
                np.ones((5, 5), np.uint8)) > 0
            # Repeated parallel high-contrast edges (for example barcodes) need
            # their original narrow light spaces. This generic source-pattern
            # evidence is independent of decoded text or any document layout.
            gx = cv.Sobel(gray, cv.CV_32F, 1, 0, ksize=3)
            gy = cv.Sobel(gray, cv.CV_32F, 0, 1, ksize=3)
            a = cv.boxFilter(gx * gx, -1, (21, 21))
            b = cv.boxFilter(gy * gy, -1, (21, 21))
            cross = cv.boxFilter(gx * gy, -1, (21, 21))
            coherence = np.sqrt((a - b) ** 2 + 4 * cross ** 2) / (a + b + 1)
            dark = (gray < neutral_reference * .65).astype(np.int8)
            transitions = np.zeros(gray.shape, np.float32)
            transitions[:, 1:] += np.abs(np.diff(dark, axis=1))
            transitions[1:] += np.abs(np.diff(dark, axis=0))
            stripes = ((coherence > .86)
                       & (cv.boxFilter(transitions, -1, (21, 21)) > .20))
            gentle = strong_support & ((gray >= neutral_reference * .68) | stripes)
            ys, xs = slice(top - t, bottom - t), slice(left - l, right - l)
            pixels = smooth[ys, xs]
            gray = gray[ys, xs]
            local_paper = local_paper[ys, xs]
            shape = (bottom - top, right - left)
            columns = ((np.arange(left, right, dtype=np.float32) + .5)
                       * small.width / width - .5)
            rows = ((np.arange(top, bottom, dtype=np.float32) + .5)
                    * small.height / height - .5)
            maps = (np.broadcast_to(columns, shape), np.broadcast_to(rows[:, None], shape))
            field = cv.remap(illumination, *maps, cv.INTER_LINEAR,
                             borderMode=cv.BORDER_REPLICATE)
            color_field = field if native_color_field is None else native_color_field[ys, xs]
            normalized = np.empty_like(pixels)
            for channel in range(3):
                normalized[:, :, channel] = cv.divide(pixels[:, :, channel],
                    np.maximum(color_field[:, :, channel], max(75, round(paper_reference[channel] * .5))), scale=255)
            normalized_gray = cv.cvtColor(normalized, cv.COLOR_RGB2GRAY).astype(np.float32)
            # The native paper field follows broad smooth folds rather than
            # treating their shading as a written character. A small camera
            # noise floor suppresses grain; genuine faint strokes remain a
            # continuous luminance residual, not a binary/OCR replacement.
            residual = np.maximum(local_paper.astype(np.float32)
                                  - gray.astype(np.float32) - 2.25, 0)
            darkness = residual * 4.5 * 245 / np.maximum(local_paper, 75)
            coarse_gray = cv.cvtColor(color_field, cv.COLOR_RGB2GRAY).astype(np.float32)
            coarse_dark = np.maximum(coarse_gray - gray.astype(np.float32), 0)
            # Large dark logos/filled printed cells can exceed the native
            # closing footprint; retain their independently strong contrast.
            strong = np.clip((coarse_dark - 35) / 25, 0, 1)
            darkness = np.maximum(darkness, coarse_dark * 245
                                  / np.maximum(coarse_gray, 75) * strong * 2)
            # High-contrast printed strokes already have enough evidence.
            # Their antialiasing and narrow barcode spaces need the original
            # exposure contrast, rather than the extra gain for faint glyphs.
            darkness = np.where(gentle[ys, xs],
                                255 - normalized_gray, darkness)
            solid = np.clip((neutral_reference * .45 - gray.astype(np.float32))
                            / max(neutral_reference * .2, 1), 0, 1)
            darkness = np.maximum(darkness, solid * 255)
            neutral = np.clip(255 - darkness, 0, 255)
            chroma = np.ptp(normalized.astype(np.int16), axis=2)
            # Neutral camera grain needs no residual paper tint. A small but
            # credible color difference still protects faint colored pen ink.
            color_weight = np.clip((chroma.astype(np.float32) - 4) / 8, 0, 1)
            # Move color brightness toward the cleaned paper/ink luminance,
            # bounded by its available RGB headroom. A shared offset preserves
            # hue and channel span without letting a slight paper tint retain
            # broad gray folds or make neutral printed strokes pale.
            shift = np.clip(neutral - normalized_gray,
                            -normalized.min(axis=2).astype(np.float32),
                            255 - normalized.max(axis=2).astype(np.float32))
            colored = normalized.astype(np.float32) + shift[:, :, None]
            cleaned = np.clip(colored * color_weight[:, :, None]
                + neutral[:, :, None] * (1 - color_weight[:, :, None]), 0, 255).astype(np.uint8)
            alpha = cv.remap(region, *maps, cv.INTER_NEAREST,
                             borderMode=cv.BORDER_REPLICATE) > 0
            cleaned[~alpha] = 255
            cleaned[np.all(rgb[top:bottom, left:right] == 255, axis=2)] = 255
            result[top:bottom, left:right] = cleaned
    return Image.fromarray(result)
