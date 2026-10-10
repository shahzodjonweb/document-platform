"""A hundred and ten looks a deck can wear, in categories, and the model picks one.

Every deck used to come out in the same green, because the only colour a deck
had was the template's default accent. A design is a whole look instead: an
accent and a second colour, a light, dark or bold ground, a pair of fonts and,
for most of them, a decorative pattern on the cover and the dividers. The model
chooses one while planning the deck — it has read the brief and knows whether
this is a pitch, a lesson or a quarterly report — and the choice is kept in the
draft's style so revisions keep the look. A customer can also choose one on the
review screen (`options.deck_design`); that choice beats the brief.

What the customer said still wins over the model. A colour or a "dark"/"bold"
named in the description, or an account's brand colour, overrides that part of
the design; the rest of the design stays.

Fonts are faces that ship with Microsoft Office on Windows and macOS and cover
Cyrillic. Text fitting is measured with Noto Sans plus a 10% margin
(`slides.WIDTH_SAFETY`); every face here was measured at or under Noto's width,
so a design cannot push a slide's text off its box. Verdana and Rockwell were
measured wider and are left out on purpose.

Art is a greyscale mask in `assets/deck/` tinted in the deck's own colour and
placed only where no text is drawn (`slides.ART_ZONES`): the side, top or
corner of the cover and closing slides, the end of a divider's band, and, with
`edge`, a thin strip under every other slide's footer. Photo designs put the
cover's picture across the whole slide with the title on a solid panel.
"""

import functools

FONTS = frozenset({'Cambria', 'Corbel', 'Georgia', 'Calibri', 'Arial', 'Trebuchet MS', 'Candara', 'Constantia'})
PATTERNS = ('dots', 'grid', 'lines', 'waves', 'rings', 'arcs', 'triangles', 'hexagons', 'confetti', 'topo',
            'glow', 'plus', 'blobs')
PLACES = ('side', 'top', 'corner')


def _design(accent, second, ground, heading, body, fits, *, bold=False, paper=None, accent_headings=False,
            art=None, cover_photo=False, composition='classic'):
    return {'accent': accent, 'secondary': second, 'theme': ground, 'heading_font': heading,
            'body_font': body, 'heading_bold': bold, 'paper': paper,
            'accent_headings': accent_headings, 'art': art, 'cover_photo': cover_photo,
            'composition': composition, 'fits': fits}


def _art(pattern, place='side', strength=0.3, *, colour='accent', edge=False):
    """A pattern, where it goes on the cover, how strong, in which of the design's colours."""
    return {'pattern': pattern, 'place': place, 'strength': strength, 'colour': colour, 'edge': edge}


