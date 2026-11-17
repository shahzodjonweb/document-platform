"""Computed table cells and totals of a category paper, from the customer's own numbers (architecture 4, R5a).

A business paper's tables hold figures a reader checks with a calculator: an
offer's line amounts and its total, a report's difference from the plan and
its per cent, a plan's shares of the money and its totals. The model is told
never to do arithmetic and to leave those cells empty (finish._shape empties
any it wrote anyway), so every such figure on the page is code's, made here
from the numbers of the same row or column, and a reader never meets a total
the model guessed.

A table part says what is computed (catalogue `computed` and `total`):

- `product` (quantity × price), `sum` (cells of the row), `difference` (the
  first minus the second: actual minus plan) and `percent` (the first over
  the second × 100, one decimal half up) read cells of the same row;
- `share` reads one column: each row's part of the column's total, in whole
  per cents adding to 100 (largest remainder);
- `total` names the columns summed into a total row put last, its share
  cells 100%. A total row needs two rows to add up.

A cell is read only when it is one number as a customer types it: "40",
"650 000 so‘m", "1,5 mln", "$120.55", "12 %". Two numbers, a range, a word
before the number (taxminan, ~) or a figure as ambiguous as "1,150" are not
read: the cell computed from it stays blank, never a guess. Every number read
is held to what the customer said (`trusted`, when one is given) unless code
wrote it in this pass, so a computed cell rests on verified numbers only; the
finish has grounded every input already, and this is the second lock. The
results are code-written and exempt from grounding: finish calls this after
it has grounded the parts.

Units and scales follow the inputs: 120 mln and 300 mln add to "420 mln";
an amount takes the price's currency and scale ("2" × "1,5 mln so‘m" is
"3 mln so‘m"); inputs that disagree are added as full numbers. The decimal
mark and the thousands are the paper's language's ("1 067,08" in Uzbek and
Russian, "1,067.08" in English), a difference carries its sign ("+22",
"−3").

What a table does when a row cannot be computed is its template's (the table
placement's parameters in the entry's default template):

- `partial`: `named` (the default: the total of the rows that have a figure,
  labelled as the items listed, "Jami (ko‘rsatilgan moddalar)") or `none`
  (an offer prints no total rather than a total of some of its lines);
- `total_label` and `named_label`: the label keys of the total row's word
  (else the built-in "Jami / Итого / Total" and its "items listed" form);
- `round: currency`: amounts to the currency's smallest unit, whole so‘m and
  cents of a dollar or a euro, read from the price cell or the `currency`
  fact; the total is the sum of the rounded amounts.

A total row the model wrote (a "Jami" line, or a row an earlier pass marked
`total` and a change sent back) is taken out and made again, so a total the
customer typed that differs from the sum of the lines never prints. A per
cent of a level indicator (a figure that is itself a per cent) is a dash.
"""
import copy
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import numbers
from .catalogue import LOCALES

# The words of a total row when the template has none, plain and for a total of only the items with a figure.
TOTAL = {'uz': 'Jami', 'ru': 'Итого', 'en': 'Total'}
NAMED = {'uz': 'Jami (ko‘rsatilgan moddalar)', 'ru': 'Итого (указанные статьи)', 'en': 'Total (items listed)'}
# A row that is a total, whoever wrote it: its first cell starts with a total's word.
TOTAL_ROW = re.compile(r'^\s*(?:jami|жами|итого|всего|total|grand\s+total|subtotal)(?![^\W\d_])', re.IGNORECASE)
CELL = ' | '
GAP = '[    ]'
# One number as typed: groups of three by spaces, by dots or commas with the other mark for decimals, by dots or
# commas alone (two groups at least, so "1,150" is left to the paper's language), or plain digits with decimals.
NUMBER = re.compile(rf'(?P<sign>[+\-−–])?{GAP}*(?P<digits>\d{{1,3}}(?:{GAP}\d{{3}})+(?:[.,]\d+)?'
                    rf'|\d{{1,3}}(?:\.\d{{3}})+,\d+|\d{{1,3}}(?:,\d{{3}})+\.\d+'
                    rf'|\d{{1,3}}(?:\.\d{{3}}){{2,}}|\d{{1,3}}(?:,\d{{3}}){{2,}}|\d+(?:[.,]\d+)?)')
