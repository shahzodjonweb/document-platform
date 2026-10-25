"""Slides filled to what each layout's guide allows, in English, Russian and Uzbek.

A variant has to hold these whole (tests/test_slide_variants.py, bench.py):
they are the longest content the model is asked for — a cards slide of six
items of 25 words, a bullets slide of six sentences of 20 words — in the
languages that run longest. Where a layout's guide sets no limit, or the
classic drawer cannot hold the guide's in Russian or Uzbek (a matrix of 22
words a cell), the fixture is what the classic drawer holds: a variant is
never held to less than the classic one, nor to more.
"""
SENTENCES = {
    'en': ('Regional teams cut delivery times by a third after moving stock closer to their largest '
           'customers last spring and hiring local drivers'),
    'ru': ('Региональные команды сократили сроки доставки на треть, перенеся склады ближе к крупнейшим '
           'клиентам прошлой весной и наняв местных водителей'),
    'uz': ('Hududiy jamoalar o‘tgan bahorda omborlarni eng yirik mijozlarga yaqinlashtirib, yetkazib '
           'berish muddatini uchdan bir qismga qisqartirdi va mahalliy haydovchilarni yolladi'),
}
LOCALES = tuple(SENTENCES)

# The entries each layout is drawn with: (fewest, most) that the guide asks for.
RANGES = {
    'agenda': (3, 6), 'bullets': (3, 6), 'two_column': (2, 2), 'statement': (1, 1), 'quote': (1, 1),
    'big_number': (1, 1), 'stats': (2, 4), 'timeline': (3, 6), 'process': (3, 5), 'comparison': (2, 6),
    'pros_cons': (2, 8), 'cards': (3, 6), 'matrix': (4, 4), 'chart': (2, 8), 'table': (2, 6),
    'image_split': (2, 4), 'image_full': (1, 1),
}
STATS = ('-33%', '118%', '4 200', '4.8')
YEARS = ('2019', '2020', 'Q3 2021', '2022', '2023', '2024')
FIGURES = ('420', '310', '185', '96', '240', '58', '133', '75')


def words(locale, count, offset=0):
    parts = ((SENTENCES[locale] + ' ') * 8).split()
    return ' '.join(parts[offset:offset + count])


def line(locale, limit, offset=0):
    """The longest run of words from `offset` that stays within `limit` characters."""
    count = 1
    while count < 40 and len(words(locale, count + 1, offset)) <= limit:
        count += 1
    return words(locale, count, offset)


def item(label='', text='', value=''):
    return {'label': label, 'text': text, 'value': value}


def section(kind, n, locale='en'):
    """A `kind` slide with `n` entries, every field as long as its guide allows."""
    w = lambda count, offset=0: words(locale, count, offset)
    heading, body, items, columns = w(8 if kind == 'bullets' else 6), '', [], []
    if kind == 'agenda':
        items = [item(w(4, k), w(15, k)) for k in range(n)]
    elif kind in ('bullets', 'image_split'):
        body = '\n'.join(w(20 if kind == 'bullets' else 18, 3 * k) for k in range(n))
    elif kind == 'two_column':
        items = [item(w(3), w(50)), item(w(3, 4), w(50, 4))]
    elif kind == 'statement':
        body = line(locale, 118)
    elif kind == 'quote':
        heading, body, items = w(5), w(45), [item(w(2, 3), w(5, 6))]
    elif kind == 'big_number':
        items = [item(w(4), w(35), '64%')]
    elif kind == 'stats':
        items = [item(w(3, k), w(15, k), STATS[k]) for k in range(n)]
    elif kind == 'timeline':
        items = [item(w(3, k), w(12, k), YEARS[k]) for k in range(n)]
    elif kind == 'process':
        items = [item(w(3, k), w(18, k)) for k in range(n)]
    elif kind == 'comparison':
        columns = [w(2), w(2, 5)]
        items = [item(w(3, k), w(8, k), w(8, k + 4)) for k in range(n)]
    elif kind == 'pros_cons':
        pros = -(-n // 2)
        items = [item(w(12, k), '', 'pro' if k < pros else 'con') for k in range(n)]
    elif kind == 'cards':
        items = [item(w(3, k), w(25, k), 'new' if k % 2 == 0 else '') for k in range(n)]
    elif kind == 'matrix':
        items, columns = [item(w(2, k), w(18, k)) for k in range(4)], [w(1), w(1, 4)]
    elif kind == 'chart':
        items, columns = [item(w(2, k), '', FIGURES[k]) for k in range(n)], [w(2, 9)]
    elif kind == 'table':
        columns = [w(2), w(2, 3), w(2, 6)]
        items = [item(w(2, k), w(3, k), w(2, k + 2)) for k in range(n)]
    elif kind == 'image_full':
        heading, body = w(10), w(18)
    else:
        raise ValueError(kind)
    return {'id': 's1', 'heading': heading, 'body': body, 'notes': '', 'layout': kind, 'items': items,
            'columns': columns, 'image_query': 'harbour cranes' if kind.startswith('image') else ''}


def light(kind, n, locale='en'):
    """The same slide written briefly: a heading of three words and fields of a few."""
    full = section(kind, n, locale)
    short = lambda value: ' '.join(str(value).split()[:4])
    return {**full, 'heading': words(locale, 3, 2),
            'body': '\n'.join(short(row) for row in full['body'].split('\n')) if full['body'] else '',
            'items': [{**entry, 'label': short(entry['label']), 'text': short(entry['text'])}
                      for entry in full['items']]}
