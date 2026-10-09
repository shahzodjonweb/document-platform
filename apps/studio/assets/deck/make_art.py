"""Draw the decorative masks deck designs put on covers and dividers.

Run once and commit the PNGs: `python apps/studio/assets/deck/make_art.py`.
Each mask is greyscale — white is ink, black is clear — at `slides.ART_PPI`
pixels per inch and square at `SIZE`, so the widest art zone on a 13.333 in
slide crops from it without tiling. The renderer tints a crop in the deck's own
colour, so one mask serves every design that uses it. Seeds are fixed: running
this again writes the same files.
"""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1600
SCALE = 2  # drawn at twice the size, then reduced, for smooth edges
HERE = Path(__file__).resolve().parent


def canvas():
    image = Image.new('L', (SIZE * SCALE, SIZE * SCALE), 0)
    return image, ImageDraw.Draw(image)


def finish(image):
    return image.resize((SIZE, SIZE), Image.LANCZOS)


def px(inches):
    return round(inches * 120 * SCALE)


def dots():
    image, draw = canvas()
    step, radius = px(0.3), px(0.05)
    for row, y in enumerate(range(0, image.height + step, step)):
        offset = step // 2 if row % 2 else 0
        for x in range(-step, image.width + step, step):
            cx = x + offset
            draw.ellipse((cx - radius, y - radius, cx + radius, y + radius), fill=255)
    return finish(image)


def grid():
    image, draw = canvas()
    step, width = px(0.42), max(2, px(0.012))
    for value in range(0, image.width + step, step):
        draw.line((value, 0, value, image.height), fill=255, width=width)
        draw.line((0, value, image.width, value), fill=255, width=width)
    return finish(image)


def lines():
    image, draw = canvas()
    step, width = px(0.22), px(0.03)
    for start in range(-image.height, image.width + image.height, step):
        draw.line((start, image.height, start + image.height, 0), fill=255, width=width)
    return finish(image)


def waves():
    image, draw = canvas()
    step, width = px(0.3), px(0.03)
    amplitude, period = px(0.12), px(1.6)
    for base in range(-step, image.height + step, step):
        points = [(x, base + amplitude * math.sin(2 * math.pi * x / period))
                  for x in range(0, image.width + 8, 8)]
        draw.line(points, fill=255, width=width, joint='curve')
    return finish(image)


def rings():
    image, draw = canvas()
    cx, cy = image.width, 0  # centred on the corner crops are taken from
    step, width = px(0.28), px(0.025)
    for radius in range(step, int(image.width * 1.5), step):
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), outline=255, width=width)
    return finish(image)


def arcs():
    image, draw = canvas()
    rng = random.Random(7)
    width = px(0.045)
    # Crops are taken from the top-right corner, so that is where most arcs are.
    for _ in range(46):
        cx = image.width - abs(rng.gauss(0, image.width * 0.35))
        cy = abs(rng.gauss(0, image.height * 0.35))
        radius = rng.randrange(px(0.4), px(2.2))
        start = rng.randrange(0, 360)
        draw.arc((cx - radius, cy - radius, cx + radius, cy + radius), start, start + rng.randrange(60, 180),
                 fill=255, width=width)
    return finish(image)


def triangles():
    image, draw = canvas()
    side = px(0.7)
    height = side * math.sqrt(3) / 2
    rng = random.Random(11)
    rows = int(image.height / height) + 2
    for row in range(rows):
        for column in range(int(image.width / side) * 2 + 4):
            x = column * side / 2 - side
            y = row * height
            up = (row + column) % 2 == 0
            points = ([(x, y + height), (x + side / 2, y), (x + side, y + height)] if up
                      else [(x, y), (x + side, y), (x + side / 2, y + height)])
            shade = rng.choice((0, 0, 70, 140, 255))
            if shade:
                draw.polygon(points, fill=shade)
    return finish(image)


def hexagons():
    image, draw = canvas()
    radius, width = px(0.32), px(0.022)
    w, h = math.sqrt(3) * radius, 1.5 * radius
    for row in range(int(image.height / h) + 2):
        for column in range(int(image.width / w) + 2):
            cx = column * w + (w / 2 if row % 2 else 0)
            cy = row * h
            points = [(cx + radius * math.cos(math.radians(60 * k + 30)),
                       cy + radius * math.sin(math.radians(60 * k + 30))) for k in range(7)]
            draw.line(points, fill=255, width=width, joint='curve')
    return finish(image)


