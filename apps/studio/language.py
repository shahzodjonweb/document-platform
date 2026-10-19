"""The one language a document is written in, decided once and said to every call.

Resolved when a draft is prepared, stored with it, and handed to the outline,
the writing calls, the repair call and the length top-up alike: no later stage
reads the description again and picks a language of its own.

Precedence (owner's rules, 2026-10-12):

1. A language the customer picked for this request — the studio's language
   menu or the bot's review-screen button (`options.locale_chosen`). It is made
   after the description is read and is how a misread one is put right.
2. An output language the description names ("in English", "o‘zbek tilida",
   "на русском языке"), in whichever language it is written.
3. For a change request, the document's own language.
4. A description written in Russian, with no language named, is answered in
   Russian (kept from the first ad wave).
5. The language sent with the request, then the account's settings
   (preferences.output_locale, then the interface language), then English.

A change to selected pages keeps the document's language whatever it names or
picks: only those pages are rewritten (apps/studio/domain.py).

Uzbek is always written in the Latin alphabet, whatever alphabet the
description used; English in Latin; Russian in Cyrillic.
"""
import re
import unicodedata
from dataclasses import dataclass

SUPPORTED = ('en', 'uz', 'ru')
FALLBACK = 'en'
NAMES = {'en': 'English', 'uz': 'Uzbek', 'ru': 'Russian'}
SCRIPTS = {'en': 'latin', 'uz': 'latin', 'ru': 'cyrillic'}


def normalised(text):
    """Uzbek is typed with several apostrophes, and o‘ sometimes as ó; treat them as one."""
    folded = unicodedata.normalize('NFKC', text or '')
    for mark in ('‘', '’', 'ʻ', 'ʼ', '`', '´'):
        folded = folded.replace(mark, "'")
    folded = re.sub('[óòōŏ]', "o'", folded)
    folded = re.sub('[ÓÒŌŎ]', "O'", folded)
    return folded.replace('ğ', "g'").replace('Ğ', "G'")


# --- Reading an output language out of a description ------------------------

LANGUAGE_WORDS = {
    'en': r"ingi?liz|english|англи\w*|инглиз",
    'ru': r"rus|russian|русск\w*|рус",
    'uz': r"o'zbek|ozbek|uzbek|узбек\w*|ўзбек|узбек",
}
# Russian asks for a language in the prepositional ("на английском") and puts
# a text into one in the accusative ("переведи на английский").
RUSSIAN_STEMS = {'en': r"английск", 'ru': r"русск", 'uz': r"узбекск|ўзбекск"}
# What to do, after "… tilida": the request, not a participle ("yozilgan", written).
# Not "tarjima": "inglizcha tarjimasini qo‘shing" adds a translation beside the text.
DOING = (r"(?:tayyorla(?!ngan|gan)\w*|yoz(?!ilgan|gan)\w*|bo'lsin|bolsin|bo'lishi|qil(?!ingan|gan)\w*|kerak"
         r"|chiqsin|chiqar\w*|ber\w*|ishla(?!ngan|gan)\w*|tuz\w*"
         r"|тайёрла\w*|ёз\w*|бўлсин|қил\w*|керак|бер\w*|туз\w*"
         r"|сделай\w*|напиши\w*|подготов\w*|нужн\w*|составь\w*|создай\w*|переведи\w*)")
# Words that may stand between the language and what to do: "o‘zbek tilida
# 15 ta slayd tayyorlab ber". Counts, formats and how it should read.
FILLER = (r"(?:\d+(?:-?ta\w*)?|ta|tadan|-ta|та|varaq\w*|bet\w*|sahifa\w*|slayd\w*|slide\w*|taqdimot\w*|prezentats\w*"
          r"|hujjat\w*|referat\w*|matn\w*|maqola\w*|insho\w*|mustaqil|ish\w*|pdf|pptx|word|doklad\w*"
          r"|batafsil|qisqa\w*|to'liq|chiroyli|ilmiy|rasmiy|menga|bizga|iltimos"
          r"|слайд\w*|тақдимот\w*|ҳужжат\w*|реферат\w*|матн\w*|батафсил|менга|илтимос"
          r"|документ\w*|презентац\w*|текст\w*|доклад\w*|страниц\w*|подробн\w*|кратк\w*|пожалуйста)")
