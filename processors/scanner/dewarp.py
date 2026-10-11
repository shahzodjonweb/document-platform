"""Stage 2: flatten curved, folded or crumpled pages with UVDoc (ONNX, CPU).

UVDoc (MIT code, github.com/tanguymagne/UVDoc) looks at a 488x712 image and
predicts a 45x31 grid: for each point of the flat page, where it lies in the
input. The grid is upsampled to the output size and every output pixel is
sampled from the full-resolution photo, so the result keeps all the detail.

UVDoc is fed the perspective result, flattened together with 4.5% of the real
surroundings beyond the four corners. A bent sheet's edges curve away from
the straight lines between its corners; UVDoc must see the true paper edge
against the real background to map it onto straight output edges. (Cut
exactly at the corners, it trims ~17% of the page; inside an artificial dark
border it keeps background slivers where the edge curves.) Rigid cards stay
put: no surroundings pulled in, ~0.25% of the diagonal of extra bend.

The output shape is snapped to the nearest standard paper size (A4, US
Letter, Legal) when the measured shape is within 7% of it, see page_shape().
"""
import cv2
import numpy as np

from .shadows import session

INPUT_SIZE = (488, 712)  # width, height
# Real surroundings kept around the page, as a share of its size.
FLAT_CONTEXT = 0.045
WHITE = (255, 255, 255)
# Standard sheets, long side / short side.
PAPER = {'A4': 297 / 210, 'Letter': 11 / 8.5, 'Legal': 14 / 8.5}
SNAP_TOLERANCE = 0.07


def predict_grid(bgr):
    """UVDoc's 2x45x31 grid for an image, in [-1, 1] coordinates of that image."""
    rgb = cv2.cvtColor(cv2.resize(bgr, INPUT_SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)
    tensor = (rgb.astype(np.float32) / 255).transpose(2, 0, 1)[None]
    return session('uvdoc').run(['grid2d'], {'image': tensor})[0][0]


def grid_maps(grid, width, height, src_w, src_h):
    """Per-output-pixel sampling positions in a ``src_w`` x ``src_h`` source.

    Matches PyTorch's interpolate + grid_sample with align_corners=True (plain
    cv2.resize of the grid would misplace pixels by tens of pixels).
    """
    grid = np.clip(grid, -1.5, 1.5).astype(np.float32)  # the last layer is unbounded
    grid_h, grid_w = grid.shape[1:]
    cols = np.linspace(0, grid_w - 1, width, dtype=np.float32)
    rows = np.linspace(0, grid_h - 1, height, dtype=np.float32)
    map_x, map_y = np.meshgrid(cols, rows)
    gx = cv2.remap(grid[0], map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    gy = cv2.remap(grid[1], map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return (gx + 1) * .5 * (src_w - 1), (gy + 1) * .5 * (src_h - 1)


def folds_over(grid):
    """True when the predicted grid crosses itself, i.e. the prediction is unusable."""
    dx_cols = np.diff(grid[0], axis=1)
    dy_rows = np.diff(grid[1], axis=0)
    return bool((dx_cols <= 0).mean() > .02 or (dy_rows <= 0).mean() > .02)


def page_size(quad):
    tl, tr, br, bl = quad
    width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    return max(2, round(width)), max(2, round(height))


def page_shape(width, height, choice='auto'):
    """Output size and the paper it was matched to.

    'auto' snaps to the nearest standard sheet within SNAP_TOLERANCE (and keeps
    the corners' shape otherwise), or name a sheet ('A4', 'Letter', 'Legal') to
    force it. The long side keeps its measured length; orientation is kept.
    """
    long_side, short_side = max(width, height), min(width, height)
    ratio = long_side / short_side
    if choice == 'auto':
        name, target = min(PAPER.items(), key=lambda item: abs(ratio / item[1] - 1))
        if abs(ratio / target - 1) > SNAP_TOLERANCE:
            return (width, height), None
    else:
        name, target = choice, PAPER[choice]
    short_side = max(2, round(long_side / target))
    return ((short_side, long_side) if height >= width else (long_side, short_side)), name


def dewarp(bgr, quad, size=None):
    """A flat page from the photo and DocAligner's corners (TL, TR, BR, BL, full-res pixels).

    ``size`` is the output (width, height); by default the corners' shape.
    Returns the perspective-only page when UVDoc's prediction is unusable.
    """
    quad = np.float32(quad)
    width, height = page_size(quad)
    out_w, out_h = size or (width, height)
    # Flatten the page with some of its real surroundings, so UVDoc sees the
    # true paper edge (curved on a bent sheet) against the real background.
    ex, ey = round(FLAT_CONTEXT * width), round(FLAT_CONTEXT * height)
    context_w, context_h = width + 2 * ex, height + 2 * ey
    target = np.float32([[ex, ey], [ex + width - 1, ey], [ex + width - 1, ey + height - 1], [ex, ey + height - 1]])
    matrix = cv2.getPerspectiveTransform(quad, target)
    context = cv2.warpPerspective(bgr, matrix, (context_w, context_h), flags=cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REPLICATE)
    grid = predict_grid(context)
    if folds_over(grid):
        return _perspective(bgr, quad, out_w, out_h)
    # One resample from the original photo: positions on the flattened view go
    # back through the perspective transform. Outside the photo is white.
    sx, sy = grid_maps(grid, out_w, out_h, context_w, context_h)
    points = cv2.perspectiveTransform(np.dstack([sx, sy]).reshape(-1, 1, 2),
                                      np.linalg.inv(matrix)).reshape(out_h, out_w, 2)
    return cv2.remap(bgr, points[..., 0].copy(), points[..., 1].copy(), cv2.INTER_CUBIC,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=WHITE)


def _perspective(bgr, quad, width, height):
    target = np.float32([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]])
    matrix = cv2.getPerspectiveTransform(quad, target)
    return cv2.warpPerspective(bgr, matrix, (width, height), flags=cv2.INTER_CUBIC,
                               borderMode=cv2.BORDER_CONSTANT, borderValue=WHITE)
