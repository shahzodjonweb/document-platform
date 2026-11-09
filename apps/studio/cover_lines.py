"""The lines a customer asks to keep for their next decks' title slides: who made it, who checks it, class, school.

Kept in the account's preferences, packed like a draft (domain.pack), so the
names are never readable at rest; the profile never shows them (account_data)
and a settings save never drops them (core/views.py me). Forget takes them out.
The language of the deck they were kept from is kept with them: its labels
("Tayyorladi", "Выполнил", "Prepared by") are that language's. So is the Cover
sheet row each came from, when the client says: a bare "TATU" is a school there,
and a new deck reads it so rather than guessing from its words (title_lines._kept).
"""
import re
import unicodedata
from cryptography.fernet import InvalidToken
from django.db import transaction
from apps.core.errors import DomainError
from apps.core.models import Account
from .domain import pack,unpack
from .language import SUPPORTED
from .title_lines import LINE_CHARS,TITLE_LINES

KEY='cover_lines'
# The Cover sheet's rows (useDeckCover.COVER_ROLES): who made it, who checks it, the class or group, the school.
ROLES=('made','checked','group','school')

def _prefs(value):return value if isinstance(value,dict) else {}

def clean(lines,roles=None):
    """(lines, roles): the lines as a title slide takes them — control and format characters as spaces, one space
    between words, none blank — and the row of each, None where the client does not say.

    Anything else than one to eight lines of at most LINE_CHARS is refused, not trimmed: the customer sees what is kept.
    So are roles that are not one of ROLES or None for each line given; a blank line's goes with it.
    """
    if not isinstance(lines,list) or any(not isinstance(line,str) for line in lines):raise DomainError('invalid_parameters')
    if roles is None:roles=[None]*len(lines)
    if not isinstance(roles,list) or len(roles)!=len(lines) or any(role is not None and role not in ROLES for role in roles):
        raise DomainError('invalid_parameters')
    cleaned=[]
    for line,role in zip(lines,roles):
        line=re.sub(r'\s+',' ',''.join(' ' if unicodedata.category(char).startswith('C') else char for char in line)).strip()
        if len(line)>LINE_CHARS:raise DomainError('invalid_parameters')
        if line:cleaned.append((line,role))
    if not 1<=len(cleaned)<=TITLE_LINES:raise DomainError('invalid_parameters')
    return [line for line,_ in cleaned],[role for _,role in cleaned]

def deck_locale(value):
    """The deck language the lines are written in: one of the decks' own, or None when the client does not say."""
    if value is None:return None
    if not isinstance(value,str) or value not in SUPPORTED:raise DomainError('invalid_parameters')
    return value

def remembered(account):
    """{'lines', 'locale', 'roles'}: the kept lines, their deck's language and a row for each (None where not said);
    no lines, None and no roles when none can be read."""
    none={'lines':[],'locale':None,'roles':[]}
    token=_prefs(account.preferences).get(KEY)
    if not isinstance(token,str):return none
    try:kept=unpack(token.encode())
    except (InvalidToken,ValueError,TypeError):return none
    lines=kept.get('lines') if isinstance(kept,dict) else None
    if not isinstance(lines,list) or not all(isinstance(line,str) for line in lines):return none
    roles=kept.get('roles') if isinstance(kept.get('roles'),list) and len(kept['roles'])==len(lines) else [None]*len(lines)
    return {'lines':lines,'locale':kept['locale'] if kept.get('locale') in SUPPORTED else None,
            'roles':[role if role in ROLES else None for role in roles]}

def remember(account,lines,locale=None,roles=None):
    lines,roles=clean(lines,roles)
    kept={'lines':lines,'locale':deck_locale(locale),'roles':roles}
    # Under the row's lock, as `me` saves the rest of the preferences: neither writes over the other.
    with transaction.atomic():
        row=Account.objects.select_for_update().get(pk=account.pk)
        row.preferences={**_prefs(row.preferences),KEY:pack(kept).decode()}
        row.save(update_fields=['preferences'])
    account.preferences=row.preferences
    return kept

def forget(account):
    with transaction.atomic():
        row=Account.objects.select_for_update().get(pk=account.pk)
        row.preferences={key:value for key,value in _prefs(row.preferences).items() if key!=KEY}
        row.save(update_fields=['preferences'])
    account.preferences=row.preferences
