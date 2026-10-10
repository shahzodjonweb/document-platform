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
    'summit': _design('#0B3954', '#FF5A5F', 'bold', 'Trebuchet MS', 'Calibri',
                      'petrol blue with coral; strategy, goals, leadership, OKRs', bold=True,
                      art=_art('triangles', 'side', 0.18)),
    'sterling': _design('#23303B', '#2FA36B', 'bold', 'Cambria', 'Calibri',
        'graphite and emerald; finance, accounting, budgets, audits',
        composition='sidebar', bold=True, art=_art('grid', strength=0.3)),
    'broadsheet': _design('#14284B', '#E4572E', 'light', 'Georgia', 'Calibri',
        'navy on salmon paper; investment, economics, markets, real estate',
        composition='editorial', bold=True, paper='#FBF0E6', accent_headings=True),
    'clearview': _design('#0F6A73', '#F4A261', 'bold', 'Candara', 'Calibri',
        'teal and apricot cards; consulting, proposals, HR, onboarding',
        composition='card', bold=True, paper='#FFFCF8', accent_headings=True),
    'liftoff': _design('#E11D48', '#F59E0B', 'dark', 'Arial', 'Arial',
        'ember gradient; pitch decks, fundraising, launches, marketing',
        composition='gradient', bold=True),
    'scorecard': _design('#5B4FE0', '#2EC4A6', 'light', 'Trebuchet MS', 'Calibri',
        'indigo and mint tiles; KPIs, quarterly results, dashboards, sales',
        composition='mosaic', bold=True, accent_headings=True),
    'regent': _design('#3B2540', '#C4A578', 'light', 'Georgia', 'Corbel',
        'aubergine and camel discs; boards, executive briefings, M&A',
        composition='circles', bold=True, paper='#F6F3EE', accent_headings=True),
    'freight': _design('#C2410C', '#164E63', 'bold', 'Corbel', 'Corbel',
        'rust and teal blades; logistics, supply chain, manufacturing',
        composition='diagonal', bold=True, art=_art('lines', strength=0.2)),
    'counsel': _design('#6B1F2A', '#4F6B57', 'light', 'Constantia', 'Cambria',
        'oxblood and sage arches; law, contracts, compliance, governance',
        composition='arch', paper='#F7F4EE', accent_headings=True),
}

TECHNOLOGY = {
    'circuit': _design('#00B37E', '#00E5FF', 'dark', 'Trebuchet MS', 'Calibri',
                       'neon green circuitry on dark; electronics, hardware, IoT', bold=True,
                       art=_art('grid', 'side', 0.35, edge=True)),
    'quantum': _design('#06B6D4', '#A78BFA', 'dark', 'Calibri', 'Calibri',
                       'cyan rings on dark; physics, quantum, research, science fairs',
                       art=_art('rings', 'side', 0.4)),
    'stratus': _design('#1570D8', '#8C7BFF', 'light', 'Corbel', 'Calibri',
        'azure cards on lavender; cloud, SaaS, IT, product demos, fintech',
        composition='card', bold=True, paper='#F7FAFE', art=_art('dots', strength=0.25)),
    'synapse': _design('#5B21B6', '#EC4899', 'light', 'Corbel', 'Calibri',
        'violet-plum gradients; AI, ML, LLMs, chatbots, neural networks',
        composition='gradient', bold=True, art=_art('rings', strength=0.3)),
    'syntax': _design('#3DDC97', '#FFC21A', 'dark', 'Arial', 'Calibri',
        'mint and yellow stickers; coding, developers, open source, DevOps',
        composition='brutalist', bold=True, paper='#0F1A15'),
    'alloy': _design('#FF5F1F', '#2E3440', 'bold', 'Arial', 'Calibri',
        'safety orange, black type; hardware, robotics, EVs, manufacturing',
        composition='editorial', bold=True, paper='#F4F5F7'),
    'firewall': _design('#D7263D', '#7DD3FC', 'dark', 'Calibri', 'Calibri',
        'crimson and ice on navy; cybersecurity, privacy, networks, risk',
        composition='diagonal', bold=True, paper='#0D1220', art=_art('hexagons', strength=0.25)),
    'heatmap': _design('#0B7F78', '#FF7A59', 'light', 'Candara', 'Calibri',
        'teal and coral tiles; data science, analytics, BI, dashboards',
        composition='mosaic', bold=True, paper='#F5FAF9', accent_headings=True),
    'apogee': _design('#7B8CFF', '#FF9F45', 'dark', 'Trebuchet MS', 'Calibri',
        'glowing planets; space, astronomy, rockets, satellites, aviation',
        composition='glow', bold=True, paper='#0A0D1F', art=_art('confetti', strength=0.25)),
    'wireframe': _design('#2B59FF', '#FF8CC6', 'bold', 'Candara', 'Calibri',
        'cobalt and pink discs; apps, UX/UI, gaming, AR/VR, e-commerce',
        composition='circles', bold=True),
}

