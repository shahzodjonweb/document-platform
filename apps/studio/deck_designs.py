"""Ten looks a deck can wear, and the model picks the one that fits.

Every deck used to come out in the same green, because the only colour a deck
had was the template's default accent. A design is a whole look instead: an
accent and a second colour, a light, dark or bold ground, and a pair of fonts.
The model chooses one while planning the deck — it has read the brief and knows
whether this is a pitch, a lesson or a quarterly report — and the choice is kept
in the draft's style so revisions keep the look.

What the customer said still wins. A colour or a "dark"/"bold" named in the
description, or an account's brand colour, overrides that part of the design;
the rest of the design stays.

Fonts are faces that ship with Microsoft Office on Windows and macOS and cover
Cyrillic. Text fitting is measured with Noto Sans plus a 10% margin
(`slides.WIDTH_SAFETY`); every face here was measured at or under Noto's width,
so a design cannot push a slide's text off its box. Verdana and Rockwell were
measured wider and are left out on purpose.
"""

def _design(accent, second, ground, heading, body, fits, *, bold=False, paper=None, accent_headings=False):
    return {'accent': accent, 'secondary': second, 'theme': ground, 'heading_font': heading,
            'body_font': body, 'heading_bold': bold, 'paper': paper,
            'accent_headings': accent_headings, 'fits': fits}


# Five light, three bold (the accent fills the cover and the dividers), two dark;
# within each, a different paper, headline colour and pair of fonts, so no two
# decks read as the same template in a different colour.
DESIGNS = {
    'forest': _design('#1E6B45', '#C9A227', 'light', 'Cambria', 'Corbel',
                      'deep green on warm natural paper; nature, health, wellbeing, sustainability, '
                      'agriculture, biology', paper='#F4F1E8'),
    'boardroom': _design('#1F3A68', '#C9A227', 'bold', 'Georgia', 'Calibri',
                         'navy cover with gold; business, finance, strategy, investors, quarterly '
                         'reports, law'),
    'midnight': _design('#4F8CFF', '#22D3EE', 'dark', 'Trebuchet MS', 'Calibri',
                        'blue and cyan on a dark ground; technology, software, AI, data, engineering, '
                        'startups', bold=True),
    'scholar': _design('#7A1F35', '#B08D57', 'light', 'Constantia', 'Cambria',
                       'burgundy headlines on cream paper; history, literature, philosophy, academic '
                       'lectures, culture, religion', paper='#FAF5EA', accent_headings=True),
    'spotlight': _design('#D94A26', '#FFC857', 'bold', 'Arial', 'Arial',
                         'coral cover and dividers; marketing, product launches, pitches, sales, events',
                         bold=True),
    'lagoon': _design('#0F766E', '#5EC4B6', 'light', 'Candara', 'Candara',
                      'teal on pale aqua; travel, geography, oceans, environment, tourism, chemistry',
                      bold=True, paper='#EEF6F5', accent_headings=True),
    'royal': _design('#5B2A86', '#E0A458', 'bold', 'Georgia', 'Corbel',
                     'purple cover and dividers with amber; art, music, design, fashion, creative work'),
    'classroom': _design('#D9661F', '#2F80ED', 'light', 'Trebuchet MS', 'Trebuchet MS',
                         'bright orange and blue on white; school lessons, children, training, friendly '
                         'workshops', bold=True, accent_headings=True),
    'graphite': _design('#2B2F33', '#E85D3F', 'light', 'Arial', 'Arial',
                        'charcoal on light stone with a red highlight; minimal, architecture, research '
                        'summaries, manuals, product specs', bold=True, paper='#F1F0EC'),
    'gala': _design('#D4A017', '#8B5CF6', 'dark', 'Georgia', 'Calibri',
                    'gold on a dark ground; awards, ceremonies, luxury, celebrations, inspiration, sport'),
}
DESIGN_IDS = list(DESIGNS)

# The look a deck has when no design was chosen: what every deck looked like
# before designs, so old drafts and local authoring render exactly as they did.
DEFAULT_ACCENT = '#255e49'
DEFAULT_FONTS = ('Cambria', 'Corbel')


def reference():
    """What the model reads when it chooses."""
    lines = '\n'.join(f'- {key}: {value["fits"]}' for key, value in DESIGNS.items())
    return (
        'When the response has a `design` field, choose the visual design of the whole deck from '
        'this list. Pick the one '
        'whose mood fits the subject, audience and tone of the description; do not default to the '
        'first entry, and do not pick green unless the subject suits it. Colours or a dark theme '
        'named in the description are applied separately, so still choose the closest mood.\n'
        + lines
    )


def look(style):
    """The design a deck is drawn with: the chosen one, with the customer's choices on top."""
    style = style or {}
    chosen = DESIGNS.get(style.get('deck_design'))
    if chosen is None:
        return {'id': '', 'accent': style.get('accent', DEFAULT_ACCENT),
                'theme': style.get('deck_theme', 'light'), 'secondary': None, 'paper': None,
                'accent_headings': False, 'heading_font': DEFAULT_FONTS[0], 'body_font': DEFAULT_FONTS[1],
                'heading_bold': False}
    fixed = bool(style.get('accent_fixed') and style.get('accent'))
    theme = style.get('deck_theme') or chosen['theme']
    return {**{key: value for key, value in chosen.items() if key != 'fits'},
            'id': style['deck_design'],
            # A brand colour or one named in the brief is a fact, not a preference;
            # the design's second colour and paper were picked to go with its own.
            'accent': style['accent'] if fixed else chosen['accent'],
            'secondary': None if fixed else chosen['secondary'],
            'paper': None if fixed or theme != chosen['theme'] else chosen['paper'],
            'theme': theme}


def remember(data, raw, *, replace=False):
    """Keep the model's choice in the draft's style, where revisions inherit it."""
    choice = (raw or {}).get('design')
    if choice not in DESIGNS:
        return
    style = data.setdefault('options', {}).setdefault('template_style', {})
    if replace or not style.get('deck_design'):
        style['deck_design'] = choice


def wanted(data, first=0):
    """Whether this provider call should choose a design."""
    if data.get('output_format') != 'pptx' or data.get('revision') or first:
        return False
    return not (data.get('options') or {}).get('template_style', {}).get('deck_design')