# What may stand before a number: a currency's sign or code, nothing else (no "taxminan", no "~").
PREFIX = re.compile(r'^(?:\$|€|£|₽|usd|eur|rub|uzs)?$', re.IGNORECASE)
# The currencies whose smallest unit is a cent; every other (so‘m first) is rounded to whole units.
CENTS = re.compile(r'\$|€|£|\b(?:usd|eur|gbp|dollar\w*|euro\w*|доллар\w*|долл\.?|евро)\b', re.IGNORECASE)
WHOLE = re.compile(r"so[‘'ʻ`’]?m|сум|сўм|uzs|\bsum\b|\bруб\w*|₽|rub\b", re.IGNORECASE)
MINUS = '−'
DASH = '—'
HUNDRED = Decimal(100)


class Read:
    """One cell read as a number: its value, and how it was written (scale word, unit, currency sign, decimals)."""

    __slots__ = ('value', 'scale', 'exp', 'unit', 'prefix', 'decimals')

    def __init__(self, value, scale, exp, unit, prefix, decimals):
        self.value, self.scale, self.exp, self.unit = value, scale, exp, unit
        self.prefix, self.decimals = prefix, decimals

    @property
    def percent(self):
        return self.unit == '%'

    def style(self):
        return (self.scale.casefold().rstrip('.'), self.exp, self.unit.casefold(), self.prefix.casefold())


def _scale_of(text):
    """(scale word as written, its power of ten, the rest) when `text` starts with one of numbers' scale words."""
    found = numbers.SCALE.match(text)
    if not found or found.start() != 0:
        return '', 0, text
    word = (found.group(1) or found.group(2) or '').strip()
    folded = word.casefold().rstrip('.')
    exp = next((power for stem, power in numbers.SCALES if folded.startswith(stem)), 0)
    return (word, exp, text[found.end():]) if exp else ('', 0, text)


def _decimal(digits, locale=None):
    """The value of the digits of one number (see NUMBER), or None."""
    squeezed = re.sub(GAP, '', digits)
    if re.fullmatch(r'\d{1,3},\d{3}', squeezed) and locale == 'en':
        # An English paper's "1,920" is its customer's thousands, as English writes them.
        squeezed = squeezed.replace(',', '')
    elif re.fullmatch(r'\d{1,3}[.,]\d{3}', squeezed) and locale != 'en':
        # "1,150" is a thousand and a hundred and fifty in English and one and fifteen hundredths in Uzbek.
        return None
    # Groups by dots with a decimal comma ("1.067,08"), or by commas with a decimal point ("2,100.00"): both marks
    # are there, so neither is in doubt.
    if re.fullmatch(r'\d{1,3}(?:\.\d{3}){2,}|\d{1,3}(?:\.\d{3})+,\d+', squeezed):
        squeezed = squeezed.replace('.', '').replace(',', '.')
    elif re.fullmatch(r'\d{1,3}(?:,\d{3}){2,}|\d{1,3}(?:,\d{3})+\.\d+', squeezed):
        squeezed = squeezed.replace(',', '')
    else:
        squeezed = squeezed.replace(',', '.')
    try:
        return Decimal(squeezed)
    except InvalidOperation:
        return None