EDUCATION = {
    'chalkboard': _design('#F4D35E', '#9AD1D4', 'dark', 'Trebuchet MS', 'Trebuchet MS',
                          'chalk yellow on a green board; school lessons, maths, revision',
                          paper='#1F3B2D', art=_art('plus', 'corner', 0.3, edge=True)),
    'atlas': _design('#B45309', '#0F766E', 'light', 'Georgia', 'Corbel',
                     'map browns and teal; geography, history, cultures', paper='#FBF6EE',
                     art=_art('topo', 'side', 0.35)),
    'anthology': _design('#3F2147', '#C8452F', 'light', 'Constantia', 'Cambria',
        'aubergine cloth, vermilion rule; literature, poetry, classics',
        composition='split', paper='#F5EFE3'),
    'lectern': _design('#A3192F', '#1F3352', 'bold', 'Georgia', 'Calibri',
        'cardinal editorial; university lectures, seminars, history, law',
        composition='editorial', bold=True),
    'symposium': _design('#0E5E6F', '#E8919B', 'bold', 'Cambria', 'Corbel',
        'petrol and rose report; theses, research, teacher training',
        composition='sidebar'),
    'petri': _design('#0A8463', '#FF6B57', 'light', 'Trebuchet MS', 'Calibri',
        'emerald and coral discs; chemistry, biology, medicine, lab work',
        composition='circles', bold=True, paper='#F4F8F5'),
    'tangram': _design('#3346D3', '#FFB21E', 'bold', 'Arial', 'Calibri',
        'cobalt and saffron tiles; maths, geometry, logic, coding',
        composition='mosaic', bold=True),
    'hopscotch': _design('#0FA396', '#7A5CF0', 'light', 'Trebuchet MS', 'Trebuchet MS',
        'turquoise and violet rainbow; primary school, phonics, reading',
        composition='stripes', bold=True, paper='#FFF8F0'),
    'flashcard': _design('#D12F6A', '#FFA94D', 'light', 'Candara', 'Candara',
        'berry stickers on tangerine; languages, vocab, exam prep, quizzes',
        composition='brutalist', bold=True),
    'observatory': _design('#3A2FA8', '#0B8FAF', 'dark', 'Corbel', 'Corbel',
        'midnight-blue gradient, orbit; astronomy, physics, space, STEM',
        composition='gradient', paper='#0C1030'),
}

