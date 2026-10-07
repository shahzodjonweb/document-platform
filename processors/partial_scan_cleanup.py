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