_PUNCT = r"[.,!?;:()\]\n]"
# An Uzbek/Cyrillic-Uzbek construction ends the request, or leads into what to
# do, past a few of those words — the last of them may end the request too:
# "rus tilida 10 ta slayd", "Kosmos haqida ingliz tilida taqdimot".
_UZ_ENDS = r"(?=(?:\s*" + FILLER + r"\b){0,5}\s*(?:" + DOING + r"|" + _PUNCT + r"|$))"
# "ingliz tiliga tarjima qil", "inglizchaga o‘gir": putting the text into a
# language, not "rus tiliga oid so‘zlar" (words to do with Russian).
_UZ_INTO = (r"(?=\s+(?:[^\s.!?;:]+\s+)?(?:tarjima\s+(?:qil|et|ber)(?!ma)\w*|tarjima(?=\s*(?:[.!?,;:]|$))"
            r"|o'gir(?!ma)\w*|o'tkaz(?!il|gan|ma)\w*|qil(?!in|gan|ma)\w*|ber(?!il|gan|ma)\w*"
            r"|таржима\s+(?:қил|эт|бер)\w*|ўгир\w*|ўтказ\w*|қил\w*|бер\w*))")
# "in English" ends the request or leads into the rest of it, never into a noun
# it qualifies: "women in Russian history" is a subject, not an instruction, and
# so are "in Russian and Soviet history" and "in English-speaking countries".
_EN_ENDS = (r"(?=\s*(?:" + _PUNCT + r"|$|\d|(?:please|only|too|as\s+well|for|about|on|with|so|that|using|from|to"
            r"|by|of|covering|including|explaining|describing|where|which|latin|lotin|cyrillic|script"
            r"|and\s+(?:make|add|include|use|keep|put|write|give|send))\b)|\s+[-–—])")
_RU_ENDS = (r"(?=\s*(?:" + _PUNCT + r"|$|\d|(?:пожалуйста|и|для|о|об|про|по|с|на|в|из|чтобы|где|который\w*"
            r"|документ\w*|презентац\w*|слайд\w*|текст\w*|реферат\w*|доклад\w*)(?![\wЀ-ӿ])|" + DOING
            + r")|\s+[-–—])")
# The grammar and study of a language: "Phrasal verbs in English", "Rus tilida
# olmoshlar haqida", "Глаголы на английском" are about the language.
UZBEK_TERMS = (r"fe'l\w*|so'z\w*|zamon(?!aviy)\w*|grammat\w*|omonim\w*|sinonim\w*|antonim\w*|frazeolog\w*"
               r"|talaffuz\w*|imlo\w*|harf\w*|tovush\w*|kelishik\w*|morfolog\w*|sintaksis\w*|leksik\w*|fonetik\w*"
               r"|lug'at\w*|idiom\w*|dialekt\w*|sheva\w*|artikl\w*|predlog\w*|olmosh\w*|sifat(?:dosh\w*|lar\w*)?"
               r"|ravish(?:dosh\w*|lar\w*)?|son(?:lar\w*)?|padej\w*|bog'lovchi\w*|ko'makchi\w*|ko'plik\w*|undov\w*"
               r"|o'zlashma\w*|yasalish\w*")
ENGLISH_TERMS = (r"cases?|verbs?|nouns?|pronouns?|adjectives?|adverbs?|prepositions?|conjunctions?|interjections?"
                 r"|numerals?|particles?|participles?|gerunds?|infinitives?|modals?|conditionals?|tenses?|grammar"
                 r"|vocabulary|loanwords?|borrowings?|neologisms?|synonyms?|antonyms?|homonyms?|idioms?|proverbs?"
                 r"|collocations?|phraseolog\w*|spelling|pronunciation|punctuation|syntax|morphology|phonetics"
                 r"|phonology|intonation|vowels?|consonants?|harmony|dialects?|slang|plurals?|declensions?"
                 r"|conjugations?|suffix(?:es)?|prefix(?:es)?|morphemes?|phonemes?|alphabets?|orthography|terms"
                 r"|terminology|euphemisms?|metaphors?")