CREATIVE = {
    'vinyl': _design('#F43F5E', '#FACC15', 'dark', 'Arial', 'Arial',
                     'rose on black; music, concerts, bands, podcasts', bold=True,
                     art=_art('rings', 'side', 0.35)),
    'bauhaus': _design('#D62828', '#003049', 'light', 'Arial', 'Arial',
                       'red, blue and cream geometry; design, architecture, posters', bold=True,
                       paper='#F7F3E3', art=_art('triangles', 'side', 0.35)),
    'vernissage': _design('#1F4D3A', '#DB9B70', 'bold', 'Constantia', 'Calibri',
        'copper frames, museum green; art history, exhibitions, portfolios',
        composition='frame', paper='#F7F4EC'),
    'riso': _design('#0078BF', '#FF6FAE', 'light', 'Arial', 'Arial',
        'riso blue and pink, loud; branding, agencies, posters, design',
        composition='brutalist', bold=True, paper='#F3F0E8'),
    'gouache': _design('#D9387A', '#FFC145', 'light', 'Candara', 'Candara',
        'painted tiles in fuchsia and sun; art classes, crafts, painting',
        composition='mosaic', bold=True, paper='#FFFAF3'),
    'matinee': _design('#EE7F38', '#23A69E', 'dark', 'Georgia', 'Calibri',
        'orange and teal spotlights on black; film, theatre, storytelling',
        composition='circles', bold=True, paper='#0E1618'),
    'masthead': _design('#4B1D52', '#D9A441', 'light', 'Constantia', 'Constantia',
        'plum serif on cream; journalism, essays, media, books, publishing',
        composition='editorial', paper='#FBF9F4', accent_headings=True),
    'maison': _design('#7393BA', '#5A3B2E', 'light', 'Georgia', 'Corbel',
        'dusty blue and cocoa arches; fashion, beauty, interiors, brands',
        composition='arch', paper='#F6F1EA'),
    'groove': _design('#5B3F8C', '#F2B33D', 'bold', 'Trebuchet MS', 'Trebuchet MS',
        '70s grape and marigold bands; illustration, zines, social media',
        composition='stripes', bold=True, paper='#FFF6E6'),
    'strobe': _design('#8B5CF6', '#B8F135', 'dark', 'Trebuchet MS', 'Calibri',
        'violet and lime glow; music, festivals, nightlife, gaming, youth',
        composition='glow', bold=True, paper='#0C0A1A'),
}

NATURE = {
    'ocean': _design('#0369A1', '#67E8F9', 'bold', 'Trebuchet MS', 'Calibri',
                     'ocean blue with waves; marine life, water, climate', art=_art('waves', 'side', 0.3)),
    'canopy': _design('#4ADE80', '#FACC15', 'dark', 'Trebuchet MS', 'Calibri',
                      'leaf green on a dark forest; ecology, rainforests, wildlife', paper='#10231A',
                      art=_art('topo', 'side', 0.3)),
    'stillness': _design('#4E7D6A', '#E0A184', 'light', 'Candara', 'Corbel',
        'sage arches on linen; mindfulness, yoga retreats, spa, skincare',
        composition='arch', paper='#F4F1EA', accent_headings=True),
    'remedy': _design('#6A58A6', '#7DB59B', 'light', 'Candara', 'Calibri',
        'lavender and eucalyptus; herbal medicine, pharmacy, nutrition',
        composition='card', bold=True, paper='#FAF8FC'),
    'kyzylkum': _design('#B5562F', '#2E9C9A', 'light', 'Constantia', 'Calibri',
        'terracotta, turquoise; Central Asia, Silk Road, deserts, geology',
        composition='circles', bold=True, paper='#F5E8DC'),
    'polar_dawn': _design('#6FA8E0', '#F3B49A', 'dark', 'Corbel', 'Calibri',
        'glacier blue, polar dawn; Arctic, Antarctica, glaciers, winter',
        composition='glow', paper='#0B1426'),
    'switchback': _design('#1F5560', '#D0703C', 'bold', 'Trebuchet MS', 'Calibri',
        'retro spruce and rust; hiking, national parks, wildlife, camping',
        composition='stripes', bold=True, paper='#F7F0E2'),
    'granary': _design('#66761D', '#E8A33D', 'bold', 'Cambria', 'Calibri',
        'olive and gold patchwork; farming, food, rural life, cooking',
        composition='mosaic', bold=True, paper='#F7F0DE'),
    'herbarium': _design('#8C2D4B', '#4F7F52', 'light', 'Constantia', 'Candara',
        'rose ink, leaf green; botany, natural history, flowers, gardens',
        composition='frame', paper='#F6F0E4', accent_headings=True),
    'loam': _design('#234B3C', '#8FBF4D', 'light', 'Corbel', 'Calibri',
        'pine and sprout blades; ESG, sustainability, climate, renewables',
        composition='diagonal', bold=True, paper='#F4F2EA', art=_art('hexagons', strength=0.25)),
}

