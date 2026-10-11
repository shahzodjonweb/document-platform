"""Document scanner: a photo of a document in, a clean flat page out.

DocAligner finds the page, UVDoc flattens it, Intel's text model rebuilds the
print at up to 2x, GC-Net removes shadows and look.py gives the final clean
paper; see pipeline.py. The code is derived from open-doc-scanner; it differs
only in how much memory it uses (strip-wise text model, no ONNX Runtime
arena, SCANNER_THREADS and SCANNER_MODELS), never in its output pixels.

The engine calls scan_photo() once per uploaded image. Only a written page
is changed; any other photo comes back as the very same object, so a plain
JPEG upload is still embedded byte for byte.
"""
import logging

import cv2
import numpy as np
from onnxruntime.capi.onnxruntime_pybind11_state import (EPFail, EngineError, Fail, InvalidArgument,
                                                         RuntimeException)
from PIL import Image

from .pipeline import load_models, scan
from .shadows import threads

__all__ = ['load_models', 'scan_photo']

# OpenCV's own pool would otherwise start one thread per visible CPU.
cv2.setNumThreads(threads())

# Smaller images are icons or thumbnails, never a page worth scanning.
MIN_SIDE = 96
# Longer photos are reduced to this long side first: a 12 MP phone photo
# (4032 px) scans the same at 3000 px, in less time and memory.
MAX_LONG_SIDE = 3000
# A fault inside the scan itself costs that photo its scan, not the job.
# MemoryError too: a photo too large for the child's memory is still a page.
# Missing or unreadable model files are raised by load_models() instead and
# fail the job: that is a deployment fault.
SCAN_ERRORS = (cv2.error, ValueError, RuntimeError, MemoryError, Fail, InvalidArgument, RuntimeException, EngineError,
               EPFail)
log = logging.getLogger(__name__)


def scan_photo(image, paper='auto'):
    """Scan one upload.

    ``image`` is PIL RGB (already EXIF-transposed and alpha-flattened);
    ``paper`` is 'auto', 'A4' or 'Letter'. Returns ``(image, outcome)`` where
    outcome is ``{'document_detected': bool, 'sheet': 'A4'|'Letter'|'Legal'|None}``.
    When no written page is found, the input object itself is returned. When
    the scan itself failed, the outcome also names the error as
    ``'scan_error'`` (its class name), which the engine counts in the job's
    metadata: the child's own log goes nowhere in production.
    """
    outcome = {'document_detected': False, 'sheet': None}
    if min(image.size) < MIN_SIDE:
        return image, outcome
    load_models()
    try:
        bgr = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
        long_side = max(bgr.shape[:2])
        if long_side > MAX_LONG_SIDE:
            scale = MAX_LONG_SIDE / long_side
            size = (max(1, round(bgr.shape[1] * scale)), max(1, round(bgr.shape[0] * scale)))
            bgr = cv2.resize(bgr, size, interpolation=cv2.INTER_AREA)
        result = scan(bgr, paper)
        if not result['found']:
            return image, outcome
        page = Image.fromarray(cv2.cvtColor(result['page'], cv2.COLOR_BGR2RGB))
    except SCAN_ERRORS as error:
        log.warning('Document scan failed, page kept as uploaded: %s', type(error).__name__)
        return image, {**outcome, 'scan_error': type(error).__name__}
    return page, {'document_detected': True, 'sheet': result['sheet']}