RUSSIAN_TERMS = (r"падеж\w*|глагол\w*|местоимен\w*|прилагательн\w*|наречи\w*|существительн\w*|причасти\w*"
                 r"|деепричасти\w*|суффикс\w*|приставк\w*|орфограф\w*|произношен\w*|алфавит\w*|лексик\w*"
                 r"|синоним\w*|антоним\w*|омоним\w*|заимствован\w*|фразеолог\w*|идиом\w*|грамматик\w*|говорящ\w*")
GRAMMAR_PHRASES = (r"word\s+(?:order|formation|stress)|vowel\s+harmony|(?:reported|direct|indirect)\s+speech"
                   r"|(?:present|past|future)(?:\s+perfect)?\s+(?:simple|perfect|continuous|progressive|indefinite)"
                   r"|(?:passive|active)\s+voice")
# The one word (or two) just before the language: "Synonyms in Uzbek", "Word
# order in Russian", "Inglizcha so‘zlar o‘zbek tilida".
TERM_BEFORE = re.compile(UZBEK_TERMS + r"|maqol(?!a)\w*|" + ENGLISH_TERMS + r"|" + RUSSIAN_TERMS, re.IGNORECASE)
PHRASE_BEFORE = re.compile(GRAMMAR_PHRASES, re.IGNORECASE)
# The words between "… tilida" and "haqida": "Rus tilida fe'l zamonlari haqida"
# is about Russian verbs.
LINGUISTIC = re.compile(
    r"\b(?:" + UZBEK_TERMS + r"|" + GRAMMAR_PHRASES + r"|" + RUSSIAN_TERMS
    + r"|gap\w*|qo'shimcha\w*|maqol\w*|adabiyot\w*|she'r\w*|asar\w*|tarjima\w*|qoida\w*|conditional\w*"
    r"|grammar\w*|word\w*|verb\w*|noun\w*|tense\w*|vocabular\w*|literatur\w*"
    # …and speaking, teaching or writing in it: "rus tilida gapiradigan", "o‘qitish".
    r"|gapir\w*|so'zlash\w*|muloqot\w*|o'qit\w*|o'rgan\w*|dars\w*|ta'lim\w*|\w+(?:gan|digan|uvchi\w*))\b",
    re.IGNORECASE)
# "Women in Russian, Soviet and post-Soviet history": a list of adjectives.
_LIST_OF_ADJECTIVES = re.compile(r",\s*(?:[\w'-]+,?\s+){0,3}?(?:and|or)\s+(?:[\w'-]+\s+)?(?:history|literature"
                                 r"|culture|politics|economy|art|music|cinema|society|war|empire|revolution)s?\b",
                                 re.IGNORECASE)
_NAME = re.compile('|'.join(LANGUAGE_WORDS.values()), re.IGNORECASE)
# A correction names the wrong language too: "Не на русском, а на узбекском",
# "Why is it in Russian? I need it in Uzbek", "Rus tilida emas, o‘zbek tilida".
_NOT_BEFORE = re.compile(r"(?<![\wЀ-ӿ'])(?:not|no|nega|why|не|почему|зачем)(?![\wЀ-ӿ'])", re.IGNORECASE)
_NOT_AFTER = re.compile(r"[^.,!?;:\n]{0,15}?(?<![\wЀ-ӿ'])(?:emas|эмас)(?![\wЀ-ӿ'])", re.IGNORECASE)
_WORD = re.compile(r"(?<![\wЀ-ӿ'-])[\wЀ-ӿ'-]+")