MINIMAL = {
    'baseline': _design('#2340C8', '#E8B04B', 'light', 'Arial', 'Calibri',
        'black type, one cobalt accent; any topic, reports, plain talks',
        composition='editorial', bold=True, paper='#FAF9F6'),
    'monolith': _design('#141414', '#D8D2C7', 'bold', 'Arial', 'Arial',
        'black block, stark type; manifestos, vision, portfolios, CVs',
        composition='split', bold=True),
    'grotesk': _design('#E3120B', '#111111', 'light', 'Arial', 'Arial',
        'Swiss red and black discs; design, typography, architecture',
        composition='circles', bold=True),
    'northlight': _design('#35577D', '#CBBBA5', 'light', 'Corbel', 'Calibri',
        'steel blue cards on birch; product docs, reports, research',
        composition='card', bold=True),
    'flax': _design('#9C7451', '#3E3934', 'light', 'Corbel', 'Calibri',
        'oak and charcoal arches, Japandi; interiors, lifestyle, hotels',
        composition='arch', paper='#F7F2EA'),
    'inkwell': _design('#1E2A47', '#C0453A', 'light', 'Georgia', 'Georgia',
        'navy ink, red-pencil frame; speeches, essays, letters, op-eds',
        composition='frame', paper='#F6F2EA'),
    'blue_hour': _design('#1E8C7E', '#34506E', 'dark', 'Corbel', 'Calibri',
        'teal dusk gradient; minimal tech, evening talks, keynotes',
        composition='gradient', bold=True, paper='#0F1B20'),
    'fieldbook': _design('#2E3A87', '#F0855A', 'bold', 'Trebuchet MS', 'Calibri',
        'indigo panels, coral marks; how-tos, manuals, SOPs, checklists',
        composition='sidebar', bold=True),
    'heather': _design('#6D5BA3', '#F2A98E', 'light', 'Candara', 'Candara',
        'lilac and peach blades; HR, culture, onboarding, wellbeing',
        composition='diagonal', paper='#FAF7FC'),
    'formwork': _design('#4B5056', '#F5C400', 'bold', 'Arial', 'Arial',
        'concrete grey, hi-vis yellow; construction, civil works, safety',
        composition='mosaic', bold=True),
}

DARK = {
    'late_edition': _design('#E63946', '#F2E8D5', 'dark', 'Georgia', 'Corbel',
        'crimson on ink-black; true crime, horror, film, history, news',
        composition='editorial', bold=True, paper='#0E0E10'),
    'afterburn': _design('#FF6A1A', '#2F6BFF', 'dark', 'Arial', 'Calibri',
        'orange and cobalt blades; sport, racing, esports, fitness, fire',
        composition='diagonal', bold=True, art=_art('lines', strength=0.3)),
    'zero_day': _design('#C5F82A', '#FF2D8A', 'dark', 'Arial', 'Trebuchet MS',
        'acid lime and magenta slabs; hacking, cybersecurity, gaming',
        composition='brutalist', bold=True, paper='#0B0C0A'),
    'polar_night': _design('#39E68C', '#8B5CFF', 'dark', 'Candara', 'Corbel',
        'aurora green and violet glow; astronomy, space, northern lights',
        composition='glow', paper='#07140F'),
    'reagent': _design('#FF7A66', '#14C4CC', 'dark', 'Trebuchet MS', 'Calibri',
        'coral and teal tile wall; chemistry, physics, biotech, labs',
        composition='mosaic', bold=True, paper='#081517'),
    'abyssal': _design('#1FA2FF', '#BDE6FF', 'dark', 'Cambria', 'Candara',
        'azure arches in the deep; oceans, diving, mysteries, geology',
        composition='arch', paper='#04111F'),
    'sapphire_gilt': _design('#D8BB85', '#5B7CF2', 'dark', 'Constantia', 'Corbel',
        'gilt frame, sapphire jewels; finance, law, galas, awards',
        composition='frame', paper='#0B1022'),
    'after_hours': _design('#FF3E8E', '#7A5CFF', 'dark', 'Candara', 'Calibri',
        'magenta-to-violet neon; music, nightlife, festivals, fashion',
        composition='gradient', bold=True, paper='#150B16'),
    'mainstage': _design('#9B8CFF', '#FFB199', 'dark', 'Corbel', 'Calibri',
        'lavender cards on indigo night; tech talks, AI, startups, SaaS',
        composition='card', bold=True, paper='#17152B'),
    'ivory_eclipse': _design('#EDE6D6', '#9DB17C', 'dark', 'Corbel', 'Calibri',
        'ivory and sage discs on graphite; design, architecture, art',
        composition='circles', bold=True, paper='#151412'),
}

