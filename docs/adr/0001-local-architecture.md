# ADR 0001: local implementation and repository boundaries

Accepted 2026-09-22. The user requested PDF Master using the supplied specification. The planning folder is product input, not an independent authorization to publish, purchase, or contact anyone.

Use two Git repositories under the workspace: document-web (Nuxt/Vue/TypeScript customer app) and document-platform (Django API, bot, processing and staff operations). No admin source or client is shipped with the customer build.

SQLite provides a zero-service local development baseline; PostgreSQL is the deployment database. Database transactions, unique idempotency keys and owner checks are mandatory in both. SQLite tests do not establish PostgreSQL concurrency/load behavior. Private local object storage is the development adapter. Server files are not served by STATIC/MEDIA URLs.

Local sign-in is an explicit, environment-gated developer convenience and never claims verified Telegram authentication. Production startup must disable it and provide Telegram credentials, secret key, allowed origins and a private storage/worker deployment. Development records are marked test and excluded from production metrics.

Paid checkout remains disabled with the supplied null commercial prices. Later releases stay cataloged and gated; an unimplemented operation is not made available through a placeholder success endpoint. Release gate status is separate from the existence of code.

Staff uses Django password hashes, a separate opaque HttpOnly ops_session cookie, eight-hour sessions, mandatory production TOTP, explicit role groups, CSRF, and audited actions. Staff sessions do not imply customer file access.
