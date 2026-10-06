"""How a PDF document looks, and which section layouts it may use.

A document is plain by default: black headings, black text, one flowing column.
That is what most people want from "write me a document about…", and colour
they did not ask for reads as decoration. So:

* **Five text designs.** `plain` is the default. The other four each add one
  accent colour and a little structure (numbered headings, a heading bar, a
  tinted heading band, ruled headings). The model may choose one only when the
  description asks for a look, a style or a colour.
* **Five layouts.** `text` (a heading and paragraphs) is the default. `image`,
  `table`, `list` and `callout` exist for descriptions that ask for pictures,
  tables, lists or highlighted points, and the model is only offered them then.

Whether the description asks is read from its words, in English, Uzbek and
Russian, the same way the page count and a deck's colour are. A miss costs
nothing: the document is still written, in the plain look.
"""
import re
import unicodedata

# id: heading colour, structure, when it fits.
DESIGNS = {
    'plain': {'accent': '#111111', 'style': 'plain',
              'fits': 'black and white; the default, and any document whose description does not ask for a look'},
    'academic': {'accent': '#1F3A68', 'style': 'numbered',
                 'fits': 'navy numbered headings, justified text; reports, essays, coursework, research, formal'},
    'modern': {'accent': '#0062D6', 'style': 'bar',
               'fits': 'blue headings with a side bar; business, technology, product, guides, colourful but clean'},
    'elegant': {'accent': '#7A1F35', 'style': 'ruled',
                'fits': 'burgundy ruled headings, centred title; literature, history, culture, invitations, programmes'},
    'fresh': {'accent': '#0F766E', 'style': 'band',
              'fits': 'teal headings on a tinted band; education, health, nature, children, friendly handouts'},
}
DESIGN_IDS = list(DESIGNS)
DEFAULT_DESIGN = 'plain'
# The accent every document template once had. On a document that never chose a
# design it means "nobody picked a colour", so it renders plain.
LEGACY_ACCENT = '#255e49'

LAYOUTS = {
    'text': 'a heading (or none, when continuing the previous topic) and paragraphs; the default',
    'image': 'paragraphs with one photo: image_query = 2-4 plain English words naming what the photo shows',
    'table': 'paragraphs and a table: columns = 2-3 headers, items = rows (label, text, value are the cells)',
    'list': 'paragraphs and a list: items with label = the point, text = one or two sentences',
    'callout': 'paragraphs and a highlighted box: items with label = key point, text = one sentence',
}
LAYOUT_IDS = list(LAYOUTS)

# What in a description asks for more than prose. Stems, so plural and case
# endings match in all three languages.
_RICH = re.compile(
    r'\b(?:image|picture|photo|illustrat|visual|diagram|chart|graph|infographic|table|tabular|'
    r'bullet|list|checklist|steps?\b|callout|highlight|key\s+points|box|'
    r'rasm|surat|fotosurat|tasvir|illyustr|vizual|diagramma|grafik|jadval|ro.?yxat|qadam|'
    r'muhim\s+fikr|ramka|'
    r'изображ|картин|фото|иллюстрац|визуал|наглядн|диаграм|график|таблиц|список|спис|пункт|шаг|'
    r'выделен|ключев\w*\s+(?:мысл|момент|пункт))',
    re.IGNORECASE | re.UNICODE)
_IMAGES = re.compile(
    r'\b(?:image|picture|photo|illustrat|visual|rasm|surat|fotosurat|tasvir|illyustr|vizual|'
    r'изображ|картин|фото|иллюстрац|визуал|наглядн)',
    re.IGNORECASE | re.UNICODE)
_STYLE = re.compile(
    r'\b(?:design|style|styled|colou?r|colorful|colourful|theme|beautiful|elegant|modern|'
    r'academic|formal|creative|attractive|fancy|stylish|'
    r'dizayn|uslub|rang|chiroyli|zamonaviy|nafis|akademik|'
    r'дизайн|стил|цвет|красив|элегант|современ|академич|оформлен)',
    re.IGNORECASE | re.UNICODE)


def _plain(text):
    return unicodedata.normalize('NFKC', str(text or '')).replace('ʻ', "'").replace('‘', "'").replace('’', "'")