LUXURY = {
    'champagne': _design('#A47E3B', '#E8D8B0', 'light', 'Georgia', 'Calibri',
                         'champagne gold on ivory; weddings, galas, hospitality', paper='#FBF7EF',
                         accent_headings=True, art=_art('arcs', 'corner', 0.35)),
    'bordeaux': _design('#5C1A33', '#C9A15A', 'bold', 'Georgia', 'Corbel',
        'wine and gold frame; fine dining, wine, charity galas, fashion',
        composition='frame', paper='#F8F3EF', accent_headings=True),
    'malachite': _design('#DDB2A3', '#14805F', 'dark', 'Cambria', 'Corbel',
        'rose gold and emerald on black; jewellery, watches, perfume',
        composition='split', paper='#0B0F0E'),
    'penthouse': _design('#C8764A', '#8FA3B8', 'dark', 'Georgia', 'Corbel',
        'copper on charcoal; hotels, resorts, residences, private clubs',
        composition='editorial', paper='#141518'),
    'accolade': _design('#1E3A8A', '#C9A13B', 'light', 'Georgia', 'Calibri',
        'sapphire and gold medals; awards, graduations, conferences, galas',
        composition='circles', paper='#FAF7F0'),
    'tulle': _design('#8E5A73', '#C9A46A', 'light', 'Georgia', 'Candara',
        'mauve, champagne arches; weddings, bridal, invitations, 8 March',
        composition='arch', paper='#FAF5F2', accent_headings=True),
    'sparkler': _design('#D63A4A', '#F2C14E', 'dark', 'Georgia', 'Calibri',
        'ruby, gold lights; New Year, Christmas, birthdays, parties, shows',
        composition='glow', bold=True),
    'samarkand': _design('#1F4E9A', '#2FA7A3', 'light', 'Cambria', 'Candara',
        'lapis, turquoise tiles; Navruz, Independence Day, Uzbek culture',
        composition='mosaic', paper='#FBF8F1', accent_headings=True),
    'lantern': _design('#E1B04F', '#4FB3A5', 'dark', 'Georgia', 'Calibri',
        'gold arches and jade on night blue; Ramadan, Eid, iftar evenings',
        composition='arch', paper='#0B1730'),
    'grandprix': _design('#17191E', '#D4AF37', 'bold', 'Arial', 'Arial',
        'black and gold blades; motorsport, supercars, launches, finals',
        composition='diagonal', bold=True),
}

PLAYFUL = {
    'comic': _design('#DC2626', '#FACC15', 'bold', 'Arial', 'Arial',
                     'comic red with halftone dots; stories, heroes, fun lessons', bold=True,
                     art=_art('dots', 'side', 0.4, edge=True)),
    'sunbeam': _design('#FF8A1F', '#2EA3F2', 'light', 'Trebuchet MS', 'Calibri',
        'tangerine and sky bands; summer camp, holidays, picnics, scouts',
        composition='stripes', bold=True, paper='#EEF7FD', art=_art('dots', strength=0.3)),
    'pinata': _design('#E0368C', '#1FC2B8', 'light', 'Candara', 'Candara',
        'magenta and turquoise discs; birthdays, parties, carnivals, music',
        composition='circles', bold=True, paper='#FFF7EE', art=_art('confetti', strength=0.35)),
    'doodle': _design('#2F5BEA', '#FFC93C', 'light', 'Trebuchet MS', 'Calibri',
        'cobalt sticker cards; kindergarten, primary school, crafts, art',
        composition='brutalist', bold=True, accent_headings=True),
    'treetop': _design('#1E8048', '#F4A23C', 'light', 'Corbel', 'Calibri',
        'leafy green and marigold arches; animals, zoo, farm, pets, nature',
        composition='arch', bold=True, paper='#FBF6EC', art=_art('blobs', strength=0.3)),
    'sprinkles': _design('#E8735F', '#2CC4A4', 'light', 'Candara', 'Candara',
        'coral and mint cards; baking, tea parties, Christmas, family days',
        composition='card', bold=True, paper='#FFF4F1', art=_art('dots', strength=0.3)),
    'gizmo': _design('#9BE15D', '#3DA5FF', 'dark', 'Arial', 'Calibri',
        'lime and blue tiles on navy; kids STEM, coding, robotics, makers',
        composition='mosaic', bold=True, paper='#101A33', art=_art('plus', strength=0.3)),
    'lemon_fizz': _design('#FFD23F', '#14B8C4', 'bold', 'Trebuchet MS', 'Trebuchet MS',
        'lemon and pool-blue blades; school fairs, sports day, pool party',
        composition='diagonal', bold=True, art=_art('waves', strength=0.35)),
    'stardust': _design('#22C3EE', '#F472B6', 'dark', 'Georgia', 'Calibri',
        'cyan and pink glow at night; bedtime stories, fairy tales, magic',
        composition='glow', bold=True, paper='#0A1A22', art=_art('confetti', strength=0.3)),
    'jigsaw': _design('#6A3DF0', '#18B4F0', 'bold', 'Corbel', 'Corbel',
        'violet to sky gradients; games, quizzes, trivia, icebreakers',
        composition='gradient', bold=True, art=_art('triangles', strength=0.3)),
}