def _patterns(words, stem):
    """Each way of naming a language, and whether a topic can look the same."""
    return [
        # "ingliz tilida", "English language da", "рус тилида": the language, then the request.
        (re.compile(r"\b(?:" + words + r")\s*(?:tilida|tilda|language\s*da|тилида|тилда)\b" + _UZ_ENDS,
                    re.IGNORECASE), True),
        # "inglizcha", "ruscha da", "ўзбекча".
        (re.compile(r"\b(?:" + words + r")(?:cha|ча)(?:\s*(?:da|да))?\b" + _UZ_ENDS, re.IGNORECASE), True),
        # "ingliz tiliga tarjima qil", "inglizchaga o‘gir".
        (re.compile(r"\b(?:" + words + r")(?:\s*(?:tiliga|tilga|тилига|тилга)|chaga|чага)\b" + _UZ_INTO,
                    re.IGNORECASE), False),
        # "in (the) English (language)", "into Russian".
        (re.compile(r"\b(?:in|into)\s+(?:the\s+)?(?:" + words + r")(?:\s+language)?\b" + _EN_ENDS, re.IGNORECASE),
         True),
        # "translate it to English", "convert into Uzbek".
        (re.compile(r"\b(?:translate|convert|rewrite)\b(?:\s+[^\s.!?;:]+){0,8}?\s+(?:in)?to\s+(?:the\s+)?(?:"
                    + words + r")\b", re.IGNORECASE), False),
        # "Make an English version", "Russian version please" — not "add the
        # English translation of each term", which keeps the text as it is.
        (re.compile(r"\b(?:make|create|write|prepare|give|need|want|produce|send)\b(?:\s+(?:me|us|it|this|that|a|an"
                    r"|the|its|my|our|full|complete|whole|separate|new)){0,3}\s+(?:" + words
                    + r")\s+(?:version|translation)\b", re.IGNORECASE), False),
        (re.compile(r"(?:^|(?<=[.!?\n]))\s*(?:an?\s+|the\s+)?(?:" + words
                    + r")\s+(?:version|translation)(?=\s*(?:please\b|[.!]|$))", re.IGNORECASE), False),
        # "на русском языке", "на английском" — not "на английском рынке".
        (re.compile(r"(?<![\wЀ-ӿ])на\s+(?:" + stem + r")ом\s+язык\w*", re.IGNORECASE), True),
        (re.compile(r"(?<![\wЀ-ӿ])на\s+(?:" + stem + r")ом" + _RU_ENDS, re.IGNORECASE), True),
        # "Переведи на английский": into a language only when translating, not
        # "Влияние французского на английский язык".
        (re.compile(r"(?<![\wЀ-ӿ])переве\w*(?:\s+[^\s.!?;:]+){0,5}?\s+на\s+(?:" + stem + r")(?:ий|ом)(?![\wЀ-ӿ])",
                    re.IGNORECASE), False),
        # "по-английски", "по русски".
        (re.compile(r"(?<![\wЀ-ӿ])по-\s*(?:" + words + r")", re.IGNORECASE), False),
        (re.compile(r"(?<![\wЀ-ӿ])по\s+(?:" + stem + r")и(?![\wЀ-ӿ])", re.IGNORECASE), False),
        # "Language: English", "Til: o'zbek", "Язык: русский".
        (re.compile(r"\b(?:output\s+)?(?:language|til|tili|язык|тил|тили)\s*[:=\-–—]\s*(?:" + words + r")",
                    re.IGNORECASE), False),
    ]


PATTERNS = {code: _patterns(words, RUSSIAN_STEMS[code]) for code, words in LANGUAGE_WORDS.items()}
# "Rus tilida fe'l zamonlari haqida slayd": the words between the language and
# "haqida" (about) are its subject. It starts on a non-space, so a run of blank
# space can be matched only one way.
_ABOUT = {code: re.compile(r"\b(?:" + words + r")\s*(?:tilida|tilda|тилида)\s+(\S.{0,79}?)\s+"
                           r"(?:haqida|ҳақида|хақида)\b", re.IGNORECASE)
          for code, words in LANGUAGE_WORDS.items()}


def _clause_start(body, start, size):
    """Where the clause holding `start` begins, looking back at most `size` characters."""
    begin = max(0, start - size)
    cuts = [body.rfind(mark, begin, start) + 1 for mark in '.,!?;:\n–—']
    dash = body.rfind(' - ', begin, start)
    return max(begin, dash + 3 if dash >= 0 else 0, *cuts)


def _negated(body, match):
    """'Not in Russian', 'Не на русском', 'Nega rus tilida?', 'rus tilida emas'."""
    return bool(_NOT_BEFORE.search(body, _clause_start(body, match.start(), 16), match.start())
                or _NOT_AFTER.match(body, match.end()))


