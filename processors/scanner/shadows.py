"""Stage 4: remove shadows and uneven lighting from the flat page with GC-Net (ONNX, CPU).

GC-Net is the shading-estimation half of GCDRNet: it predicts the page's
shading map directly. It runs on a reduced copy of the page; its output is
turned into an illumination map (input / output), smoothed, upsampled and
divided out of the full-resolution page, so the result keeps all the page's
detail at a fraction of the cost. This is how GCDRNet's own inference applies
its model to large images. A final gain per channel makes the paper white.

This module also holds the shared ONNX Runtime setup (model folder, threads,
sessions) used by every stage.
"""
import os
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

# Model files: the folder named by SCANNER_MODELS (the image build fetches
# them there, pinned in models.json). A model missing there is also looked
# for in the package's models/ folder, which ships text_sr_x3.onnx.
BUNDLED = Path(__file__).resolve().parent / 'models'
MODELS = Path(os.environ.get('SCANNER_MODELS') or BUNDLED)
# Long side the model sees, chosen from the measured CPU cost: GC-Net takes
# ~60 ms at 1024 px on an M2 Pro. Its input sides must be multiples of 32.
SIZE = 1024
STRIDE = 32
_sessions = {}


def threads():
    """CPU threads for every model: SCANNER_THREADS, by default one.

    The worker sandbox limits CPU seconds and processes, so one thread keeps
    CPU time equal to wall time (a 34 MP photo took 3.0 s on one thread
    against 2.4 s on all cores of an M2 Pro).
    """
    return int(os.environ.get('SCANNER_THREADS') or 1)


def options():
    settings = ort.SessionOptions()
    settings.intra_op_num_threads = threads()
    # No memory arena: it keeps the largest buffers of every page size it has
    # seen and grows across a job's photos (macOS: 1.95 GB against 1.56 GB
    # over twelve photos). The pages are byte-identical either way.
    settings.enable_cpu_mem_arena = False
    return settings


def session(name):
    """The ONNX Runtime session for ``models/<name>.onnx``, loaded once."""
    if name not in _sessions:
        path = MODELS / f'{name}.onnx'
        if not path.is_file() and (BUNDLED / f'{name}.onnx').is_file():
            path = BUNDLED / f'{name}.onnx'
        if not path.is_file():
            raise FileNotFoundError(f'Scanner model {path} is missing: run scripts/fetch_scanner_models.py '
                                    'and point SCANNER_MODELS at its folder.')
        _sessions[name] = ort.InferenceSession(str(path), options(), providers=['CPUExecutionProvider'])
    return _sessions[name]


def _tensor(bgr):
    return (bgr.astype(np.float32) / 255).transpose(2, 0, 1)[None].astype(np.float32)


def _image(tensor):
    return np.clip(tensor[0].astype(np.float32).transpose(1, 2, 0), 0, 1)


def predict(low):
    """GC-Net's shadow-free version of ``low`` (BGR uint8), as BGR float in 0..1."""
    shading = np.clip(session('gcnet').run(['output'], {'input': _tensor(low)})[0], 1e-3, 1)
    return np.clip(low.astype(np.float32) / 255 / _image(shading), 0, 1)


def remove_shadows(page):
    """``page`` (BGR uint8, full resolution) with shadows and uneven light removed.

    The paper keeps its own tint here; whiten_paper() makes it white.
    """
    height, width = page.shape[:2]
    scale = min(1.0, SIZE / max(height, width))
    w = max(STRIDE, round(width * scale / STRIDE) * STRIDE)
    h = max(STRIDE, round(height * scale / STRIDE) * STRIDE)
    low = cv2.resize(page, (w, h), interpolation=cv2.INTER_AREA)
    clean = np.clip(predict(low), 1 / 255, 1)
    # The illumination map the model removed. Its ink-scale detail (the model's
    # own text edits) is smoothed away so only lighting is transferred.
    light = np.clip(low.astype(np.float32) / 255 / clean, 0.05, 4)
    light = cv2.medianBlur(light, 5)
    light = cv2.resize(light, (width, height), interpolation=cv2.INTER_LINEAR)
    return np.clip(page.astype(np.float32) / light, 0, 255).astype(np.uint8)


def whiten_paper(page):
    """One gain per channel that makes the paper neutral white (245)."""
    return np.clip(page.astype(np.float32) * (245 / paper_colour(page.astype(np.float32))), 0, 255).astype(np.uint8)


def paper_colour(bgr):
    """Median colour of the brighter half of the page: the paper, not the print."""
    pixels = cv2.resize(bgr, (256, 256), interpolation=cv2.INTER_AREA).reshape(-1, 3)
    brightness = pixels.sum(axis=1)
    return np.maximum(np.median(pixels[brightness >= np.median(brightness)], axis=0), 1)
