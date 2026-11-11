"""App settings read from the environment under the DocMaster name.

`env('PDFCRAFT_BIN')` reads DOCMASTER_PDFCRAFT_BIN, then the pre-rename
PDFMASTER_PDFCRAFT_BIN, then the default. It lives in `processors` because the
sandboxed child (`python -m processors`) imports nothing from Django or `apps`.

Rename migration: the PDFMASTER_ fallback can go once no deployment `.env`,
compose file or CI job sets a PDFMASTER_ name that this module reads.
"""
import os

PREFIX = 'DOCMASTER_'
LEGACY_PREFIX = 'PDFMASTER_'


def names(name):
    """Both spellings of one setting, the current one first."""
    return PREFIX + name, LEGACY_PREFIX + name


def env(name, default=None):
    """The setting's value, or `default` when neither spelling is set (an empty value counts as unset)."""
    for key in names(name):
        value = os.environ.get(key)
        if value:
            return value
    return default