def _topic(body, match):
    """'Phrasal verbs in English', 'from English into Uzbek', 'in Russian, Soviet and post-Soviet history'."""
    words = _WORD.findall(body, _clause_start(body, match.start(), 40), match.start())[-2:]
    if words and (TERM_BEFORE.fullmatch(words[-1]) or PHRASE_BEFORE.fullmatch(' '.join(words))):
        return True
    if len(words) == 2 and words[0].lower() == 'from' and _NAME.fullmatch(words[1]):
        return True
    return bool(_LIST_OF_ADJECTIVES.match(body, match.end()))


def _first(pattern, body, checked, keep=None):
    """Where the first naming of a language that is meant as one starts, or None."""
    for match in pattern.finditer(body):
        if (not _negated(body, match) and not (checked and _topic(body, match))
                and (keep is None or keep(body, match))):
            return match.start()
    return None


def explicit(text, keep=None):
    """The output language a description names, or None.

    The earliest one named wins. A language that is the subject — "Xitoy tilida
    omonimlar", "women in Russian history", "на русском рынке" — is not one,
    and neither is one the description says it does not want. `keep(body,
    match)`, when given, says which of the namings left count, read on the
    normalised body: a CV's says a language the person speaks is not one
    (apps/studio/cv/content.py names_the_cvs_language).
    """
    # A run of blank space reads as one space, so no pattern can backtrack over it.
    body = re.sub(r'[^\S\n]+', ' ', normalised(text))
    found = []
    for code, patterns in PATTERNS.items():
        starts = [start for start in (_first(pattern, body, checked, keep) for pattern, checked in patterns)
                  if start is not None]
        if not starts:
            # "Ingliz tilida sun'iy intellekt haqida taqdimot" asks for English;
            # "Rus tilida fe'l zamonlari haqida" is about Russian verbs.
            about = next((about for about in _ABOUT[code].finditer(body)
                          if not LINGUISTIC.search(about.group(1)) and not _negated(body, about)
                          and (keep is None or keep(body, about))), None)
            starts = [about.start()] if about else []
        if starts:
            found.append((min(starts), code))
    return min(found)[1] if found else None


# --- What a text is written in -----------------------------------------------

# Every Cyrillic block, not only the basic one: a stray letter from any of them
# is still a Cyrillic letter in a Latin document.
CYRILLIC = re.compile('[Ѐ-ԯᲀ-᲏ⷠ-ⷿꙀ-ꚟᴫᵸ]')
LATIN = re.compile(r'[A-Za-zÀ-ɏ]')
UZBEK_CYRILLIC = re.compile(r'[ЎўҚқҒғҲҳ]')
RUSSIAN_WORDS = re.compile(r'(?<![\wЀ-ӿ])(?:и|в|на|о|об|с|для|по|не|что|как|это|из|к|у|от|при|или|также|которые|является)'
                           r'(?![\wЀ-ӿ])', re.IGNORECASE)
# A suffix is matched from the start of its word only: from every letter of a
# long unbroken run, the search would take quadratic time. "-лик" is Uzbek
# (бирлик, ёшлик), not the Russian "республик" or "католик".
UZBEK_CYRILLIC_WORDS = re.compile(r'(?<![\wЀ-ӿ])(?:ва|учун|билан|ҳақида|хақида|ҳам|хам|бу|мен|сен|керак|бўлсин|эса|ёки)'
                                  r'(?![\wЀ-ӿ])|(?<![\wЀ-ӿ])[Ѐ-ӿ]+(?:лари|ларни|нинг|даги|(?<![бо])лик)\b',
                                  re.IGNORECASE)
ENGLISH_WORDS = re.compile(r"\b(?:the|and|of|to|is|are|in|that|for|with|as|by|this|it|on|be|from|an|or|which|its"
                           r"|was|were|has|have|can|their|these|such)\b", re.IGNORECASE)
