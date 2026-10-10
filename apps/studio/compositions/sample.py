"""A sample deck that exercises everything a composition arranges, and its previews.

Used by tests/test_compositions.py and when designing or reviewing a
composition:

    python -m apps.studio.compositions.sample split /tmp/split.png

renders the sample deck in the composition (light, dark and bold, with and
without photos) and writes one contact sheet of every slide.
"""
import io
import tempfile
from pathlib import Path


def _section(sid, heading, body, layout, items=None):
    return {'id': sid, 'heading': heading, 'body': body, 'notes': '', 'layout': layout,
            'items': items or [], 'columns': [], 'image_query': ''}


def deck(locale='en'):
    """Ten slides: cover, dividers with and without a kicker, text, data, photos, closing."""
    if locale == 'ru':
        title = 'Приливы Северного моря и то, как они меняют берега Северной Европы'
        heading = 'Сизигийные и квадратурные приливы'
    else:
        title = 'How the tides of the North Sea shape the coasts of Northern Europe'
        heading = 'Spring tides and neap tides through the year'
    return {'title': title, 'questions': [], 'citations': [], 'sections': [
        _section('s1', title, 'A field guide for coastal walkers, sailors and anyone curious about the sea', 'cover'),
        _section('s2', heading, 'When the sun and the moon line up, the sea reaches furthest', 'section'),
        _section('s3', 'The moon pulls the water toward it',
                 'Gravity from the moon pulls the ocean toward it on the near side of the Earth.\n'
                 'A second bulge forms on the far side, where the pull is weakest.\n'
                 'Most coasts therefore see two high tides and two low tides every day.\n'
                 'The timing shifts by about fifty minutes from one day to the next.', 'bullets'),
        _section('s4', 'Two kinds of tide', '', 'two_column', [
            {'label': 'Spring tides', 'text': 'The sun and moon pull together, so high tides are higher.', 'value': ''},
            {'label': 'Neap tides', 'text': 'They pull at right angles, so the range is smallest.', 'value': ''}]),
        _section('s5', 'Reading the shore at low tide', 'Rock pools, sandbars and channels appear twice a day',
                 'image_split'),
        _section('s6', 'Living with the tides', '', 'section'),
        _section('s7', 'A sailor on the Wadden Sea',
                 'You learn to read the tide long before you learn to read the weather.', 'quote', [
            {'label': 'Anna de Vries', 'text': 'harbour master, Texel', 'value': ''}]),
        _section('s8', 'Tides by the numbers', '', 'stats', [
            {'label': 'Highest range', 'text': 'Bay of Fundy, Canada', 'value': '16 m'},
            {'label': 'Tides a day', 'text': 'On most coasts', 'value': '2'},
            {'label': 'Daily delay', 'text': 'Between high tides', 'value': '50 min'}]),
        _section('s9', 'The coast at dawn', 'Low tide reveals the sea floor for a few hours', 'image_full'),
        _section('s10', 'Thank you', 'Questions and walks welcome', 'closing'),
    ]}


def photo(colour=(46, 98, 140)):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (1600, 1000), colour)
    draw = ImageDraw.Draw(image)
    for row in range(0, 1000, 8):
        shade = tuple(min(255, c + row // 12) for c in colour)
        draw.line([(0, row), (1600, row)], fill=shade, width=8)
    draw.ellipse((980, 160, 1360, 540), fill=(250, 214, 140))
    buffer = io.BytesIO()
    image.save(buffer, 'JPEG', quality=85)
    return {'jpeg': buffer.getvalue(), 'width': 1600, 'height': 1000}


def photos():
    return {'s1': photo(), 's5': photo((84, 120, 70)), 's9': photo((120, 84, 60))}


def render(style, path, with_photos=False, locale='en'):
    """Render the sample deck with `style` (a template_style) to `path`; render_pptx's result."""
    from ..slides import render_pptx
    return render_pptx(deck(locale), Path(path), locale=locale, style={'brand_name': 'Acme Studio', **style},
                       photos=photos() if with_photos else None)


def sheet(composition, out, accent='#1F3A68', secondary='#E0A458', themes=('light', 'dark', 'bold')):
    """A contact sheet of the sample deck in `composition`, for each theme, with and without photos."""
    from . import preview
    from ..deck_designs import DESIGNS
    images, labels = [], []
    with tempfile.TemporaryDirectory() as folder:
        for theme in themes:
            for with_photos in (False, True):
                style = _style(composition, accent, secondary, theme)
                path = Path(folder) / f'{theme}-{with_photos}.pptx'
                result = render(style, path, with_photos)
                for number, image in enumerate(preview.slide_images(path, width=480), 1):
                    images.append(image)
                    labels.append(f'{theme}{" photos" if with_photos else ""} · {number} {result["metadata"]["layouts"][number - 1]}')
    preview.contact_sheet(images, columns=10, labels=labels).save(out)
    return out


def _style(composition, accent, secondary, theme):
    """A template_style that wears `composition` with the given colours (a throwaway design)."""
    from .. import deck_designs
    key = f'_sample_{composition}'
    deck_designs.DESIGNS[key] = {**deck_designs._design(accent, secondary, theme, 'Georgia', 'Calibri', 'sample',
                                                       composition=composition), 'category': 'sample'}
    return {'deck_design': key}


if __name__ == '__main__':
    import os
    import sys
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    import django
    django.setup()
    print(sheet(sys.argv[1], sys.argv[2]))
