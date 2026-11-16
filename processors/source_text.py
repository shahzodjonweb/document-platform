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

# The longest text read from one file: past it the file has far more than the
# 1,000 pages any upload may have (at two bytes a character, 16 MiB is over
# eight million characters, 2,700 parts), so it is refused as too long without
# decoding it all.
MAX_TEXT_BYTES = 16 * 1024 * 1024

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


def _windows_1251(raw):
    """The text of a Windows-1251 file, or None when its high bytes are not Cyrillic writing."""
    try:
        text = raw.decode('cp1251')
    except UnicodeDecodeError:
        return None
    # One byte is one character in this code page, so bytes and characters line up.
    telling = [ch for byte, ch in zip(raw, text) if byte >= 0x80 and byte not in _SHARED]
    cyrillic = sum(_cyrillic(ch) for ch in telling)
    if cyrillic < 0.95 * len(telling):
        return None
    # Every accented Latin letter is a Cyrillic one in this code page: "cafe"
    # with its accent would read "caf" and a Cyrillic letter. Cyrillic words
    # stand apart from Latin ones, so when most of the Cyrillic letters touch a
    # Latin letter it is Western text, which is not guessed at.
    touching = sum(1 for i, ch in enumerate(text) if _cyrillic(ch) and (_latin(text[i - 1:i]) or _latin(text[i + 1:i + 2])))
    return None if touching * 2 > cyrillic else text


def _cyrillic(ch):
    return '\u0400' <= ch <= '\u04ff' and ch.isalpha()


def _latin(ch):
    return ch.isascii() and ch.isalpha()


def _plain(text):
    """True for writing, False for a binary file that happened to decode."""
    if '\x00' in text:
        return False
    controls = sum(1 for ch in text if (ord(ch) < 32 and ch not in '\t\n\r\f\v\x1a') or 0x7f <= ord(ch) < 0xa0)
    return controls * 100 <= len(text)


def decode(raw):
    """The text of a `.txt` file's bytes, with line ends made `\\n`, or None when it is not text.

    In order: a byte-order mark (UTF-8, UTF-16 little or big endian); strict
    UTF-8; then Windows-1251, the "ANSI" of Russian and Uzbek Cyrillic
    Windows, when at least 95% of the high bytes that tell code pages apart are
    Cyrillic letters and most of them are not inside Latin words. Nothing is ever guessed with replacement characters: a
    lone surrogate could be neither stored nor sent to the worker. A NUL, or
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
            text = _windows_1251(raw)
    if text is None or not _plain(text):
        return None
    return text.replace('\r\n', '\n').replace('\r', '\n')


_SENTENCE = re.compile(r'.*?(?:[.!?…]+["»”’)\]]*\s+|$)', re.S)
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
