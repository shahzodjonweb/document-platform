"""Fifty looks a CV can wear, in six categories, and how one is chosen.

A template is a drawer (one of eight ways of arranging a CV on the page, see
`layouts.py`), two colours, a paper or sidebar tint, a pair of type faces and a
tone. The accent is the one colour text is set in besides ink: headings, the
headline, a band or a sidebar. The second colour is decoration only — rules,
timeline dots, a photo ring — and never carries text, so a pale second colour
cannot make anything hard to read.

`tone` says what the colour does: `light` puts ink on a pale tint (or on white),
`dark` fills the sidebar or band with a deep colour and sets white text on it,
and `paper` lays the whole page on the tint.

The default, and what *Auto* comes to unless the description clearly calls for
something else, is `classic_navy`: one calm column that suits any profession.
A customer can pick any template on the setup screen (`options.cv_template`);
that pick beats the model's. The model chooses only on the first call of a CV
that has none yet, or on a change that asks for a new look, and the choice is
kept in the draft's style (`options.template_style.cv_template`) so revisions
keep it.
"""
import functools

DRAWERS = ('column', 'sidebar_left', 'sidebar_right', 'band', 'centered', 'timeline', 'compact', 'executive')
# Drawers with a place for a portrait. A photo template on any other drawer would
# promise a picture it cannot show.
PHOTO_DRAWERS = frozenset({'column', 'sidebar_left', 'sidebar_right', 'band', 'compact'})
# (heading face, body face).
FONT_PAIRS = {'sans': ('CVSans', 'CVSans'), 'serif': ('CVSerif', 'CVSerif'), 'mixed': ('CVSerif', 'CVSans'),
              'inverse': ('CVSans', 'CVSerif')}
TONES = ('light', 'dark', 'paper')
INK = '#1A1A1A'
WHITE = '#FFFFFF'
DEFAULT_TEMPLATE = 'classic_navy'
LOCALES = ('en', 'uz', 'ru')


def _template(drawer, accent, secondary, tint, fonts, fits, *, photo=False, tone='light'):
    return {'drawer': drawer, 'accent': accent, 'secondary': secondary, 'tint': tint, 'fonts': fonts,
            'fits': fits, 'photo': photo, 'tone': tone}


CLASSIC = {
    'classic_navy': _template('column', '#1F3A68', '#B08D57', None, 'mixed',
                              'the default: navy headings, serif name, one column; any profession'),
    'charter': _template('column', '#14284B', '#C9A227', None, 'serif',
                         'all-serif navy, formal; law, finance, government'),
    'ledger': _template('column', '#2B2F33', '#9CA3AF', None, 'sans',
                        'charcoal plain sans; accounting, administration, engineering'),
    'forest_classic': _template('column', '#1E6B45', '#B08D57', None, 'mixed',
                                'deep green; agriculture, environment, healthcare'),
    'burgundy_rule': _template('column', '#7A1F35', '#B08D57', None, 'serif',
                               'burgundy ruled headings; humanities, education, culture'),
    'oxford': _template('timeline', '#0B3954', '#B08D57', None, 'serif',
                        'dated timeline in serif; teachers, researchers, lecturers'),
    'ivory': _template('column', '#3B2540', '#B08D57', '#FAF5EA', 'mixed',
                       'aubergine on ivory paper; publishing, museums, arts administration', tone='paper'),
    'slate_portrait': _template('column', '#37474F', '#90A4AE', None, 'sans',
                                'slate sans with a photo top right; office roles, logistics, retail', photo=True),
    'heritage': _template('column', '#4E342E', '#A1887F', '#F6F1EA', 'serif',
                          'walnut serif on warm paper; hospitality, trades, family business', tone='paper'),
}

MODERN = {
    'azure_side': _template('sidebar_left', '#0F4C81', '#5DA9E9', '#EAF2FA', 'sans',
                            'blue sidebar with photo and skills; IT, product, marketing', photo=True),
    'mint_side': _template('sidebar_left', '#0F766E', '#5EC4B6', '#E8F5F2', 'sans',
                           'teal sidebar; healthcare, pharmacy, biotech', photo=True),
    'coral_band': _template('band', '#9F1239', '#FB7185', None, 'sans',
                            'deep coral header band with photo; sales, PR, events', photo=True, tone='dark'),
    'indigo_band': _template('band', '#3730A3', '#818CF8', None, 'sans',
                             'indigo band, no photo; software, data, analytics', tone='dark'),
    'teal_timeline': _template('timeline', '#0E7490', '#67E8F9', None, 'sans',
                               'timeline for many dates; project management, consulting'),
    'cobalt_right': _template('sidebar_right', '#1E40AF', '#93C5FD', '#EAF0FB', 'sans',
                              'photo and contacts on the right; engineering, architecture, QA', photo=True),
    'plum_side': _template('sidebar_left', '#6A1B9A', '#CE93D8', '#F3E8F7', 'inverse',
                           'plum sidebar, serif body; HR, psychology, education', photo=True),
    'steel_band': _template('band', '#37474F', '#B0BEC5', None, 'sans',
                            'steel-grey band; manufacturing, operations, security', photo=True, tone='dark'),
    'olive_right': _template('sidebar_right', '#365314', '#A3B18A', '#EEF2E6', 'mixed',
                             'olive sidebar, no photo; agronomy, environment, NGOs'),
}