def asks_for_layouts(text):
    """Whether the description asks for pictures, tables, lists or highlighted points."""
    return bool(_RICH.search(_plain(text)))


def asks_for_images(text):
    return bool(_IMAGES.search(_plain(text)))


def asks_for_design(text):
    """Whether the description asks for a look, a style or a colour."""
    from .pages import requested_accent
    body = _plain(text)
    return bool(_STYLE.search(body)) or requested_accent(body) is not None


def reference(layouts=False, design=False, images=0):
    """What the model reads about this document's look, only the parts it may use."""
    parts = []
    if design:
        parts.append(
            'When the response has a `design` field, choose the look of the whole document from this '
            'list, matching what the description asks for. Choose plain unless it asks for a style, '
            'a look or colours; when it names colours, choose a design other than plain.\n'
            + '\n'.join(f'- {key}: {value["fits"]}' for key, value in DESIGNS.items()))
    if layouts:
        lines = [f'- {key}: {guide}' for key, guide in LAYOUTS.items() if key != 'image' or images]
        parts.append(
            'Choose a layout for every section from this list. Most sections are text; use table, '
            'list, callout' + (' or image' if images else '') + ' only where the description asks for '
            'them or the content is naturally a table or a list. Fill only the fields the layout uses '
            'and leave the others empty ("" or []). Never invent figures.\n' + '\n'.join(lines)
            + (f'\nUse the image layout on at most {images} section{"s" if images != 1 else ""}.'
               if images else '\nDo not use the image layout; leave image_query empty.'))
    return '\n'.join(parts)


def look(style):
    """The design a document is drawn with, with the customer's own colour on top."""
    style = style or {}
    chosen = style.get('doc_design')
    fixed = bool(style.get('accent_fixed') and style.get('accent'))
    if chosen not in DESIGNS:
        accent = style.get('accent') or LEGACY_ACCENT
        # A document that never chose a design: plain, unless a template or the
        # customer gave it a colour of its own.
        if fixed or accent.lower() != LEGACY_ACCENT:
            return {'id': '', 'accent': accent, 'style': 'plain'}
        return {'id': DEFAULT_DESIGN, **{k: v for k, v in DESIGNS[DEFAULT_DESIGN].items() if k != 'fits'}}
    design = DESIGNS[chosen]
    return {'id': chosen, 'accent': style['accent'] if fixed else design['accent'], 'style': design['style']}


def remember(data, raw, *, replace=False):
    """Keep the model's choice with the draft, where revisions inherit it."""
    choice = (raw or {}).get('design')
    if choice not in DESIGNS:
        return
    style = data.setdefault('options', {}).setdefault('template_style', {})
    if replace or not style.get('doc_design'):
        style['doc_design'] = choice


def wanted(data, first=0):
    """Whether this provider call should choose a document's design."""
    options = data.get('options') or {}
    if data.get('output_format') == 'pptx' or not options.get('wants_design') or first:
        return False
    if data.get('revision', {}).get('selected_section_ids'):
        return False
    # A change request that asks for a look may choose again; otherwise once.
    return bool(data.get('revision')) or not options.get('template_style', {}).get('doc_design')


def clean_fields(section):
    """A document section's layout fields, bounded; empty when it is plain text.

    Raises ValueError on a shape no model can produce under the schema.
    """
    from .layouts import MAX_COLUMNS, MAX_ITEMS, _item, clean_query
    layout = str(section.get('layout') or 'text')
    if layout not in LAYOUTS:
        raise ValueError('layout')
    items, columns = section.get('items') or [], section.get('columns') or []
    if not isinstance(items, list) or not isinstance(columns, list):
        raise ValueError('shape')
    items = [item for item in (_item(value) for value in items) if any(item.values())][:MAX_ITEMS * 2]
    columns = [str(column or '').strip()[:80] for column in columns[:MAX_COLUMNS]]
    columns = columns if any(columns) else []
    query = clean_query(section.get('image_query', ''))
    if layout == 'text' and not items and not columns and not query:
        return {}
    return {'layout': layout, 'items': items, 'columns': columns, 'image_query': query}