def read(text, locale=None):
    """A cell as a Read, or None when it is not one number as a customer types it (see the module's docstring).

    `locale` settles "1,920": thousands in an English paper, unread in an
    Uzbek or Russian one, where the comma is the decimal mark.
    """
    text = ' '.join(str(text or '').split())
    if not text or '_' in text:
        return None
    found = list(NUMBER.finditer(text))
    if len(found) != 1:
        return None
    match = found[0]
    prefix = text[:match.start()].strip()
    if not PREFIX.fullmatch(prefix):
        return None
    value = _decimal(match.group('digits'), locale)
    if value is None:
        return None
    if match.group('sign') in ('-', '−', '–'):
        value = -value
    rest = text[match.end():].strip()
    scale, exp, rest = _scale_of(rest)
    unit = ' '.join(rest.split()).strip(' .,;:')
    if re.search(r'\d', unit) or len(unit) > 24:
        return None
    decimals = max(0, -value.as_tuple().exponent)
    return Read(value * (Decimal(10) ** exp), scale, exp, unit, prefix, decimals)


def _known(text, trusted):
    """Whether every number of a cell is the customer's; True when there is nothing to hold it to."""
    values = getattr(trusted, 'values', None)
    if values is None:
        return True
    return not numbers.unknown(text, values)


# ---------------------------------------------------------------- writing numbers


def _grouped(integer, separator=' '):
    """'1150000' as '1 150 000' (or '1,150,000' with a comma)."""
    digits = str(integer)
    head = len(digits) % 3 or 3
    return separator.join([digits[:head]] + [digits[index:index + 3] for index in range(head, len(digits), 3)])


def number(value, locale, *, decimals=None, places=2, sign=False):
    """`value` written for the paper: grouped thousands, the language's marks, half-up rounding.

    Uzbek and Russian group with spaces and mark decimals with a comma
    ("1 067,08"), English with commas and a point ("1,067.08").

    `decimals` fixes the places (a currency's cents); otherwise up to `places`
    are kept and trailing zeros dropped. `sign` writes "+" before a positive
    value; a negative one always has the minus sign.
    """
    quantum = Decimal(1).scaleb(-(decimals if decimals is not None else places))
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    if decimals is None and rounded == rounded.to_integral_value():
        rounded = rounded.quantize(Decimal(1))
    text = format(abs(rounded), 'f')
    whole, _, fraction = text.partition('.')
    if decimals is None:
        fraction = fraction.rstrip('0')
    mark = '.' if locale == 'en' else ','
    written = _grouped(int(whole), ',' if locale == 'en' else ' ') + (mark + fraction if fraction else '')
    if rounded < 0:
        return MINUS + written
    return ('+' + written) if sign and rounded > 0 else written


def _styled(value, reads, locale, *, decimals=None, sign=False):
    """`value` written in the shared style of `reads`: their scale word, unit and currency sign when all agree."""
    styles = {read_.style() for read_ in reads}
    if len(styles) == 1:
        first = reads[0]
        shown = value / (Decimal(10) ** first.exp) if first.exp else value
        # A scaled figure keeps two places ("1,25 mln"); a plain one the most its inputs were written with.
        places = 2 if first.exp else max(read_.decimals for read_ in reads)
        text = number(shown, locale, decimals=decimals, places=places, sign=sign)
        pieces = [first.prefix + text if first.prefix in ('$', '€', '£', '₽') else
                  ' '.join(piece for piece in (first.prefix, text) if piece)]
        pieces += [piece for piece in (first.scale, first.unit) if piece]
        return ' '.join(pieces)
    return number(value, locale, decimals=decimals, places=2, sign=sign)


# ---------------------------------------------------------------- the table


def _cells(item, count):
    """A row's cells, held to the part's columns (finish.cells: padded, a middle cell with ' | ' merged)."""
    from .finish import cells
    return cells(item, count)


def _row(values, total=None):
    middle = list(values[1:-1])
    while middle and not middle[-1]:
        middle.pop()
    item = {'label': values[0], 'text': CELL.join(middle), 'value': values[-1] if len(values) > 1 else ''}
    if total:
        item['total'] = total
    return item


def _is_total(item, values, totals, computed):
    """Whether a row is a total (the model's "Jami" line, or one this module made in an earlier pass)."""
    if item.get('total'):
        return True
    if TOTAL_ROW.match(values[0]):
        return True
    # A row with no name whose only figures sit in total columns is a total that lost its word.
    return not values[0].strip() and any(values[column].strip() for column in totals if column < len(values)) and \
        all(not values[column].strip() for column in range(1, len(values)) if column not in totals | computed)


