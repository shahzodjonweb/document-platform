"""Plain text and old Word files as AI sources: pure functions, no I/O.

A category's sources may be a `.txt` or an old binary Word `.doc` as well as a
PDF or `.docx` (upload purpose 'ai_source', apps/core/services.upload_file).
The upload door and the source reader both use this module, so the "pages"
counted when a file arrives are the parts the model is later shown and the two
200-page checks of a draft agree.

It imports nothing but the standard library and nothing of the app, so the
standalone source reader can load it inside its bounded child.
"""
import re
import struct

# A "page" of a Word or text file is a part of at most this many characters.
PAGE_CHARS = 3000

# The most pages any upload may have (processors/engine.MAX_PAGES).
MAX_PARTS = 1000

# The longest text read from one file. No encoding takes more than four bytes
# a character, so a file past this holds more characters than 1,000 full parts
# and is refused as too long before it is decoded. The decoded text is at most
# a few dozen megabytes, and decoding and cutting it keep nothing else that
# grows with it (test_upload_ai_source pins the peak).
MAX_TEXT_BYTES = MAX_PARTS * PAGE_CHARS * 4

_BOMS = ((b'\xef\xbb\xbf', 'utf-8'), (b'\xff\xfe', 'utf-16-le'), (b'\xfe\xff', 'utf-16-be'))


def _shared(byte):
    """True for a high byte Windows-1251 and Windows-1252 read as the same punctuation."""
    try:
        cyrillic, western = bytes([byte]).decode('cp1251'), bytes([byte]).decode('cp1252')
    except UnicodeDecodeError:
        return False
    return cyrillic == western and not cyrillic.isalpha()


# Typographic quotes, dashes, the ellipsis, «», №... An Uzbek Latin file saved
# by Notepad as "ANSI" holds o‘ and g‘ as 0x91 and 0x92 and no Cyrillic at all:
# these bytes are the same character in either code page, so they neither
# prove nor disprove Cyrillic and are left out of the 95% count below.
_SHARED = frozenset(b for b in range(0x80, 0x100) if _shared(b))


def _cyrillic(ch):
    return '\u0400' <= ch <= '\u04ff' and ch.isalpha()


def _cp1251_letter(byte):
    try:
        return _cyrillic(bytes([byte]).decode('cp1251'))
    except UnicodeDecodeError:
        return False


# One byte is one character in this code page, so both counts below are made
# on the bytes with bytes.translate: a list of the characters themselves costs
# about 80 bytes each for Cyrillic, a gigabyte for a 16 MiB file.
_NOT_TELLING = bytes(b for b in range(256) if b < 0x80 or b in _SHARED)
_NOT_CYRILLIC = bytes(b for b in range(256) if not _cp1251_letter(b))
# A Cyrillic letter with a Latin letter on either side (every character in
# this range that cp1251 decodes to is a letter).
_TOUCHING = re.compile(r'(?<=[A-Za-z])[\u0400-\u04ff]|[\u0400-\u04ff](?=[A-Za-z])')


def _windows_1251(raw):
    """The text of a Windows-1251 file, or None when its high bytes are not Cyrillic writing."""
    # 0x98 is the one byte this code page leaves undefined; a stray one is
    # taken as U+FFFD rather than refusing the file. It counts against the 95%.
    telling = raw.translate(None, _NOT_TELLING)
    cyrillic, telling = len(telling.translate(None, _NOT_CYRILLIC)), len(telling)
    if cyrillic < 0.95 * telling:
        return None
    text = raw.decode('cp1251', 'replace')
    # Every accented Latin letter is a Cyrillic one in this code page: "cafe"
    # with its accent would read "caf" and a Cyrillic letter. Cyrillic words
    # stand apart from Latin ones, so when most of the Cyrillic letters touch a
    # Latin letter it is Western text, which is not guessed at.
    touching = sum(1 for _ in _TOUCHING.finditer(text))
    return None if touching * 2 > cyrillic else text


_HIGH = re.compile(rb'[\x80-\xff]')


