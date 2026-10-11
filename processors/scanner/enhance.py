"""AI text upscaling: rebuild text at a higher resolution right after dewarping.

Phone photos give pages of ~0.9-2 MP, so body text is 5-8 px tall; every
later step then breaks thin strokes and draws jagged letters. Upscaling the
page first lets shadow removal and the final look work on clean, smooth
strokes and keeps signatures and handwriting whole.

The model is Intel's text-image-super-resolution-0001 (Apache-2.0, Open Model
Zoo), rebuilt as ONNX (models/text_sr_x3.onnx): ~2.7K weights, grey in, 3x
out, trained on clean scanned text, ~0.1 s per page. It runs on the page as
photographed (shadows included); shadow removal follows on the upscaled page.
Fed shadows and grey fills it draws speckles, so its output is kept as is on
every stroke and smoothed only in flat areas of the original (paper, shadows,
shaded cells), found by their low local contrast. Colour is enlarged smoothly
and recombined with the model's lightness.
"""
import cv2
import numpy as np

from .shadows import session

# Upscale until the page's long side is about this (2x for a typical phone
# page); pages already this large are left alone.
TARGET_LONG_SIDE = 2200
MAX_SCALE = 2.0
FLAT_CONTRAST = 36
# The model runs on strips of this many rows: its 3x layers on a whole
# 1100 x 850 page hold ~1.6 GB at once, a strip ~0.2 GB. A pixel of its output
# depends on input rows within 3 of its own, so strips that overlap by OVERLAP
# rows give the very same floats as one run (measured: bit-identical).
STRIP_ROWS = 128
OVERLAP = 8


def scale_for(page):
    return min(MAX_SCALE, TARGET_LONG_SIDE / max(page.shape[:2]))


def text_model(grey):
    """Intel's model on ``grey`` (uint8): its 3x output as float, run strip by strip."""
    height = grey.shape[0]
    out = np.empty((3 * height, 3 * grey.shape[1]), np.float32)
    for top in range(0, height, STRIP_ROWS):
        bottom = min(height, top + STRIP_ROWS)
        start, stop = max(0, top - OVERLAP), min(height, bottom + OVERLAP)
        strip = session('text_sr_x3').run(None, {'image': grey[start:stop].astype(np.float32)[None, None]})[0][0, 0]
        out[3 * top:3 * bottom] = strip[3 * (top - start):3 * (bottom - start)]
    return out


def text_upscale(page):
    """The photographed page (BGR) rebuilt at up to 2x as grey, with Intel's text model."""
    grey = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    scale = scale_for(grey)
    if scale <= 1.05:
        return grey
    size = (round(grey.shape[1] * scale), round(grey.shape[0] * scale))
    out = text_model(grey)
    sharp = cv2.resize((np.clip(out, 0, 1) * 255).astype(np.uint8), size, interpolation=cv2.INTER_AREA)
    # Flat areas of the original: little local contrast, away from strokes.
    values = grey.astype(np.float32)
    contrast = cv2.dilate(values, np.ones((5, 5))) - cv2.erode(values, np.ones((5, 5)))
    flat = cv2.erode((contrast < FLAT_CONTRAST).astype(np.uint8), np.ones((3, 3), np.uint8))
    flat = cv2.GaussianBlur(cv2.resize(flat, size, interpolation=cv2.INTER_NEAREST).astype(np.float32), (0, 0), 1.5)
    smooth = cv2.GaussianBlur(sharp, (0, 0), 2.5).astype(np.float32)
    return np.clip(smooth * flat + sharp.astype(np.float32) * (1 - flat), 0, 255).astype(np.uint8)


def upscale(page):
    """The colour page (BGR) at up to 2x: Intel's model on lightness, colour (chroma) enlarged smoothly."""
    lab = cv2.cvtColor(page, cv2.COLOR_BGR2LAB)
    lightness = text_upscale(page)  # grey = lightness-like, flat areas smoothed
    size = lightness.shape[1::-1]
    if size == page.shape[1::-1]:
        return page
    chroma = cv2.resize(lab[:, :, 1:], size, interpolation=cv2.INTER_CUBIC)
    # The model's lightness with the photo's colour (chroma) enlarged smoothly.
    lab_big = np.dstack([lightness, chroma])
    return cv2.cvtColor(lab_big, cv2.COLOR_LAB2BGR)
