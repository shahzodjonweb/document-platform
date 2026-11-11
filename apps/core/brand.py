"""The product's name wherever the code writes it: bot screens, notices, file metadata, admin.

Translated copy (telegram/ux_copy.py, telegram/channels.py, email texts) spells it in the
sentence itself. App-level names moved to DocMaster with a migration (session and challenge
cookies: apps.core.middleware.LegacyCookieMiddleware; DOCMASTER_* settings: processors/env.py).
Deployment names (Docker project, containers, volumes, database, bucket, server folders,
compose variables) still use the old one until they are moved together with the server.
"""
PRODUCT_NAME = 'DocMaster'