def _not_strict_utf8(raw, error):
    """The text of bytes strict UTF-8 refused: damaged UTF-8, else Windows-1251, else None.

    A file whose only break is its last character cut short, after at least
    one well-formed one, is UTF-8 however short it is: strict decoding stops
    at the first break, so everything before it decoded. Windows-1251 Cyrillic
    breaks UTF-8 long before its last byte.

    A file cut in the middle of a character, or one stray byte, fails strict
    UTF-8; read as Windows-1251 its lead bytes would each become a Cyrillic
    letter and the whole file mojibake. Well-formed multibyte characters almost
    never arise by chance in Windows-1251 text, which breaks UTF-8 at nearly
    every high byte, so many of them beside few breaks is UTF-8. A file with at
    most one break in a thousand characters (or a single one) is taken with
    U+FFFD where the bytes broke, which can be stored and shown; one damaged
    more than that is refused rather than guessed at as Windows-1251.
    """
    if error.reason == 'unexpected end of data' and _HIGH.search(raw, 0, error.start):
        return raw.decode('utf-8', 'replace')
    text = raw.decode('utf-8', 'replace')
    broken = text.count('\ufffd')
    multibyte = len(text) - len(text.encode('ascii', 'ignore')) - broken
    if multibyte < 10 * broken:
        # Let go of the UTF-8 reading first: both at once of a 12 MB file are 50 MB.
        del text
        return _windows_1251(raw)
    return text if broken <= max(1, len(text) // 1000) else None


_CONTROLS = re.compile('[\x01-\x08\x0e-\x19\x1b-\x1f\x7f-\x9f]')


def _plain(text):
    """True for writing, False for a binary file that happened to decode."""
    if '\x00' in text:
        return False
    # Control characters other than tab, the line ends, form feed and the old end-of-file mark.
    controls = sum(1 for _ in _CONTROLS.finditer(text))
    return controls * 100 <= len(text)


def decode(raw):
    """The text of a `.txt` file's bytes, with line ends made `\\n`, or None when it is not text.

    In order: a byte-order mark (UTF-8, UTF-16 little or big endian); strict
    UTF-8; UTF-8 with a few broken bytes, taken with U+FFFD there and never
    read as Windows-1251 (_not_strict_utf8); then Windows-1251, the "ANSI" of
    Russian and Uzbek Cyrillic Windows, when at least 95% of the high bytes
    that tell code pages apart are Cyrillic letters and most of them are not
    inside Latin words. A mark's codec is strict: a lone surrogate could be
    neither stored nor sent to the worker. A NUL, or
    control characters in more than one character in a hundred, is a binary
    file named `.txt` (and UTF-16 or UTF-32 without a mark comes out full of NULs).
    """
    raw = bytes(raw)
    for mark, codec in _BOMS:
        if raw.startswith(mark):
            try:
                text = raw[len(mark):].decode(codec)
            except UnicodeDecodeError:
                return None
            break
    else:
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as error:
            text = _not_strict_utf8(raw, error)
    if text is None or not _plain(text):
        return None
    return text.replace('\r\n', '\n').replace('\r', '\n')


# A sentence ends at the start of a run of . ! ? or … followed by closing
# quotes or brackets and a space. The run and the quotes are taken possessively
# and only where the run begins: otherwise, in a line of 40,000 dots, every
# position the lazy .*? reached would scan the rest of the run again, a cost
# that grows with the square of the length (25 s for 40,000 characters of
# "!?"). It splits normal text exactly as the plain pattern does. The spaces
# after the end are its group 1, so a sentence's length without them is known
# without copying it.
_SENTENCE = re.compile(r'.*?(?:(?<![.!?…])[.!?…]++["»”’)\]]*+(\s+)|$)', re.S)
_WORD = re.compile(r'(\S*)\s*')
# A run of spaces and line ends. Blank lines are found as the part of such a
# run up to its last line end: a repeated group, (?:[^\S\n]*\n)+, keeps a
# backtracking mark for every line it passes, 1.7 GB for 12 MB of line ends.
_SPACE_RUN = re.compile(r'\s+')
# Every character str.isspace() and the patterns' \s take; all lie below U+3001.
_SPACES = tuple(chr(c) for c in range(0x3001) if chr(c).isspace())

# Everything below walks the text and keeps only the part being filled: the
# upload counts pages inside the bot's 384 MiB container, where a list of every
# word of a 12 MB file (six million small strings) took over 360 MiB.


def _small(line, size):
    """The sentences of a long line, and the words or slices of a sentence longer than `size`, one at a time.

    Each is given as (start, end, stop) in the line, where `stop` is where it
    ends without its trailing spaces; they follow one another with no gap.
    """
    for sentence in _SENTENCE.finditer(line):
        start, end = sentence.span()
        if start == end:
            continue
        stop = sentence.start(1) if sentence.start(1) >= 0 else end
        if stop - start <= size:
            yield start, end, stop
            continue
        for word in _WORD.finditer(line, start, end):
            first, last = word.span()
            if first == last:
                continue
            if word.end(1) - first <= size:
                yield first, last, word.end(1)
                continue
            # A word is its letters then its spaces, so a slice of it ends its
            # letters where they end or where the slice does.
            for i in range(first, last, size):
                yield i, min(i + size, last), max(i, min(i + size, word.end(1)))


def _pieces(line, size):
    """A line longer than `size` cut into pieces of at most `size` characters, packed greedily.

    It is cut at sentence ends; a sentence longer than `size` at spaces, and a
    word longer than that anywhere. Each piece is the line's own characters.
    The bits follow one another, so the piece being filled is the line from
    `start`, and line[start:stop] is it without its trailing spaces: only a
    finished piece is copied out of the line.
    """
    start = stop = 0
    for first, _, ends in _small(line, size):
        if stop == start:
            # Nothing but spaces so far: they are dropped.
            start, stop = first, ends
        elif ends > first and ends - start > size:
            yield line[start:stop]
            start, stop = first, ends
        elif ends > first:
            stop = ends
    if stop > start:
        yield line[start:stop]


def _lines(text, size):
    """The text's lines without trailing spaces, a long one as its pieces; a run of blank lines as its count."""
    position, end = 0, len(text)
    while position <= end:
        run = _SPACE_RUN.match(text, position)
        last = text.rfind('\n', position, run.end()) if run else -1
        if last >= 0:
            yield text.count('\n', position, last + 1)
            position = last + 1
            continue
        stop = text.find('\n', position)
        stop = end if stop < 0 else stop
        line = text[position:stop].rstrip()
        position = stop + 1
        if not line:
            yield 1
        elif len(line) > size:
            yield from _pieces(line, size)
        else:
            yield line


def iter_pages(text, size=PAGE_CHARS):
    """The parts of `pages`, one at a time, so that a count can stop as soon as it is too many."""
    current = ''
    for line in _lines(text, size):
        if isinstance(line, int):
            # Blank lines are kept inside a part while it has room for them; the
            # first that does not fit ends the part and the rest go with it.
            if not current:
                continue
            if len(current) + line <= size:
                current += '\n' * line
            else:
                yield current.rstrip('\n')
                current = ''
        elif not current:
            current = line
        elif len(current) + 1 + len(line) <= size:
            current = f'{current}\n{line}'
        else:
            yield current.rstrip('\n')
            current = line
    if current:
        yield current.rstrip('\n')


def pages(text, size=PAGE_CHARS):
    """The parts of a Word or text file's text, in order: part N is "page" N + 1.

    Each part is at most `size` characters and is cut at a paragraph end (a
    line end); a paragraph longer than that at a sentence end, a sentence
    longer than that at a space, and a word longer than that anywhere. Parts
    are cut, never rewritten: the text the model is shown is the file's own,
    so a quotation it copies can be found again. An empty text has no parts.
    """
    return list(iter_pages(text, size))


def surely_over(text, parts, size=PAGE_CHARS):
    """True when the text holds more than `parts` full parts of characters other than spaces.

    Cutting drops only spaces, so such a text cannot fit and is refused
    without being cut. str.count makes no copy of the text.
    """
    return len(text) - sum(text.count(space) for space in _SPACES) > parts * size


# ------------------------------------------------------------------ old Word

OLE_MAGIC = b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
_FREE = 0xFFFFFFFA  # sector numbers from here up are markers, never sectors
_WORD_IDENTS = (0xA5EC, 0xA5DC)
# Storages that hold Visual Basic macros: Word's 'Macros' (with 'VBA' inside),
# and Excel's '_VBA_PROJECT_CUR' in a workbook embedded in the document.
_MACRO_STORAGES = frozenset({'macros', 'vba', '_vba_project_cur', '_vba_project'})


def _chain(fat, start, limit):
    """The sectors of a chain in the allocation table, or None when it loops or leaves the table."""
    sectors, seen = [], set()
    while start < _FREE:
        if start in seen or start >= len(fat) or len(sectors) >= limit:
            return None
        seen.add(start)
        sectors.append(start)
        start = fat[start]
    return sectors


def ole_entries(raw):
    """The directory of a compound file (an old Office file): [(name, type, start, size)], or None.

    `type` is 1 for a storage, 2 for a stream and 5 for the root. Only the
    header, the allocation table and the directory are read, all bounded by the
    file's own length; a damaged or looping file gives None. `raw` may be bytes
    or a read-only memory map of the file.
    """
    total = len(raw)
    if total < 512 or raw[:8] != OLE_MAGIC:
        return None
    try:
        major, order, shift = struct.unpack_from('<HHH', raw, 0x1A)
        if order != 0xFFFE or (major, shift) not in ((3, 9), (4, 12)):
            return None
        size = 1 << shift
        fat_count, first_directory = struct.unpack_from('<II', raw, 0x2C)
        first_difat, difat_count = struct.unpack_from('<II', raw, 0x44)
        sectors = (total + size - 1) // size
        if fat_count > sectors or difat_count > sectors:
            return None

        def sector(number):
            offset = (number + 1) * size
            if number >= _FREE or offset + size > total:
                raise ValueError('outside the file')
            return raw[offset:offset + size]

        fat_sectors = [n for n in struct.unpack_from('<109I', raw, 0x4C) if n < _FREE]
        per = size // 4
        seen = set()
        while first_difat < _FREE and len(fat_sectors) < fat_count:
            if first_difat in seen:
                return None
            seen.add(first_difat)
            values = struct.unpack(f'<{per}I', sector(first_difat))
            fat_sectors.extend(n for n in values[:-1] if n < _FREE)
            first_difat = values[-1]
        fat = []
        for number in fat_sectors[:fat_count]:
            fat.extend(struct.unpack(f'<{per}I', sector(number)))
        chain = _chain(fat, first_directory, sectors)
        if not chain:
            return None
        entries = []
        for number in chain:
            block = sector(number)
            for offset in range(0, size, 128):
                kind = block[offset + 0x42]
                length = struct.unpack_from('<H', block, offset + 0x40)[0]
                if kind not in (1, 2, 5) or not 2 <= length <= 64:
                    continue
                name = bytes(block[offset:offset + length - 2]).decode('utf-16-le', 'replace')
                start, stream_size = struct.unpack_from('<II', block, offset + 0x74)
                entries.append((name, kind, start, stream_size))
        return entries
    except (struct.error, ValueError, IndexError):
        return None


def has_macros(raw):
    """True for a compound file that holds a Visual Basic macro storage anywhere in it."""
    return any(kind == 1 and name.lower() in _MACRO_STORAGES for name, kind, _, _ in ole_entries(raw) or ())


def is_word97(raw):
    """True for an old binary Word document ("Word 97-2003", and Word 6 and 95, which antiword reads too).

    It is a compound file with a 'WordDocument' stream that starts with Word's
    file identifier. The stream is never under the 4,096-byte mini-stream cut
    off in a file Word wrote, so its first sector is found from the directory.
    """
    entries = ole_entries(raw)
    if not entries:
        return False
    shift = struct.unpack_from('<H', raw, 0x1E)[0]
    for name, kind, start, size in entries:
        if kind == 2 and name == 'WordDocument' and size >= 4096 and start < _FREE:
            offset = (start + 1) << shift
            if offset + 2 > len(raw):
                return False
            return struct.unpack_from('<H', raw, offset)[0] in _WORD_IDENTS
    return False


def doc_command(executable, path):
    """antiword's arguments for a file's text: UTF-8 whatever the locale, one line a paragraph."""
    return [executable, '-m', 'UTF-8.txt', '-w', '0', str(path)]


# A line that holds nothing but antiword's mark for a picture, with the line end before it.
_PICTURE = re.compile(r'\n[^\S\n]*\[pic\][^\S\n]*(?=\n|\Z)')


def doc_text(output):
    """The text antiword printed, as `pages` takes it; its "[pic]" marks for pictures are left out.

    The text is never split into a list of its lines, for the same reason as
    `pages`: only the stretches between marks are kept, and a file without
    pictures is not copied at all.
    """
    text = bytes(output).decode('utf-8', 'replace').replace('\r\n', '\n').replace('\r', '\n')
    if '[pic]' not in text:
        return text
    text = '\n' + text
    kept, position = [], 0
    for picture in _PICTURE.finditer(text):
        if picture.start() > position:
            kept.append(text[position:picture.start()])
        position = picture.end()
    kept.append(text[position:])
    return ''.join(kept)[1:]