def confetti():
    image, draw = canvas()
    rng = random.Random(3)
    for _ in range(420):
        x, y = rng.randrange(image.width), rng.randrange(image.height)
        size = rng.randrange(px(0.04), px(0.12))
        kind = rng.random()
        if kind < 0.4:
            draw.ellipse((x - size, y - size, x + size, y + size), fill=255)
        elif kind < 0.75:
            angle = rng.random() * math.pi
            dx, dy = math.cos(angle) * size * 1.6, math.sin(angle) * size * 1.6
            draw.line((x - dx, y - dy, x + dx, y + dy), fill=255, width=max(2, size // 2))
        else:
            draw.regular_polygon((x, y, size * 1.2), 3, rotation=rng.randrange(360), fill=255)
    return finish(image)


def topo():
    import numpy
    rng = random.Random(5)
    side = SIZE * SCALE
    axis = numpy.arange(side, dtype=numpy.float64)
    field = numpy.zeros((side, side))
    for _ in range(18):
        cx, cy = rng.uniform(0, side), rng.uniform(0, side)
        spread = rng.uniform(side * 0.08, side * 0.3)
        weight = rng.uniform(-1, 1)
        field += weight * numpy.outer(numpy.exp(-(axis - cy) ** 2 / (2 * spread ** 2)),
                                      numpy.exp(-(axis - cx) ** 2 / (2 * spread ** 2)))
    levels = field * 14
    # Distance to the nearest contour in pixels: the value's distance to a whole
    # level over how fast the value changes. Lines come out the same width
    # however steep the slope.
    dy, dx = numpy.gradient(levels)
    slope = numpy.hypot(dx, dy) + 1e-9
    fraction = levels - numpy.floor(levels)
    distance = numpy.minimum(fraction, 1 - fraction) / slope
    half = px(0.012)
    ink = numpy.clip((half + 1 - distance) * 255, 0, 255)
    # Four grey steps of antialiasing are plenty once reduced, and compress well.
    ink = (numpy.round(ink / 85) * 85).astype(numpy.uint8)
    return finish(Image.fromarray(ink, 'L'))


def glow():
    image, draw = canvas()
    rng = random.Random(9)
    for _ in range(5):
        x, y = rng.randrange(image.width), rng.randrange(image.height)
        radius = rng.randrange(px(1.0), px(2.6))
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=rng.randrange(150, 256))
    return finish(image.filter(ImageFilter.GaussianBlur(px(0.6))))


def plus():
    image, draw = canvas()
    step, arm, width = px(0.4), px(0.07), px(0.025)
    for row, y in enumerate(range(0, image.height + step, step)):
        for x in range(0, image.width + step, step):
            cx = x + (step // 2 if row % 2 else 0)
            draw.line((cx - arm, y, cx + arm, y), fill=255, width=width)
            draw.line((cx, y - arm, cx, y + arm), fill=255, width=width)
    return finish(image)


def blobs():
    # Drawn on a margin and cut back, so blur does not leave a band at the edge.
    margin = px(0.6)
    side = SIZE * SCALE
    image = Image.new('L', (side + 2 * margin, side + 2 * margin), 0)
    draw = ImageDraw.Draw(image)
    rng = random.Random(13)
    for _ in range(28):
        x = margin + side - abs(rng.gauss(0, side * 0.3))
        y = margin + abs(rng.gauss(0, side * 0.4))
        rx, ry = rng.randrange(px(0.3), px(1.3)), rng.randrange(px(0.3), px(1.3))
        draw.ellipse((x - rx, y - ry, x + rx, y + ry), fill=rng.choice((110, 170, 255)))
    soft = image.filter(ImageFilter.GaussianBlur(px(0.08)))
    return finish(soft.crop((margin, margin, margin + side, margin + side)))


PATTERNS = {name: function for name, function in globals().items()
            if name in ('dots', 'grid', 'lines', 'waves', 'rings', 'arcs', 'triangles', 'hexagons',
                        'confetti', 'topo', 'glow', 'plus', 'blobs')}


if __name__ == '__main__':
    for name, draw_mask in PATTERNS.items():
        mask = draw_mask()
        assert mask.size == (SIZE, SIZE) and mask.mode == 'L'
        mask.save(HERE / f'{name}.png', optimize=True)
        print(name, (HERE / f'{name}.png').stat().st_size // 1024, 'KB')
