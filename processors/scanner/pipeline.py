"""The whole scan, one fixed chain.

  1 page detection    DocAligner fastvit_sa24 + tuned rules        detect.py
    document check    writing inside, nothing lost outside         evidence.py
  2 dewarping         UVDoc on the perspective result, paper snap  dewarp.py
  3 AI text upscaling Intel text-image-super-resolution-0001       enhance.py
  4 shadow removal    GC-Net, then the paper made white            shadows.py
  5 final look        folds, thumbs, clarity, bold text, tone      look.py
"""
import time

import numpy as np

from . import evidence
from .detect import detect, model, order, presence_model
from .dewarp import PAPER, dewarp, page_shape, page_size
from .enhance import scale_for, upscale
from .look import magic
from .shadows import remove_shadows, session, whiten_paper

PAPER_CHOICES = ('auto', *PAPER)


def load_models():
    """Load every model up front (otherwise each loads on first use)."""
    model()
    presence_model()
    for name in ('uvdoc', 'text_sr_x3', 'gcnet'):
        session(name)


def _ms(started):
    return round((time.perf_counter() - started) * 1000)


def scan(bgr, paper='auto'):
    """Scan one photo (BGR uint8, upright).

    ``paper``: 'auto' snaps the page to the nearest of A4 / Letter / Legal when
    its measured shape is within 7% (otherwise keeps that shape); 'A4',
    'Letter' or 'Legal' force that sheet.

    Returns a dict: ``found``; ``page`` (the final scan, BGR uint8, or None when
    no document was found); ``reason`` (why an outline was not taken as a page,
    see evidence.check, or None); ``corners`` (TL, TR, BR, BL in photo pixels);
    ``sheet`` (the paper size matched, or None); ``ratio`` (measured long/short
    side); ``times`` (ms per step and 'total').
    """
    if paper not in PAPER_CHOICES:
        raise ValueError(f'paper must be one of {", ".join(PAPER_CHOICES)}')
    total = time.perf_counter()
    times = {}
    result = {'found': False, 'page': None, 'reason': None, 'corners': None, 'sheet': None, 'ratio': None,
              'times': times}

    # Stage 1: page detection.
    started = time.perf_counter()
    points = detect(bgr)
    times['detect'] = _ms(started)
    if points is None:
        times['total'] = _ms(total)
        return result
    quad = order(points)
    # Only a written page is cropped: never a photo, an appliance or the
    # inner table of a larger sheet.
    started = time.perf_counter()
    is_page, result['reason'] = evidence.check(bgr, quad)
    times['evidence'] = _ms(started)
    if not is_page:
        times['total'] = _ms(total)
        return result
    result.update(found=True, corners=np.round(quad).astype(int).tolist())

    # Stage 2: dewarping (UVDoc), output snapped to a standard sheet.
    measured = page_size(quad)
    size, sheet = page_shape(*measured, paper)
    result.update(sheet=sheet, ratio=round(max(measured) / min(measured), 3))
    started = time.perf_counter()
    page = dewarp(bgr, quad, size)
    times['dewarp'] = _ms(started)

    # Stage 3: AI text upscaling, right after dewarping, so shadow removal
    # and the final look work on the rebuilt page: Intel's text model on
    # lightness, colour enlarged smoothly. Pages already large enough are
    # left alone.
    if scale_for(page) > 1.05:
        started = time.perf_counter()
        page = upscale(page)
        times['upscale'] = _ms(started)

    # Stage 4: shadow removal, then the paper made neutral white.
    started = time.perf_counter()
    clean = whiten_paper(remove_shadows(page))
    times['shadows'] = _ms(started)

    # Stage 5: the final look.
    started = time.perf_counter()
    result['page'] = magic(clean)
    times['magic'] = _ms(started)
    times['total'] = _ms(total)
    return result
