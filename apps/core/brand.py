"""The product's name wherever the code writes it: bot screens, notices, file metadata, admin.

Translated copy (telegram/ux_copy.py, telegram/channels.py, email texts) spells it in the
sentence itself. Internal names are DocMaster too (cookies, settings, Docker projects, database,
server folders); the storage bucket keeps `pdfmaster`, and processors/env.py still reads an old
PDFMASTER_* setting when no DOCMASTER_* one is set.
"""
PRODUCT_NAME = 'DocMaster'
