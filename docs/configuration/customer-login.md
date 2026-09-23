# Customer sign-in configuration

Configure customer identity providers at **Admin → Integrations**. This page requires the Administrator role and an active staff session. Every save and connection test requires an audit reason. Customer sign-in remains separate from staff password and two-factor authentication.

## Google

1. In Google Cloud, configure the OAuth consent screen and create an OAuth client with application type **Web application**. If the consent screen is in testing mode, add the accounts that will test the app.
2. Add this exact authorized redirect URI for production:

   `https://pdfmaster.orderdesk.live/api/v1/auth/google/callback`

3. In **Google sign-in**, enter the client ID and client secret, check the redirect URI, enable Google sign-in, supply an audit reason, and save.
4. Open the customer web app and choose Google sign-in. A matching email address alone does not authorize merging customer accounts; use the authenticated account linking flow to connect another sign-in method.

The callback must use the same scheme, hostname, and port as **Telegram bot → Web application URL**, with the exact path `/api/v1/auth/google/callback`, no query string, and no fragment. Production requires HTTPS. Local development permits HTTP only on localhost/loopback; the typical local callback is `http://localhost:3000/api/v1/auth/google/callback`.

Client secrets are encrypted in the database. Their inputs remain blank after saving. Leave a secret blank to retain the existing value. Clear the enable checkbox to disable Google without deleting its saved settings. Changing the customer app's origin requires updating both the saved callback and Google's authorized redirect URI.

Google's setup reference: [OAuth 2.0 for web server applications](https://developers.google.com/identity/protocols/oauth2/web-server).

## Email and password

In **Email and password sign-in**, configure:

- SMTP host, port, and username.
- SMTP password or provider-issued application password.
- Sender email address authorized by your email provider.
- One secure transport mode: STARTTLS (commonly port 587) or implicit TLS (commonly port 465).

Enable email registration and recovery, provide an audit reason, and save. Then use **Test connection** to connect and authenticate using the saved settings. This test does **not** send an email and cannot prove that a provider will accept your sender or deliver to an inbox. Complete a customer registration to verify delivery after configuration. Provider-side sender/domain verification and DNS records, such as SPF/DKIM, must be configured with your chosen email service.

Email sends use the saved settings immediately; an application restart is unnecessary. Each connection has a ten-second timeout. Verification and password reset messages contain a code for the customer to enter in the app. The password is encrypted, never rendered or audited, and a blank password field preserves the saved password. Plain SMTP without encryption is rejected in production. Disable registration/recovery using the checkbox without removing the stored credentials.

For isolated development tests, `DEBUG=True` with Django's `django.core.mail.backends.locmem.EmailBackend` keeps outgoing mail in memory. Production always uses the saved SMTP configuration; it never prints verification codes to a console backend.

Implementation reference: [Django email connections](https://docs.djangoproject.com/en/5.2/topics/email/).

## Telegram and shared accounts

Keep the existing Telegram bot token, username, and web application URL configured. Customers who sign up with another method can add Telegram from their signed-in account settings after verifying control of that Telegram account. Linked methods use the same customer account, documents, plan, and usage balance. Do not create a separate customer account just to add a sign-in method.