UZBEK_WORDS = re.compile(r"\b(?:va|bilan|uchun|bu|ham|esa|yoki|hamda|bo'lib|qilib|orqali|kabi|deb|emas|bor|yo'q"
                         r"|edi|ekan|bo'ladi|mumkin|kerak|lekin|ammo|shu|ushbu|bunda|qanday|uning|ular)\b"
                         r"|\b\w+(?:ning|larni|lari|dagi|ladi|moqda|ishi|ilgan)\b", re.IGNORECASE)


def cyrillic_share(text):
    cyrillic, latin = len(CYRILLIC.findall(text or '')), len(LATIN.findall(text or ''))
    return cyrillic / (cyrillic + latin) if cyrillic + latin else 0.0


# Russian, not Uzbek Cyrillic: letters Uzbek does not use, Russian endings and requests.
# Endings from the start of a word and numbers from their first digit, as above.
RUSSIAN_LETTERS = re.compile(r'[ЫыЩщ]')
RUSSIAN_SIGNS = re.compile(r'(?<![\wЀ-ӿ])[Ѐ-ӿ]+(?:ого|его|ому|ему|ыми|ими|ая|яя|ую|юю|ое|ые|ых|ться|ешь|ишь|ию)'
                           r'(?![\wЀ-ӿ])'
                           r'|(?<![\wЀ-ӿ])(?:сделай|напиши|подготовь|создай|составь|расскажи|опиши|про)(?![\wЀ-ӿ])'
                           r'|(?<!\d)\d+\s*(?:слайд(?:ов|а)|страниц\w*|лист(?:ов|а))',
                           re.IGNORECASE)


def _russian(body):
    return (len(RUSSIAN_WORDS.findall(body)) >= 2 or bool(RUSSIAN_LETTERS.search(body))
            or bool(RUSSIAN_SIGNS.search(body)))


def written_in_russian(text):
    """A description written in Russian — not Uzbek in Cyrillic letters."""
    body = normalised(text)
    return (cyrillic_share(body) >= 0.6 and not UZBEK_CYRILLIC.search(body)
            and not UZBEK_CYRILLIC_WORDS.search(body) and _russian(body))


def written_in(text, *, least_words=8):
    """'en', 'uz', 'ru', or None when the text is too short or too mixed to tell.

    Only a whole passage is judged: a heading, a name or a term in another
    alphabet says nothing about the language of the text around it.
    """
    body = normalised(text)
    words = re.findall(r"[\wЀ-ӿ']+", body)
    if len(words) < least_words:
        return None
    share = cyrillic_share(body)
    if share >= 0.6:
        uzbek = len(UZBEK_CYRILLIC.findall(body)) + 2 * len(UZBEK_CYRILLIC_WORDS.findall(body))
        russian = (len(RUSSIAN_WORDS.findall(body)) + len(RUSSIAN_LETTERS.findall(body))
                   + len(RUSSIAN_SIGNS.findall(body)))
        if uzbek >= 2 and uzbek >= russian / 2:
            return 'uz'
        return 'ru' if russian >= 2 else None
    if share > 0.25:
        return None
    english, uzbek = len(ENGLISH_WORDS.findall(body)), len(UZBEK_WORDS.findall(body))
    if english >= 0.12 * len(words) and english > 2 * uzbek:
        return 'en'
    if uzbek >= 0.08 * len(words) and uzbek > 2 * english:
        return 'uz'
    return None


# --- Deciding ----------------------------------------------------------------

@dataclass(frozen=True)
class Resolution:
    locale: str
    source: str  # picked | prompt | document | prompt_language | request | settings | default

    @property
    def script(self):
        return SCRIPTS[self.locale]


def settings_locale(account):
    """The account's chosen output language, then its interface language."""
    preferences = getattr(account, 'preferences', None) or {}
    for value in (preferences.get('output_locale') if isinstance(preferences, dict) else None,
                  getattr(account, 'locale', None)):
        if value in SUPPORTED:
            return value
    return None


def resolve(prompt, *, picked=None, requested=None, settings=None, document=None, keep=None):
    """The language to write in, and what decided it.

    `keep` narrows which languages the prompt names count (explicit).
    """
    if picked in SUPPORTED:
        return Resolution(picked, 'picked')
    named = explicit(prompt, keep)
    if named:
        return Resolution(named, 'prompt')
    # A change request may be written in any language about a document that
    # stays in its own: only a language it names, or one picked, changes it.
    if document in SUPPORTED:
        return Resolution(document, 'document')
    if written_in_russian(prompt):
        return Resolution('ru', 'prompt_language')
    if requested in SUPPORTED:
        return Resolution(requested, 'request')
    if settings in SUPPORTED:
        return Resolution(settings, 'settings')
    return Resolution(FALLBACK, 'default')