def _settings(entry):
    """{part id: the table placement's parameters} of the entry's default template (see the module's docstring)."""
    from . import catalogue
    try:
        template = catalogue.template(entry.templates[0]) if entry.templates else {}
    except KeyError:
        return {}, {}
    found = {}
    for placement in template.get('flow') or ():
        if placement.get('block') == 'table' and placement.get('part') and isinstance(placement.get('params'), dict):
            found.setdefault(placement['part'], placement['params'])
    return found, template.get('labels') or {}


def _word(labels, key, fallback, locale):
    label = labels.get(key) if isinstance(key, str) else None
    if isinstance(label, dict) and (label.get(locale) or label.get('en')):
        return label.get(locale) or label['en']
    return fallback[locale]


def _currency_places(reads, currency):
    """The fixed places of an amount rounded to its currency: 2 for cents, 0 for whole units, None when unknown."""
    marks = ' '.join([read_.prefix + ' ' + read_.unit for read_ in reads] + [currency or ''])
    if CENTS.search(marks):
        return 2
    if WHOLE.search(marks):
        return 0
    return None


def _shares(values):
    """Whole per cents of `values` (positive Decimals) adding to 100, by the largest remainder; None for no total."""
    total = sum(values)
    if total <= 0 or any(value < 0 for value in values):
        return None
    exact = [value * HUNDRED / total for value in values]
    floors = [int(share) for share in exact]
    left = 100 - sum(floors)
    order = sorted(range(len(values)), key=lambda index: (-(exact[index] - floors[index]), index))
    for index in order[:left]:
        floors[index] += 1
    return floors


def _table(section, part, params, labels, trusted, locale, currency):
    """One table part's section made: model totals out, computed cells in, the total row last."""
    count = len(part.get('columns') or ()) or None
    if count is None:
        return
    rules = [rule for rule in part.get('computed') or () if isinstance(rule, dict)]
    totals = {column for column in part.get('total') or () if 0 < column < count}
    computed = {rule['column'] for rule in rules}
    grid = []
    for item in section.get('items') or ():
        if not isinstance(item, dict):
            continue
        values = _cells(item, count)
        if not (totals and _is_total(item, values, totals, computed)):
            grid.append(values)
    # The cells this pass wrote: code's own figures, read back without asking the customer's words for them.
    made = set()

    def value(row, column):
        text = grid[row][column] if column < count else ''
        found = read(text, locale)
        if found is None:
            return None
        if (row, column) not in made and not _known(text, trusted):
            return None
        return found

    for rule in rules:
        column, op, of = rule['column'], rule['op'], [index for index in rule['of'] if index < count]
        if column >= count or not of:
            continue
        if op == 'share':
            readable = [(row, value(row, of[0])) for row in range(len(grid))]
            readable = [(row, found) for row, found in readable if found is not None]
            shares = _shares([found.value for _, found in readable]) if readable else None
            for (row, _), share in zip(readable, shares or ()):
                grid[row][column] = f'{share}%'
                made.add((row, column))
            continue
        for row in range(len(grid)):
            inputs = [value(row, index) for index in of]
            if any(found is None for found in inputs):
                continue
            result = _computed(op, inputs, grid[row], params, locale, currency)
            if result is not None:
                grid[row][column] = result
                made.add((row, column))
    rows = [_row(values) for values in grid]
    total = _total_row(grid, totals, rules, params, labels, locale, made, value)
    section['items'] = rows + ([total] if total else [])