MINIMAL = {
    'hairline': _template('centered', '#1C1917', '#A8A29E', None, 'sans',
                          'centred black type, hairline rules; any profession, print-safe'),
    'mono_ink': _template('column', '#212121', '#9E9E9E', None, 'sans',
                          'black sans, no colour; developers, editors, analysts'),
    'quiet_sage': _template('centered', '#44403C', '#8A9A5B', None, 'mixed',
                            'warm grey with a sage rule; designers, writers, architects'),
    'dove': _template('column', '#525252', '#BDBDBD', None, 'inverse',
                      'dove grey, serif body; translators, librarians, administrators'),
    'thin_navy': _template('centered', '#14284B', '#14284B', None, 'sans',
                           'navy name, the rest black; banking, audit, legal support'),
    'nordic': _template('compact', '#263238', '#78909C', None, 'sans',
                        'compact two-column grey; long careers that must fit a page'),
    'paper_grey': _template('column', '#374151', '#9CA3AF', '#F5F5F4', 'sans',
                            'grey on stone paper; civil service, procurement, logistics', tone='paper'),
    'ash_portrait': _template('compact', '#1F2937', '#9CA3AF', None, 'sans',
                              'compact with a small photo; medicine, aviation, hospitality', photo=True),
}

CREATIVE = {
    'sunset_band': _template('band', '#BF360C', '#FFB74D', None, 'sans',
                             'burnt-orange band with photo; graphic design, media, advertising', photo=True,
                             tone='dark'),
    'magenta_side': _template('sidebar_left', '#880E4F', '#F48FB1', '#FBE9F0', 'sans',
                              'magenta sidebar; fashion, beauty, event planning', photo=True),
    'violet_timeline': _template('timeline', '#5B21B6', '#C4B5FD', None, 'sans',
                                 'violet timeline; UX, content, creative direction'),
    'tangerine_right': _template('sidebar_right', '#C2410C', '#FDBA74', '#FDF1E7', 'inverse',
                                 'tangerine sidebar on the right; photographers, video, music', photo=True),
    'ocean_dark': _template('sidebar_left', '#0B3954', '#FF5A5F', '#0B3954', 'sans',
                            'dark navy sidebar, white text, coral rule; startups, product design', photo=True,
                            tone='dark'),
    'raspberry_band': _template('band', '#9D174D', '#F9A8D4', None, 'mixed',
                                'raspberry band with a serif name; journalism, PR, publishing', photo=True,
                                tone='dark'),
    'mustard_left': _template('sidebar_left', '#854D0E', '#FACC15', '#FBF3D5', 'sans',
                              'mustard-tinted sidebar, brown headings; illustration, animation, crafts', photo=True),
    'aqua_compact': _template('compact', '#006064', '#4DD0E1', None, 'sans',
                              'aqua compact two-column; game design, 3D, motion', photo=True),
}

EXECUTIVE = {
    'boardroom_cv': _template('executive', '#1F3A68', '#C9A227', None, 'serif',
                              'navy serif, headings in the left margin, gold rule; directors, CFOs'),
    'mahogany': _template('executive', '#5D4037', '#C9A227', '#FAF5EA', 'serif',
                          'mahogany on ivory; partners, consultants, lawyers', tone='paper'),
    'onyx': _template('executive', '#212121', '#C9A227', None, 'mixed',
                      'black and gold; luxury, hospitality, real-estate executives'),
    'royal_exec': _template('executive', '#4527A0', '#E0A458', None, 'serif',
                            'royal purple serif; founders, non-profit leaders, deans'),
    'midnight_exec': _template('band', '#1F2937', '#C9A227', None, 'mixed',
                               'dark band, gold details, photo; general managers, country heads', photo=True,
                               tone='dark'),
    'emerald_exec': _template('executive', '#065F46', '#B08D57', None, 'mixed',
                              'emerald serif headings; finance, sustainability, banking'),
    'bronze': _template('executive', '#78350F', '#D4A017', None, 'serif',
                        'bronze and brown; engineering and manufacturing directors'),
    'pinstripe': _template('column', '#263238', '#C9A227', None, 'serif',
                           'charcoal serif with a thin gold rule; strategy, investment'),
}

