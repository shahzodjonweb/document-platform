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
# and is refused as too long before it is decoded. It also keeps a decoded
# file to a few dozen megabytes inside the bot's small container.
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
    try:
        text = raw.decode('cp1251')
    except UnicodeDecodeError:
        return None
    telling = raw.translate(None, _NOT_TELLING)
    cyrillic = len(telling.translate(None, _NOT_CYRILLIC))
    if cyrillic < 0.95 * len(telling):
        return None
    # Every accented Latin letter is a Cyrillic one in this code page: "cafe"
    # with its accent would read "caf" and a Cyrillic letter. Cyrillic words
    # stand apart from Latin ones, so when most of the Cyrillic letters touch a
    # Latin letter it is Western text, which is not guessed at.
    touching = sum(1 for _ in _TOUCHING.finditer(text))
    return None if touching * 2 > cyrillic else text


def _not_strict_utf8(raw):
    """The text of bytes strict UTF-8 refused: damaged UTF-8, else Windows-1251, else None.

    A file cut in the middle of a character, or one stray byte, fails strict
    UTF-8; read as Windows-1251 its lead bytes would each become a Cyrillic
    letter and the whole file mojibake. Well-formed multibyte characters almost
    never arise by chance in Windows-1251 text, which breaks UTF-8 at nearly
    every high byte, so many of them beside few breaks is UTF-8. A file with at
    most one break in a thousand characters (or a single one) is taken with
    U+FFFD where the bytes broke, which can be stored and shown; one damaged
    more than that is refused rather than guessed at as Windows-1251.
    """
    text = raw.decode('utf-8', 'replace')
    broken = text.count('\ufffd')
    multibyte = len(text) - len(text.encode('ascii', 'ignore')) - broken
    if multibyte < 10 * broken:
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
        except UnicodeDecodeError:
            text = _not_strict_utf8(raw)
    if text is None or not _plain(text):
        return None
    return text.replace('\r\n', '\n').replace('\r', '\n')


# A sentence ends at the start of a run of . ! ? or … followed by closing
# quotes or brackets and a space. The run and the quotes are taken possessively
# and only where the run begins: otherwise, in a line of 40,000 dots, every
# position the lazy .*? reached would scan the rest of the run again, a cost
# that grows with the square of the length (25 s for 40,000 characters of
# "!?"). It splits normal text exactly as the plain pattern does.
_SENTENCE = re.compile(r'.*?(?:(?<![.!?…])[.!?…]++["»”’)\]]*+\s+|$)', re.S)
_WORD = re.compile(r'\S*\s*')


def _split(text, pattern):
    return [match.group() for match in pattern.finditer(text) if match.group()]


def _pieces(line, size):
    """A line longer than `size` cut into pieces of at most `size` characters, packed greedily.

    It is cut at sentence ends; a sentence longer than `size` at spaces, and a
    word longer than that anywhere. Each piece is the line's own characters.
    """
    small = []
    for sentence in _split(line, _SENTENCE):
        if len(sentence.rstrip()) <= size:
            small.append(sentence)
            continue
        for word in _split(sentence, _WORD):
            small.extend([word] if len(word.rstrip()) <= size else [word[i:i + size] for i in range(0, len(word), size)])
    pieces, current = [], ''
    for piece in small:
        if not current.strip():
            current = piece
        elif len((current + piece).rstrip()) > size:
            pieces.append(current.rstrip())
            current = piece
        else:
            current += piece
    if current.strip():
        pieces.append(current.rstrip())
    return pieces


def pages(text, size=PAGE_CHARS):
    """The parts of a Word or text file's text, in order: part N is "page" N + 1.

    Each part is at most `size` characters and is cut at a paragraph end (a
    line end); a paragraph longer than that at a sentence end, a sentence
    longer than that at a space, and a word longer than that anywhere. Parts
    are cut, never rewritten: the text the model is shown is the file's own,
    so a quotation it copies can be found again. An empty text has no parts.
    """
    lines = []
    for line in text.split('\n'):
        line = line.rstrip()
        lines.extend(_pieces(line, size) if len(line) > size else [line])
    parts, current = [], ''
    for line in lines:
        if not current:
            current = line
        elif len(current) + 1 + len(line) <= size:
            current = f'{current}\n{line}'
        else:
            parts.append(current)
            current = line
    parts.append(current)
    return [part.strip('\n') for part in parts if part.strip()]


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


def doc_text(output):
    """The text antiword printed, as `pages` takes it; its "[pic]" marks for pictures are left out."""
    text = bytes(output).decode('utf-8', 'replace').replace('\r\n', '\n').replace('\r', '\n')
    return '\n'.join(line for line in text.split('\n') if line.strip() != '[pic]')