# The original ten: five light, three bold (the accent fills the cover and the
# dividers), two dark; within each, a different paper, headline colour and pair
# of fonts. They keep their exact look, without art.
CLASSIC = {
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

BUSINESS = {
    'corporate': _design('#1D4E89', '#F2A900', 'bold', 'Calibri', 'Calibri',
                         'corporate blue; company profiles, annual reports, HR, policies', bold=True,
                         art=_art('lines', 'side', 0.22)),
    'ledger': _design('#14532D', '#A3A3A3', 'light', 'Georgia', 'Calibri',
                      'banking green on ledger paper; finance, accounting, budgets', paper='#F5F7F2',
                      art=_art('grid', 'corner', 0.35)),
    'summit': _design('#0B3954', '#FF5A5F', 'bold', 'Trebuchet MS', 'Calibri',
                      'petrol blue with coral; strategy, goals, leadership, OKRs', bold=True,
                      art=_art('triangles', 'side', 0.18)),
    'capital': _design('#2C3E50', '#E67E22', 'light', 'Constantia', 'Calibri',
                       'slate with orange; investment, economics, market analysis', accent_headings=True,
                       art=_art('arcs', 'corner', 0.45, colour='secondary')),
    'consult': _design('#3D3D99', '#9FA8DA', 'light', 'Calibri', 'Calibri',
                       'calm indigo; consulting, proposals, client meetings', paper='#F6F6FB',
                       art=_art('dots', 'top', 0.3)),
    'venture': _design('#E63946', '#1D3557', 'bold', 'Arial', 'Arial',
                       'red and navy; startup pitch decks, fundraising, growth', bold=True,
                       art=_art('lines', 'side', 0.25)),
    'quarterly': _design('#006D77', '#83C5BE', 'light', 'Calibri', 'Calibri',
                         'teal data look; KPIs, quarterly results, dashboards', bold=True,
                         art=_art('grid', 'top', 0.3)),
    'executive': _design('#C9A66B', '#7A8B99', 'dark', 'Georgia', 'Calibri',
                         'bronze on charcoal; board meetings, executive briefings',
                         art=_art('lines', 'corner', 0.3)),
    'logistics': _design('#F28C28', '#2E4057', 'light', 'Trebuchet MS', 'Trebuchet MS',
                         'orange and steel; operations, logistics, manufacturing', bold=True,
                         art=_art('hexagons', 'side', 0.35)),
    'legal': _design('#5C4033', '#8C7853', 'light', 'Constantia', 'Constantia',
                     'umber on parchment; law, contracts, compliance, governance', paper='#F7F3EA',
                     accent_headings=True, art=_art('lines', 'corner', 0.18)),
}

TECHNOLOGY = {
    'circuit': _design('#00B37E', '#00E5FF', 'dark', 'Trebuchet MS', 'Calibri',
                       'neon green circuitry on dark; electronics, hardware, IoT', bold=True,
                       art=_art('grid', 'side', 0.35, edge=True)),
    'cloud': _design('#2F80ED', '#56CCF2', 'light', 'Calibri', 'Calibri',
                     'sky blue on pale cloud; cloud, SaaS, web services, IT', paper='#F3F7FC',
                     art=_art('glow', 'corner', 0.45, colour='secondary')),
    'neural': _design('#8B5CF6', '#EC4899', 'dark', 'Arial', 'Arial',
                      'violet and pink on dark; AI, machine learning, neural networks', bold=True,
                      art=_art('topo', 'side', 0.4)),
    'terminal': _design('#F59E0B', '#10B981', 'dark', 'Trebuchet MS', 'Trebuchet MS',
                        'amber terminal on dark; programming, developers, coding', art=_art('lines', 'top', 0.25)),
    'quantum': _design('#06B6D4', '#A78BFA', 'dark', 'Calibri', 'Calibri',
                       'cyan rings on dark; physics, quantum, research, science fairs',
                       art=_art('rings', 'side', 0.4)),
    'silicon': _design('#475569', '#0EA5E9', 'light', 'Arial', 'Arial',
                       'cool grey and blue; product specs, engineering, hardware', bold=True, paper='#F1F5F9',
                       art=_art('hexagons', 'corner', 0.4, colour='secondary')),
    'pixel': _design('#6366F1', '#F472B6', 'bold', 'Trebuchet MS', 'Calibri',
                     'indigo with pink; apps, UX, digital products, gaming', bold=True,
                     art=_art('plus', 'side', 0.35)),
    'cyber': _design('#EF4444', '#94A3B8', 'dark', 'Arial', 'Calibri',
                     'alert red on dark; cybersecurity, risk, networks, privacy', bold=True,
                     art=_art('grid', 'corner', 0.35)),
    'datastream': _design('#0D9488', '#F97316', 'light', 'Calibri', 'Calibri',
                          'teal with orange; data science, analytics, statistics',
                          art=_art('waves', 'top', 0.3)),
    'orbit': _design('#1E40AF', '#FBBF24', 'bold', 'Trebuchet MS', 'Calibri',
                     'deep blue with yellow; space, astronomy, rockets, aviation',
                     art=_art('arcs', 'side', 0.35)),
}

EDUCATION = {
    'chalkboard': _design('#F4D35E', '#9AD1D4', 'dark', 'Trebuchet MS', 'Trebuchet MS',
                          'chalk yellow on a green board; school lessons, maths, revision',
                          paper='#1F3B2D', art=_art('plus', 'corner', 0.3, edge=True)),
    'notebook': _design('#2563EB', '#EF4444', 'light', 'Calibri', 'Calibri',
                        'blue ink with a red margin; homework, study notes', paper='#FDFDF8',
                        art=_art('grid', 'corner', 0.3)),
    'campus': _design('#9B2335', '#F2C14E', 'bold', 'Georgia', 'Calibri',
                      'university crimson; lectures, theses, academic defences',
                      art=_art('rings', 'side', 0.25)),
    'library': _design('#2F5D50', '#C08552', 'light', 'Constantia', 'Cambria',
                       'library green on cream; literature, reading, essays', paper='#F8F4EC',
                       accent_headings=True, art=_art('lines', 'corner', 0.2)),
    'lab': _design('#0284C7', '#22C55E', 'light', 'Calibri', 'Calibri',
                   'lab blue and green; chemistry, biology, experiments', bold=True,
                   art=_art('hexagons', 'side', 0.35)),
    'atlas': _design('#B45309', '#0F766E', 'light', 'Georgia', 'Corbel',
                     'map browns and teal; geography, history, cultures', paper='#FBF6EE',
                     art=_art('topo', 'side', 0.35)),
    'alphabet': _design('#F97316', '#3B82F6', 'bold', 'Trebuchet MS', 'Trebuchet MS',
                        'bright orange; primary school, phonics, languages', bold=True,
                        art=_art('confetti', 'side', 0.4)),
    'thesis': _design('#1E3A8A', '#94A3B8', 'light', 'Cambria', 'Cambria',
                      'formal navy; dissertations, research, conferences', accent_headings=True,
                      art=_art('lines', 'corner', 0.15)),
    'mathlab': _design('#7C3AED', '#F59E0B', 'light', 'Calibri', 'Calibri',
                       'purple on grid paper; maths, algebra, geometry, olympiads',
                       art=_art('grid', 'side', 0.3)),
    'linguist': _design('#C2185B', '#14B8A6', 'light', 'Candara', 'Candara',
                        'magenta and teal; language learning, vocabulary, grammar', bold=True,
                        art=_art('dots', 'corner', 0.4, colour='secondary')),
}

CREATIVE = {
    'gallery': _design('#18181B', '#E11D48', 'light', 'Georgia', 'Arial',
                       'black on white with a red note; art history, exhibitions, portfolios',
                       art=_art('arcs', 'corner', 0.3, colour='secondary')),
    'studio': _design('#FF6B6B', '#4ECDC4', 'bold', 'Trebuchet MS', 'Calibri',
                      'coral with mint; design studios, agencies, branding', bold=True,
                      art=_art('blobs', 'side', 0.3)),
    'artbox': _design('#E76F51', '#2A9D8F', 'light', 'Candara', 'Candara',
                      'terracotta and teal; painting, crafts, design classes', paper='#FFF8F0',
                      art=_art('confetti', 'corner', 0.45, colour='secondary')),
    'vinyl': _design('#F43F5E', '#FACC15', 'dark', 'Arial', 'Arial',
                     'rose on black; music, concerts, bands, podcasts', bold=True,
                     art=_art('rings', 'side', 0.35)),
    'cinema': _design('#FBBF24', '#DC2626', 'dark', 'Georgia', 'Calibri',
                      'marquee amber on dark; film, theatre, storytelling', art=_art('lines', 'top', 0.2)),
    'bauhaus': _design('#D62828', '#003049', 'light', 'Arial', 'Arial',
                       'red, blue and cream geometry; design, architecture, posters', bold=True,
                       paper='#F7F3E3', art=_art('triangles', 'side', 0.35)),
    'editorial': _design('#BE123C', '#1F2937', 'light', 'Georgia', 'Georgia',
                         'magazine serif; journalism, essays, media, publishing', accent_headings=True,
                         art=_art('lines', 'corner', 0.2, colour='secondary')),
    'atelier': _design('#1C1917', '#D4A373', 'bold', 'Constantia', 'Calibri',
                       'black cover with camel; fashion, beauty, lifestyle brands',
                       art=_art('arcs', 'side', 0.3)),
    'pastel': _design('#A855F7', '#F9A8D4', 'light', 'Candara', 'Candara',
                      'lilac pastel; illustration, social media, soft creative topics', bold=True,
                      paper='#FAF5FF', art=_art('blobs', 'corner', 0.45, colour='secondary')),
    'neon': _design('#22D3EE', '#F0ABFC', 'dark', 'Trebuchet MS', 'Trebuchet MS',
                    'cyan and pink neon; nightlife, festivals, gaming, youth', bold=True,
                    art=_art('waves', 'side', 0.4, colour='secondary')),
}

NATURE = {
    'meadow': _design('#4D7C0F', '#FACC15', 'light', 'Candara', 'Candara',
                      'fresh green and sunflower; spring, farming, gardening', paper='#F7FBEF',
                      art=_art('dots', 'corner', 0.4)),
    'ocean': _design('#0369A1', '#67E8F9', 'bold', 'Trebuchet MS', 'Calibri',
                     'ocean blue with waves; marine life, water, climate', art=_art('waves', 'side', 0.3)),
    'desert': _design('#C2410C', '#EAB308', 'light', 'Georgia', 'Corbel',
                      'sand and rust; deserts, geology, Central Asia, heritage', paper='#FBF3E6',
                      art=_art('arcs', 'side', 0.35)),
    'tundra': _design('#1D6FA3', '#BAE6FD', 'light', 'Calibri', 'Calibri',
                      'icy blue and white; winter, polar regions, glaciers', paper='#F2F8FB',
                      art=_art('topo', 'corner', 0.35)),
    'canopy': _design('#4ADE80', '#FACC15', 'dark', 'Trebuchet MS', 'Calibri',
                      'leaf green on a dark forest; ecology, rainforests, wildlife', paper='#10231A',
                      art=_art('topo', 'side', 0.3)),
    'bloom': _design('#D6336C', '#F59F00', 'light', 'Candara', 'Candara',
                     'blossom pink; flowers, botany, spring events', paper='#FFF5F7',
                     art=_art('blobs', 'side', 0.35)),
    'harvest': _design('#B45309', '#65A30D', 'bold', 'Georgia', 'Calibri',
                       'harvest amber; agriculture, food, autumn, markets', art=_art('dots', 'side', 0.3)),
    'alpine': _design('#166534', '#64748B', 'light', 'Constantia', 'Corbel',
                      'mountain green and stone; hiking, tourism, outdoors',
                      art=_art('triangles', 'top', 0.25)),
    'wellness': _design('#0F8A7E', '#F9A8D4', 'light', 'Candara', 'Candara',
                        'calm teal; healthcare, wellbeing, yoga, mental health', paper='#F0FAF8',
                        art=_art('glow', 'corner', 0.4, colour='secondary')),
    'earth': _design('#78350F', '#15803D', 'light', 'Cambria', 'Corbel',
                     'soil browns and green; geology, soils, sustainability', paper='#F6F1EA',
                     art=_art('topo', 'side', 0.3)),
}

MINIMAL = {
    'plain': _design('#262626', '#A3A3A3', 'light', 'Calibri', 'Calibri',
                     'black on off-white, nothing extra; any topic, plain and clean', paper='#FAFAFA'),
    'mono': _design('#171717', '#737373', 'bold', 'Arial', 'Arial',
                    'black cover, white pages; bold minimal statements', bold=True),
    'swiss': _design('#E10600', '#111111', 'light', 'Arial', 'Arial',
                     'Swiss red on a grid; design, typography, architecture', bold=True,
                     art=_art('grid', 'corner', 0.18)),
    'nordic': _design('#4B6584', '#D1D8E0', 'light', 'Calibri', 'Calibri',
                      'quiet grey-blue; product docs, reports, calm topics', paper='#F5F6F7'),
    'sand': _design('#8C6E54', '#D6C7B2', 'light', 'Constantia', 'Calibri',
                    'warm sand neutrals; interiors, lifestyle, hospitality', paper='#F7F3EE'),
    'ink': _design('#1E3A5F', '#9CA3AF', 'light', 'Georgia', 'Georgia',
                   'navy ink serif; essays, speeches, literature', accent_headings=True),
    'slate': _design('#94A3B8', '#CBD5E1', 'dark', 'Calibri', 'Calibri',
                     'quiet slate on dark; minimal tech, evening talks'),
    'fineline': _design('#2D6A4F', '#95D5B2', 'light', 'Trebuchet MS', 'Calibri',
                        'thin green lines; process docs, how-tos, manuals', art=_art('lines', 'corner', 0.15)),
    'blush': _design('#A84D6A', '#F4C7D1', 'light', 'Candara', 'Candara',
                     'muted rose on blush; HR, culture, soft presentations', paper='#FCF5F6'),
    'concrete': _design('#57534E', '#F97316', 'light', 'Arial', 'Arial',
                        'concrete grey with orange; construction, urban, engineering', bold=True,
                        paper='#EFEEEC', art=_art('dots', 'corner', 0.25, colour='secondary')),
}

DARK = {
    'obsidian': _design('#A78BFA', '#60A5FA', 'dark', 'Calibri', 'Calibri',
                        'lavender on black; tech talks, keynotes', bold=True, art=_art('glow', 'corner', 0.3)),
    'aurora': _design('#34D399', '#818CF8', 'dark', 'Trebuchet MS', 'Calibri',
                      'aurora green and indigo; science, the night sky, wonder',
                      art=_art('waves', 'side', 0.35, colour='secondary')),
    'ember': _design('#F97316', '#EF4444', 'dark', 'Arial', 'Arial',
                     'ember orange on charcoal; energy, sport, motivation', bold=True,
                     art=_art('glow', 'side', 0.4, colour='secondary')),
    'deepsea': _design('#38BDF8', '#6366F1', 'dark', 'Calibri', 'Calibri',
                       'glowing blue on deep navy; oceans, mysteries, deep dives', paper='#0B1E2D',
                       art=_art('waves', 'top', 0.3)),
    'galaxy': _design('#C084FC', '#F472B6', 'dark', 'Georgia', 'Calibri',
                      'purple starfield; astronomy, space, imagination', art=_art('confetti', 'side', 0.4)),
    'noir': _design('#E5E5E5', '#DC2626', 'dark', 'Georgia', 'Georgia',
                    'black and white with red; crime, film noir, drama',
                    art=_art('lines', 'corner', 0.3, colour='secondary')),
    'matrix': _design('#22C55E', '#86EFAC', 'dark', 'Trebuchet MS', 'Trebuchet MS',
                      'terminal green; hacking, coding, science fiction', bold=True,
                      art=_art('grid', 'side', 0.3, edge=True)),
    'volcano': _design('#EF4444', '#F59E0B', 'dark', 'Arial', 'Calibri',
                       'lava red; geology, volcanoes, disasters, energy', bold=True,
                       art=_art('topo', 'side', 0.35, colour='secondary')),
    'sapphire_night': _design('#3B82F6', '#E5E7EB', 'dark', 'Constantia', 'Calibri',
                              'sapphire on navy-black; formal evenings, finance', paper='#0F172A',
                              art=_art('rings', 'corner', 0.3)),
    'graphene': _design('#2DD4BF', '#3B82F6', 'dark', 'Calibri', 'Calibri',
                        'teal hexagons on dark; materials, chemistry, engineering',
                        art=_art('hexagons', 'side', 0.35)),
}

LUXURY = {
    'champagne': _design('#A47E3B', '#E8D8B0', 'light', 'Georgia', 'Calibri',
                         'champagne gold on ivory; weddings, galas, hospitality', paper='#FBF7EF',
                         accent_headings=True, art=_art('arcs', 'corner', 0.35)),
    'velvet': _design('#6B1E3B', '#D4AF37', 'bold', 'Constantia', 'Calibri',
                      'wine velvet with gold; luxury brands, fine dining', art=_art('dots', 'side', 0.25)),
    'emerald': _design('#10B981', '#D4AF37', 'dark', 'Georgia', 'Calibri',
                       'emerald and gold on dark; jewellery, premium products',
                       art=_art('rings', 'side', 0.3, colour='secondary')),
    'marble': _design('#374151', '#B8860B', 'light', 'Constantia', 'Corbel',
                      'marble grey with gold; real estate, architecture, premium', paper='#F4F4F2',
                      art=_art('topo', 'side', 0.18)),
    'gala_blue': _design('#1E3A8A', '#C0C0C0', 'bold', 'Georgia', 'Calibri',
                         'sapphire and silver; awards, ceremonies, corporate events',
                         art=_art('lines', 'side', 0.2)),
    'rosegold': _design('#B76E79', '#F3D1C8', 'light', 'Candara', 'Candara',
                        'rose gold; beauty, bridal, invitations', paper='#FDF6F4',
                        art=_art('arcs', 'side', 0.35)),
    'festive': _design('#B91C1C', '#15803D', 'bold', 'Georgia', 'Calibri',
                       'festive red and green; holidays, New Year, celebrations',
                       art=_art('confetti', 'side', 0.35)),
    'navruz': _design('#059669', '#F59E0B', 'light', 'Candara', 'Candara',
                      'spring green and gold; Navruz, spring holidays, community', paper='#F6FBF4',
                      art=_art('blobs', 'corner', 0.4, colour='secondary')),
    'crescent': _design('#E0B04A', '#2DD4BF', 'dark', 'Constantia', 'Calibri',
                        'gold on night blue; Ramadan, Eid, cultural evenings', paper='#0D1B2A',
                        art=_art('arcs', 'corner', 0.4)),
    'trophy': _design('#CA8A04', '#1F2937', 'bold', 'Arial', 'Arial',
                      'gold cover; sport, competitions, winners, achievements', bold=True,
                      art=_art('rings', 'side', 0.3)),
}

PLAYFUL = {
    'sunshine': _design('#F59E0B', '#10B981', 'bold', 'Trebuchet MS', 'Trebuchet MS',
                        'sunny yellow; kindergarten, kids, summer camp', bold=True,
                        art=_art('dots', 'side', 0.35)),
    'bubblegum': _design('#EC4899', '#8B5CF6', 'light', 'Candara', 'Candara',
                         'bubblegum pink; birthdays, kids parties, fun facts', bold=True, paper='#FFF5FB',
                         art=_art('blobs', 'side', 0.4)),
    'crayon': _design('#2563EB', '#F97316', 'light', 'Trebuchet MS', 'Trebuchet MS',
                      'crayon blue and orange; primary school, drawing, games', bold=True,
                      accent_headings=True, art=_art('confetti', 'corner', 0.5, colour='secondary', edge=True)),
    'jungle': _design('#15803D', '#FACC15', 'bold', 'Trebuchet MS', 'Calibri',
                      'jungle green; animals, zoo, nature for kids', bold=True, art=_art('blobs', 'side', 0.3)),
    'candy': _design('#F43F5E', '#22D3EE', 'light', 'Candara', 'Candara',
                     'candy red and aqua; sweets, cooking, family events', bold=True,
                     art=_art('dots', 'top', 0.4, colour='secondary')),
    'robot': _design('#0EA5E9', '#F59E0B', 'light', 'Arial', 'Arial',
                     'robot blue; STEM for kids, coding clubs, robotics', bold=True, paper='#F0F9FF',
                     art=_art('plus', 'side', 0.4)),
    'comic': _design('#DC2626', '#FACC15', 'bold', 'Arial', 'Arial',
                     'comic red with halftone dots; stories, heroes, fun lessons', bold=True,
                     art=_art('dots', 'side', 0.4, edge=True)),
    'lemonade': _design('#EAB308', '#84CC16', 'light', 'Trebuchet MS', 'Calibri',
                        'lemon and lime; summer, drinks, school fairs', paper='#FEFCE8',
                        art=_art('waves', 'corner', 0.45)),
    'rocket': _design('#4338CA', '#F472B6', 'bold', 'Trebuchet MS', 'Trebuchet MS',
                      'indigo space adventure; planets for kids, science clubs', bold=True,
                      art=_art('confetti', 'side', 0.35)),
    'toybox': _design('#7C3AED', '#10B981', 'light', 'Candara', 'Candara',
                      'purple and green blocks; games, puzzles, play', bold=True,
                      art=_art('triangles', 'corner', 0.35)),
}

# A photograph across the whole cover, the title on a solid panel. Without a
# picture (none allowed, none found) the cover is the design's ordinary one.
PHOTO = {
    'horizon': _design('#1F4E79', '#F4A261', 'light', 'Georgia', 'Calibri',
                       'navy; travel, places, tourism', cover_photo=True, art=_art('waves', 'side', 0.25)),
    'journal': _design('#3F3F46', '#EAB308', 'light', 'Constantia', 'Corbel',
                       'editorial serif; stories, reportage, history', paper='#FAF8F3', cover_photo=True,
                       art=_art('lines', 'corner', 0.2)),
    'vista': _design('#0E7C7B', '#FFD166', 'bold', 'Trebuchet MS', 'Calibri',
                     'teal; nature, geography, the outdoors', cover_photo=True, art=_art('topo', 'side', 0.3)),
    'urban': _design('#F97316', '#94A3B8', 'dark', 'Arial', 'Arial',
                     'orange on dark; cities, architecture, real estate', bold=True, cover_photo=True,
                     art=_art('grid', 'side', 0.3)),
    'portrait': _design('#9F1239', '#FBCFE8', 'light', 'Georgia', 'Georgia',
                        'wine accents; people, biographies, culture', accent_headings=True, cover_photo=True,
                        art=_art('arcs', 'corner', 0.3)),
    'showcase': _design('#2563EB', '#F59E0B', 'light', 'Calibri', 'Calibri',
                        'bright blue; products, launches, e-commerce', bold=True, cover_photo=True,
                        art=_art('dots', 'corner', 0.35)),
    'cuisine': _design('#C2410C', '#65A30D', 'light', 'Candara', 'Candara',
                       'warm orange; food, recipes, restaurants', paper='#FFF7ED', cover_photo=True,
                       art=_art('blobs', 'corner', 0.35, colour='secondary')),
    'wild': _design('#84CC16', '#FACC15', 'dark', 'Trebuchet MS', 'Calibri',
                    'lime on dark; wildlife, animals, expeditions', cover_photo=True,
                    art=_art('topo', 'side', 0.3)),
    'heritage': _design('#7C2D12', '#D97706', 'bold', 'Constantia', 'Corbel',
                        'heritage brown; history, monuments, museums', cover_photo=True,
                        art=_art('arcs', 'side', 0.3)),
    'stadium': _design('#DC2626', '#111827', 'bold', 'Arial', 'Arial',
                       'red; sport, fitness, teams, events', bold=True, cover_photo=True,
                       art=_art('lines', 'side', 0.3)),
}

# id: (English, Uzbek, Russian) — in the order the picker and the model see them.
CATEGORIES = {
    'classic': (CLASSIC, ('Classic', 'Klassik', 'Классика')),
    'business': (BUSINESS, ('Business', 'Biznes', 'Бизнес')),
    'technology': (TECHNOLOGY, ('Technology', 'Texnologiya', 'Технологии')),
    'education': (EDUCATION, ('Education', 'Ta’lim', 'Образование')),
    'creative': (CREATIVE, ('Creative', 'Ijodiy', 'Творчество')),
    'nature': (NATURE, ('Nature & health', 'Tabiat va salomatlik', 'Природа и здоровье')),
    'minimal': (MINIMAL, ('Minimal', 'Minimal', 'Минимализм')),
    'dark': (DARK, ('Dark', 'Qorong‘i', 'Тёмные')),
    'luxury': (LUXURY, ('Events & luxury', 'Tadbirlar va hashamat', 'События и премиум')),
    'playful': (PLAYFUL, ('Playful & kids', 'Bolalar uchun', 'Детские и яркие')),
    'photo': (PHOTO, ('Photo cover', 'Foto muqova', 'Фото-обложка')),
}
DESIGNS = {key: {**value, 'category': category}
           for category, (designs, _) in CATEGORIES.items() for key, value in designs.items()}
DESIGN_IDS = list(DESIGNS)

# The look a deck has when no design was chosen: what every deck looked like
# before designs, so old drafts and local authoring render exactly as they did.
DEFAULT_ACCENT = '#255e49'
DEFAULT_FONTS = ('Cambria', 'Corbel')


def reference(photos=True):
    """What the model reads when it chooses.

    Grouped by category so a long list stays easy to choose from. Photo designs
    are left out when the deck may have no pictures: their point is a photograph.
    The text depends only on `photos`, which is fixed for a draft, so every
    batch of one deck still sends the same instructions.
    """
    blocks = []
    for category, (designs, names) in CATEGORIES.items():
        if category == 'photo' and not photos:
            continue
        lines = '\n'.join(f'- {key}: {value["fits"]}' for key, value in designs.items())
        blocks.append(f'{names[0]}:\n{lines}')
    photo_note = (' Photo cover designs put a photograph across the whole cover, so give the cover an '
                  'image_query when you choose one.' if photos else '')
    return (
        'When the response has a `design` field, choose the visual design of the whole deck from '
        'this list. First find the category that suits the subject, audience and tone of the '
        'description, then the design in it whose mood fits best; do not default to the first '
        'category or entry, and do not pick green unless the subject suits it. Colours or a dark '
        'theme named in the description are applied separately, so still choose the closest mood.'
        + photo_note + '\n' + '\n'.join(blocks)
    )


@functools.lru_cache(maxsize=4)
def catalogue(locale='en'):
    """The designs as a picker shows them: grouped, named, with the colours they render in.

    Fixed data, so it is worked out once per locale and process; do not change what it returns.
    """
    from .slides import palette
    column = {'en': 0, 'uz': 1, 'ru': 2}.get(locale, 0)
    stamp = version()
    groups = []
    for category, (designs, names) in CATEGORIES.items():
        entries = []
        for key in designs:
            shown = look({'deck_design': key})
            roles = palette(shown['accent'], shown['theme'], shown['secondary'], shown['paper'],
                            shown['accent_headings'])
            entries.append({'id': key, 'name': key.replace('_', ' ').title(), 'theme': shown['theme'],
                            'photo': shown['cover_photo'], 'pattern': (shown['art'] or {}).get('pattern', ''),
                            'composition': shown['composition'],
                            'preview': f'/api/v1/studio/deck-designs/{key}.png?locale={locale}&v={stamp}',
                            'heading_font': shown['heading_font'], 'body_font': shown['body_font'],
                            'colours': {role: '#' + roles[role] for role in (
                                'accent', 'surface', 'cover_fill', 'cover_ink', 'heading', 'ink', 'muted',
                                'accent_soft', 'card')}})
        groups.append({'id': category, 'name': names[column], 'designs': entries})
    return groups


# The cover a picker shows for each design, in the viewer's language.
SAMPLE_COVER = {
    'en': ('Your presentation title', 'A subtitle that says what it is about'),
    'uz': ('Taqdimotingiz nomi', 'Mavzuni qisqacha tushuntiruvchi izoh'),
    'ru': ('Название вашей презентации', 'Подзаголовок о том, о чём она'),
}


def version():
    """Changes whenever a design or the code that draws one changes: thumbnails are cached by it."""
    import hashlib
    from pathlib import Path
    digest = hashlib.sha256(repr(sorted((key, sorted(value.items())) for key, value in DESIGNS.items())).encode())
    for source in sorted((Path(__file__).resolve().parent / 'compositions').glob('*.py')):
        digest.update(source.read_bytes())
    digest.update((Path(__file__).resolve().parent / 'slides.py').read_bytes())
    return digest.hexdigest()[:12]


@functools.lru_cache(maxsize=512)
def thumbnail(key, locale='en', width=480):
    """PNG of `key`'s cover with a sample title, as the theme picker shows it."""
    import io
    import tempfile
    from pathlib import Path
    from .compositions.preview import render
    from .slides import render_pptx
    from pptx import Presentation
    title, subtitle = SAMPLE_COVER.get(locale, SAMPLE_COVER['en'])
    section = lambda sid, heading, body, layout: {'id': sid, 'heading': heading, 'body': body, 'notes': '',
                                                  'layout': layout, 'items': [], 'columns': [], 'image_query': ''}
    content = {'title': title, 'questions': [], 'citations': [], 'sections': [
        section('s1', title, subtitle, 'cover'), section('s2', title, subtitle, 'bullets')]}
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'thumbnail.pptx'
        render_pptx(content, path, locale=locale, style={'deck_design': key})
        image = render(Presentation(str(path)).slides[0], width)
    buffer = io.BytesIO()
    image.save(buffer, 'PNG', optimize=True)
    return buffer.getvalue()


def chosen(options):
    """The design a customer picked on the review screen, or '' for the model's choice."""
    picked = (options or {}).get('deck_design')
    return picked if picked in DESIGNS else ''


def look(style):
    """The design a deck is drawn with: the chosen one, with the customer's choices on top."""
    style = style or {}
    chosen = DESIGNS.get(style.get('deck_design'))
    if chosen is None:
        return {'id': '', 'accent': style.get('accent', DEFAULT_ACCENT),
                'theme': style.get('deck_theme', 'light'), 'secondary': style.get('secondary'), 'paper': None,
                'accent_headings': False, 'heading_font': DEFAULT_FONTS[0], 'body_font': DEFAULT_FONTS[1],
                'heading_bold': False, 'art': None, 'cover_photo': False, 'category': '',
                'composition': 'classic'}
    fixed = bool(style.get('accent_fixed') and style.get('accent'))
    theme = style.get('deck_theme') or chosen['theme']
    return {**{key: value for key, value in chosen.items() if key != 'fits'},
            'id': style['deck_design'],
            # A brand colour or one named in the brief is a fact, not a preference;
            # the design's second colour and paper were picked to go with its own.
            'accent': style['accent'] if fixed else chosen['accent'],
            'secondary': style.get('secondary') or (None if fixed else chosen['secondary']),
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