ACADEMIC = {
    'scholar_cv': _template('timeline', '#7A1F35', '#B08D57', None, 'serif',
                            'burgundy serif timeline; lecturers, PhD candidates, publications'),
    'lab': _template('sidebar_left', '#01579B', '#4FC3F7', '#E8F4FB', 'sans',
                     'lab-blue sidebar for methods and skills; chemists, biologists, technicians'),
    'circuit_dark': _template('sidebar_left', '#00695C', '#80CBC4', '#0F2E2A', 'sans',
                              'dark green sidebar, white text; electronics, DevOps, network engineers', photo=True,
                              tone='dark'),
    'campus': _template('column', '#1565C0', '#90CAF9', None, 'sans',
                        'campus blue single column; students, graduates, first jobs'),
    'archive': _template('centered', '#4E342E', '#BCAAA4', '#F6F1EA', 'serif',
                         'serif on warm paper; historians, archivists, linguists', tone='paper'),
    'research_timeline': _template('timeline', '#283593', '#9FA8DA', None, 'mixed',
                                   'indigo timeline for grants and papers; researchers, clinicians'),
    'data_band': _template('band', '#0D47A1', '#64B5F6', None, 'sans',
                           'blue data band; data scientists, statisticians, BI analysts', tone='dark'),
    'syntax': _template('compact', '#1F2937', '#10B981', None, 'sans',
                        'compact charcoal with a green rule; software engineers with many stacks'),
}

# id: (templates, (English, Uzbek, Russian)) — in the order the picker and the model see them.
CATEGORIES = {
    'classic': (CLASSIC, ('Classic', 'Klassik', 'Классика')),
    'modern': (MODERN, ('Modern', 'Zamonaviy', 'Современные')),
    'minimal': (MINIMAL, ('Minimal', 'Minimal', 'Минимализм')),
    'creative': (CREATIVE, ('Creative', 'Ijodiy', 'Творческие')),
    'executive': (EXECUTIVE, ('Executive', 'Rahbarlar uchun', 'Для руководителей')),
    'academic': (ACADEMIC, ('Academic & technical', 'Ilmiy va texnik', 'Научные и технические')),
}
TEMPLATES = {key: {**value, 'category': category}
             for category, (templates, _) in CATEGORIES.items() for key, value in templates.items()}
TEMPLATE_IDS = list(TEMPLATES)
# Templates taken out of the catalogue, and the one that replaces each, so a
# draft or a revision that remembers a retired id keeps a look of the same mood.
RETIRED = {}


def current(key):
    """The template to use for `key`: itself, or the one that replaced it."""
    return RETIRED.get(key, key)


def _hex(value):
    return '#' + str(value or '').lstrip('#').upper()


def fill_of(accent, tint, tone):
    """The colour a template's sidebar or band is filled with.

    A dark template fills it with its tint when it has one, else its accent,
    darkened only as far as white text needs; a light one is tinted, and a
    template without a sidebar or band shows its accent as its one block colour.
    """
    from apps.studio.slides import _darken_for
    if tone == 'dark':
        return _hex(_darken_for('FFFFFF', (tint or accent).lstrip('#')))
    return _hex(accent)


def reference(photo=False):
    """What the model reads when it chooses a template.

    Grouped by category so fifty entries stay easy to choose from; the default
    is named first so a description that says nothing about looks gets the
    calm classic one. The text depends only on whether the customer sent a
    portrait, which is fixed for a draft.
    """
    blocks = []
    for category, (templates, names) in CATEGORIES.items():
        lines = '\n'.join(f'- {key}: {value["fits"]}' + (' (photo)' if value['photo'] else '')
                          for key, value in templates.items())
        blocks.append(f'{names[0]}:\n{lines}')
    note = (' The customer sent a portrait: prefer a template marked (photo).' if photo else
            ' A template marked (photo) has a place for a portrait; without one it still looks complete.')
    return (
        'When the response has a `design` field, choose the CV template by the profession, seniority and tone '
        'the description shows. Choose `classic_navy` unless another clearly fits better.'
        + note + '\n' + '\n'.join(blocks)
    )


def _name(key):
    return ' '.join('CV' if word == 'cv' else word.title() for word in key.split('_'))


@functools.lru_cache(maxsize=4)
def catalogue(locale='en'):
    """The templates as a picker shows them: grouped, named, with the colours they render in.

    Fixed data, so it is worked out once per locale and process; do not change what it returns.
    """
    column = {'en': 0, 'uz': 1, 'ru': 2}.get(locale, 0)
    locale = locale if locale in LOCALES else 'en'
    stamp = version()
    groups = []
    for category, (templates, names) in CATEGORIES.items():
        entries = []
        for key in templates:
            shown = look({'cv_template': key})
            heading, body = FONT_PAIRS[shown['fonts']]
            entries.append({
                'id': key, 'name': _name(key), 'category': category, 'drawer': shown['drawer'],
                'photo': shown['photo'], 'tone': shown['tone'],
                'preview': f'/api/v1/studio/cv-templates/{key}.png?locale={locale}&v={stamp}',
                'fonts': {'heading': 'serif' if heading == 'CVSerif' else 'sans',
                          'body': 'serif' if body == 'CVSerif' else 'sans'},
                'colours': {'accent': shown['accent'], 'secondary': shown['secondary'],
                            'tint': shown['tint'] or WHITE, 'ink': INK, 'fill': shown['fill']}})
        groups.append({'id': category, 'name': names[column], 'templates': entries})
    return groups