# A photograph across the whole cover, the title on a solid panel. Without a
# picture (none allowed, none found) the cover is the design's ordinary one.
PHOTO = {
    'postcard': _design('#1E5F9E', '#F39A3D', 'light', 'Trebuchet MS', 'Calibri',
        'Aegean blue and sunset discs; travel, tourism, guides, holidays',
        composition='circles', bold=True, paper='#FBF4E6', cover_photo=True),
    'front_page': _design('#1C1C1C', '#D7261E', 'light', 'Arial', 'Cambria',
        'ink and press red halftone; reportage, journalism, documentaries',
        composition='sidebar', bold=True, paper='#F3F0E8', cover_photo=True),
    'trailhead': _design('#355E3B', '#5AA2D6', 'bold', 'Candara', 'Calibri',
        'moss and lake blue; landscapes, national parks, geography, trips',
        composition='split', bold=True, cover_photo=True),
    'city_block': _design('#A63A2B', '#7FA6C2', 'light', 'Arial', 'Arial',
        'brick and glass tiles; cities, architecture, urbanism, property',
        composition='mosaic', bold=True, paper='#F4F2EE', cover_photo=True),
    'likeness': _design('#33465C', '#B8794F', 'light', 'Constantia', 'Corbel',
        'slate ink frame; biographies, portraits, memoirs, interviews',
        composition='frame', paper='#F6F1EA', cover_photo=True),
    'unboxed': _design('#E84A1C', '#3A3F47', 'light', 'Calibri', 'Calibri',
        'orange cards on cool grey; products, launches, e-commerce, retail',
        composition='card', bold=True, cover_photo=True),
    'trattoria': _design('#9AAA34', '#E2572F', 'dark', 'Georgia', 'Candara',
        'olive and tomato bands; food, recipes, restaurants, cafés, menus',
        composition='stripes', bold=True, paper='#1E1712', cover_photo=True),
    'night_safari': _design('#E8892B', '#7A2E3A', 'dark', 'Trebuchet MS', 'Calibri',
        'savanna sunset gradient; wildlife, animals, safaris, expeditions',
        composition='gradient', bold=True, paper='#17120F', cover_photo=True),
    'colonnade': _design('#9A4A2C', '#4D7FA0', 'bold', 'Constantia', 'Cambria',
        'terracotta and fresco arches; history, monuments, museums, ruins',
        composition='arch', paper='#F5EFE4', cover_photo=True),
    'photo_finish': _design('#2F5BFF', '#D7F42A', 'dark', 'Arial', 'Arial',
        'electric blue and volt blades; sport, fitness, teams, matches',
        composition='diagonal', bold=True, cover_photo=True),
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
# Designs taken out of the catalogue, and the design that replaces each: drafts
# and revisions that remember a retired id keep a look of the same mood.
RETIRED = {
    'alphabet': 'hopscotch',
    'alpine': 'switchback',
    'artbox': 'gouache',
    'atelier': 'maison',
    'aurora': 'polar_night',
    'bloom': 'herbarium',
    'blush': 'heather',
    'bubblegum': 'pinata',
    'campus': 'lectern',
    'candy': 'sprinkles',
    'capital': 'broadsheet',
    'cinema': 'matinee',
    'cloud': 'stratus',
    'concrete': 'formwork',
    'consult': 'clearview',
    'crayon': 'doodle',
    'crescent': 'lantern',
    'cuisine': 'trattoria',
    'cyber': 'firewall',
    'datastream': 'heatmap',
    'deepsea': 'abyssal',
    'desert': 'kyzylkum',
    'earth': 'loam',
    'editorial': 'masthead',
    'ember': 'afterburn',
    'emerald': 'malachite',
    'executive': 'regent',
    'festive': 'sparkler',
    'fineline': 'fieldbook',
    'gala_blue': 'accolade',
    'galaxy': 'polar_night',
    'gallery': 'vernissage',
    'graphene': 'reagent',
    'harvest': 'granary',
    'heritage': 'colonnade',
    'horizon': 'postcard',
    'ink': 'inkwell',
    'journal': 'front_page',
    'jungle': 'treetop',
    'lab': 'petri',
    'ledger': 'sterling',
    'legal': 'counsel',
    'lemonade': 'lemon_fizz',
    'library': 'anthology',
    'linguist': 'flashcard',
    'logistics': 'freight',
    'marble': 'penthouse',
    'mathlab': 'tangram',
    'matrix': 'zero_day',
    'meadow': 'granary',
    'mono': 'monolith',
    'navruz': 'samarkand',
    'neon': 'strobe',
    'neural': 'synapse',
    'noir': 'late_edition',
    'nordic': 'northlight',
    'notebook': 'flashcard',
    'obsidian': 'mainstage',
    'orbit': 'apogee',
    'pastel': 'maison',
    'pixel': 'wireframe',
    'plain': 'baseline',
    'portrait': 'likeness',
    'quarterly': 'scorecard',
    'robot': 'gizmo',
    'rocket': 'stardust',
    'rosegold': 'tulle',
    'sand': 'flax',
    'sapphire_night': 'sapphire_gilt',
    'showcase': 'unboxed',
    'silicon': 'alloy',
    'slate': 'blue_hour',
    'stadium': 'photo_finish',
    'studio': 'riso',
    'sunshine': 'sunbeam',
    'swiss': 'grotesk',
    'terminal': 'syntax',
    'thesis': 'symposium',
    'toybox': 'jigsaw',
    'trophy': 'grandprix',
    'tundra': 'polar_dawn',
    'urban': 'city_block',
    'velvet': 'bordeaux',
    'venture': 'liftoff',
    'vista': 'trailhead',
    'volcano': 'afterburn',
    'wellness': 'stillness',
    'wild': 'night_safari',
}


def current(key):
    """The design to use for `key`: itself, or the one that replaced it."""
    return RETIRED.get(key, key)

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
    photo_note = (' Photo cover designs show a photograph on the cover: give the cover an image_query.'
                  if photos else '')
    return (
        'When the response has a `design` field, choose the deck\'s design from this list: the '
        'category that suits the subject, audience and tone, then the design whose mood fits best. '
        'Do not default to the first entry. Colours or a dark theme named in the description are '
        'applied separately, so still choose the closest mood.'
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
    picked = current((options or {}).get('deck_design'))
    return picked if picked in DESIGNS else ''


def look(style):
    """The design a deck is drawn with: the chosen one, with the customer's choices on top."""
    style = style or {}
    design_id = current(style.get('deck_design'))
    chosen = DESIGNS.get(design_id)
    if chosen is None:
        return {'id': '', 'accent': style.get('accent', DEFAULT_ACCENT),
                'theme': style.get('deck_theme', 'light'), 'secondary': style.get('secondary'), 'paper': None,
                'accent_headings': False, 'heading_font': DEFAULT_FONTS[0], 'body_font': DEFAULT_FONTS[1],
                'heading_bold': False, 'art': None, 'cover_photo': False, 'category': '',
                'composition': 'classic'}
    fixed = bool(style.get('accent_fixed') and style.get('accent'))
    theme = style.get('deck_theme') or chosen['theme']
    return {**{key: value for key, value in chosen.items() if key != 'fits'},
            'id': design_id,
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
