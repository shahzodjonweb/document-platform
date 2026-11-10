"""The product's name wherever the code writes it: bot screens, notices, file metadata, admin.

Translated copy (telegram/ux_copy.py, telegram/channels.py, email texts) spells it in the
sentence itself. Internal names (cookies, PDFMASTER_* settings, containers, the bucket)
keep the old one on purpose: renaming them would sign everyone out or break deploys.
"""
PRODUCT_NAME = 'DocMaster'