def version():
    """Changes whenever a template or the code that draws one changes: thumbnails are cached by it."""
    import hashlib
    from pathlib import Path
    digest = hashlib.sha256(repr(sorted((key, sorted(value.items())) for key, value in TEMPLATES.items())).encode())
    folder = Path(__file__).resolve().parent
    for name in ('layouts.py', 'render.py', 'sample.py', 'fonts.py'):
        digest.update((folder / name).read_bytes())
    return digest.hexdigest()[:12]


@functools.lru_cache(maxsize=256)
def thumbnail(key, locale='en', width=480):
    """PNG of page 1 of the short sample CV in `key`, as the template picker shows it."""
    import io
    import tempfile
    from pathlib import Path
    import pypdfium2
    from . import sample
    from .render import render_cv
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'thumbnail.pdf'
        render_cv(sample.short(locale), path, locale=locale, style={'cv_template': key},
                  portrait=sample.portrait() if TEMPLATES[key]['photo'] else None)
        document = pypdfium2.PdfDocument(str(path))
        try:
            page = document[0]
            image = page.render(scale=width / page.get_width()).to_pil().convert('RGB')
        finally:
            document.close()
    if image.width != width:
        # pypdfium2 rounds the pixel size up; the picker lays tiles out by exact width.
        from PIL import Image
        image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, 'PNG', optimize=True)
    return buffer.getvalue()


def chosen(options):
    """The template a customer picked on the setup screen, or '' for Auto (the model's choice)."""
    picked = current((options or {}).get('cv_template'))
    return picked if picked in TEMPLATES else ''


def look(style):
    """The template a CV is drawn with: the chosen one, or the default, with a brand colour on top.

    An account's brand colour is a fact about the customer, so it replaces the
    accent; the template's second colour was picked to go with its own accent
    and is dropped, and a dark fill is worked out again from the brand colour.
    """
    from apps.studio.slides import _reads_on
    style = style or {}
    key = current(style.get('cv_template'))
    if key not in TEMPLATES:
        key = DEFAULT_TEMPLATE
    chosen_one = TEMPLATES[key]
    shown = {**{name: value for name, value in chosen_one.items() if name != 'fits'}, 'id': key}
    fixed = bool(style.get('accent_fixed') and style.get('accent'))
    if fixed:
        accent = _hex(style['accent'])
        if len(accent) != 7 or any(char not in '0123456789ABCDEF' for char in accent[1:]):
            fixed = False
    if fixed:
        # A brand colour still has to read as text on white and on the tint.
        accent = _hex(_reads_on(accent.lstrip('#'), 'FFFFFF', 4.5))
        if shown['tint'] and shown['tone'] != 'dark':
            accent = _hex(_reads_on(accent.lstrip('#'), shown['tint'].lstrip('#'), 4.5))
        shown.update(accent=accent, secondary=None,
                     tint=None if shown['tone'] == 'dark' else shown['tint'])
    shown['fill'] = fill_of(shown['accent'], shown['tint'], shown['tone'])
    return shown


def remember(data, raw, *, replace=False):
    """Keep the model's choice in the draft's style, where revisions inherit it."""
    choice = current((raw or {}).get('design'))
    if choice not in TEMPLATES:
        return
    style = data.setdefault('options', {}).setdefault('template_style', {})
    if replace or not style.get('cv_template'):
        style['cv_template'] = choice


def wanted(data, first=0):
    """Whether this provider call should choose a template.

    The pipeline calls this only for CV drafts (a draft's payload does not carry
    its feature id); a payload that does name another feature never chooses.
    The choice is made once: on the first call of a CV that has no template
    yet, or on a change that asks the whole CV for a new look.
    """
    if data.get('feature_id', 'ai.cv') != 'ai.cv' or data.get('output_format', 'pdf') != 'pdf' or first:
        return False
    revision = data.get('revision')
    if revision:
        edit = revision.get('edit') if isinstance(revision.get('edit'), dict) else {}
        return (bool(edit.get('redesign')) and not revision.get('selected_section_ids')
                and data.get('_stage') != 'repair')
    return not ((data.get('options') or {}).get('template_style') or {}).get('cv_template')