def _computed(op, inputs, row, params, locale, currency):
    """One computed cell of a row, written; None when it cannot be computed (a per cent of zero)."""
    if op == 'product':
        result = inputs[0].value
        for found in inputs[1:]:
            result *= found.value
        price = inputs[-1]
        decimals = _currency_places([price], currency) if params.get('round') == 'currency' else None
        if decimals is None and params.get('round') == 'currency':
            decimals = 2 if any(found.decimals for found in inputs) else 0
        plain = all(not found.exp and not found.prefix for found in inputs[:-1])
        return _styled(result, [price], locale, decimals=decimals) if plain else number(result, locale,
                                                                                         decimals=decimals)
    if op == 'sum':
        return _styled(sum(found.value for found in inputs), inputs, locale)
    if op == 'difference':
        return _styled(inputs[0].value - sum(found.value for found in inputs[1:]), inputs, locale, sign=True)
    if op == 'percent':
        if any(found.percent for found in inputs) or any(cell.strip() == '%' for cell in row):
            # A level indicator, itself a per cent: its per cent of plan says nothing a reader can use.
            return DASH
        base = inputs[1].value if len(inputs) > 1 else None
        if not base:
            return None
        return number(inputs[0].value * HUNDRED / base, locale, decimals=1) + '%'
    return None


def _total_row(grid, totals, rules, params, labels, locale, made, value):
    """The total row of a table, or None: two rows at least, and none when a partial total is not printed."""
    if not totals or len(grid) < 2:
        return None
    count = len(grid[0])
    cells, partial, any_value = [''] * count, False, False
    for column in sorted(totals):
        found = [(row, value(row, column)) for row in range(len(grid))]
        readable = [item for _, item in found if item is not None]
        # Any row the table holds is an item of the total, its name alone included (an item bought, its sum unsaid).
        missing = [row for row, item in found if item is None and any(cell.strip() for cell in grid[row])]
        if missing:
            partial = True
        if len(readable) < 2:
            continue
        cells[column] = _styled(sum(item.value for item in readable), readable, locale,
                                decimals=max(item.decimals for item in readable) or None)
        any_value = True
    if not any_value or (partial and params.get('partial') == 'none'):
        return None
    for rule in rules:
        if rule['op'] == 'share' and rule['of'] and rule['of'][0] in totals and rule['column'] < count \
                and any((row, rule['column']) in made for row in range(len(grid))):
            cells[rule['column']] = '100%'
    if partial:
        cells[0] = _word(labels, params.get('named_label'), NAMED, locale)
    else:
        cells[0] = _word(labels, params.get('total_label'), TOTAL, locale)
    return _row(cells, 'named' if partial else True)


def _currency(content):
    """The `currency` fact of the paper, if it has one: the money a price cell does not name."""
    for section in content.get('sections') or ():
        if isinstance(section, dict) and section.get('id') == 'facts':
            for item in section.get('items') or ():
                if isinstance(item, dict) and item.get('label') == 'currency':
                    return str(item.get('text') or item.get('value') or '')
    return ''


def apply(entry, content, trusted, locale=None):
    """`content` with the computed cells and total rows of `entry`'s tables made (see the module's docstring).

    `trusted` is facts.trusted(data) (anything without `values` holds
    nothing to it); `locale` the paper's language, for the decimal mark and
    the total's word. An entry without a computed table gets `content` back
    as it is; otherwise a copy. Never raises on content: a table it cannot
    read keeps its cells as the finish left them.
    """
    parts = [part for part in entry.parts if part.get('kind') == 'table' and not part.get('retired')
             and (part.get('computed') or part.get('total'))]
    if not parts or not isinstance(content, dict):
        return content
    wanted = {part['id'] for part in parts}
    locale = locale if locale in LOCALES else 'en'
    settings, labels = _settings(entry)
    content = copy.deepcopy(content)
    currency = _currency(content)
    for section in content.get('sections') or ():
        if not isinstance(section, dict):
            continue
        part = entry.part(section.get('id'))
        if part is None or part['id'] not in wanted:
            continue
        try:
            _table(section, part, settings.get(part['id'], {}), labels, trusted, locale, currency)
        except Exception as error:
            import logging
            # The type only: an exception's message may carry the customer's figures.
            logging.getLogger(__name__).warning('Category %s: table %s not computed (%s)', entry.id, part['id'],
                                                type(error).__name__)
    return content