# --- What the model is told ----------------------------------------------------

# The same for every call in one language, and placed after the long stable
# instructions so a deck's cached prefix is shared across languages.
COMMON = (
    'Target language: {name}. It was resolved from the customer\'s request before this call and is final: '
    'it overrides the language the description, the sources or the outline happen to be written in. Write '
    'every text field in it — title, headings, body, list items, table cells, chart labels, captions, '
    'speaker notes, questions and answers — except image_query, which is always in English, and verbatim '
    'source quotes. Compose each sentence directly in {name}, as a native writer of {name} would, rather than '
    'translating a draft from another language.'
)
NATIVE = {
    'uz': (
        ' Write modern standard Uzbek in the Latin alphabet only: o‘ and g‘ with the ‘ mark (o‘zbek, g‘oya), ʼ for '
        'the tutuq belgisi (maʼlumot, taʼlim, sanʼat), sh, ch, ng — never a Cyrillic letter, not in a heading, a list '
        'item, a table, a name or within a word, even when the description is written in Cyrillic. Write as an '
        'educated native speaker writes: natural Uzbek word order and grammar, the terms Uzbek textbooks and '
        'official texts use in the field, and an Uzbek word instead of a needless Russian or English loanword '
        '("sohalarida keng qo‘llanilmoqda", not "sferalarida realizatsiya qilinmoqda"); established international '
        'terms (texnologiya, internet, iqtisodiyot) stay. Dates and ordinals the Uzbek way: 2024-yil, 15-mart, '
        '3-bob; decimals with a comma (3,5 foiz). Keep each term the same throughout. Avoid stock phrases '
        '("Bugungi kunda", "Maʼlumki", "Shuni taʼkidlash joizki", "muhim ahamiyat kasb etadi") and never begin two '
        'sections the same way; do not be stiff or bureaucratic. Russian names in Uzbek Latin spelling (Pushkin, '
        'Moskva), well-known foreign names in their established Uzbek form (Shekspir, Nyuton), brand, product and '
        'organisation names as their owners write them (Google, Payme, IT Park).'
    ),
    'en': (
        ' Write fluent, natural English in the Latin alphabet only: never a Cyrillic letter. Write Russian or '
        'Uzbek names and terms in Latin letters, using the established English form where there is one '
        '(Tashkent, Samarkand). Use precise, internationally accepted terminology and a tone that suits the '
        'kind of document; prefer specific explanations to general statements, connect paragraphs logically, '
        'and avoid filler and stock phrasing ("in today\'s fast-paced world", "it is important to note", '
        '"delve into").'
    ),
    'ru': (
        ' Write natural, grammatical Russian in standard Russian orthography, as an educated native speaker '
        'writes it — not a word-for-word rendering of English or Uzbek: Russian word order, correct cases and '
        'aspect, established Russian academic and technical terms, and no calques, needless anglicisms or '
        'transliterated words where a Russian term exists. Latin letters only for URLs, brand and product names '
        'and technical identifiers; units of measurement in Russian (км, кг, МВт, %); Uzbek and other names in '
        'their established Russian form (Ташкент, Самарканд, Узбекистан); quotation marks «ёлочки». Avoid '
        'канцелярит and stock phrases («в современном мире», «играет важную роль», «следует отметить», '
        '«является неотъемлемой частью»); prefer a verb to a chain of nouns («влияет», not «оказывает '
        'влияние»). Keep paragraphs coherent, with smooth transitions.'
    ),
}


def instructions(locale):
    """The language part of a call's instructions."""
    return COMMON.format(name=NAMES[locale]) + NATIVE[locale]


def wire(locale):
    """The language fields of a call's input."""
    return {'output_locale': locale, 'output_language': NAMES[locale], 'output_script': SCRIPTS[locale]}
