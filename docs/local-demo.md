# Local demonstration

Start the API and web application using the repository README. Keep both terminal processes running. The development script enables the local identity fixture, beta processors, synchronous jobs and sandbox commerce explicitly.

## Open the three surfaces

1. Visit http://127.0.0.1:3000/en/app and choose **Use local development account**.
2. Visit http://127.0.0.1:8000/ops/login and choose **Open local staff workspace**.
3. Visit http://127.0.0.1:3000/en/app/bot for a conversation with the real bot handlers using local transport. `/start`, `/tools`, `/usage`, `/create`, `/teach`, `/buy` and `/myfiles` use the same customer account.

The web app and bot simulator are localhost pages. A real Telegram bot is a local polling process connecting to Telegram's servers; it cannot be demonstrated as an independent Telegram service on localhost without a bot token.

## Configure your real bot through admin

At http://127.0.0.1:8000/ops/integrations, enter the token and username, and a reason for the change. Save configuration, test the connection, then start the local bot. The form never redisplays the saved token. Stop polling from the same page before switching to a webhook. To open the Mini App from a phone, configure a reachable HTTPS URL.

No token belongs in a chat message or committed file. Local encrypted configuration depends on `.private/integration.key`; preserve it with the database backup. A lost key makes the corresponding encrypted content unreadable.

## File processing and editor

Open **All tools**, choose a processor, upload synthetic files and review the server quote. Submit and download the actual result from task history. For premium editor commands, use **Plan & usage** to make an explicitly labeled sandbox purchase. It does not spend Stars. In **PDF editor**, upload a PDF, select a page and add edits. Review the quote, export and inspect the PDF. Redaction requires an explicit rasterization acknowledgement and exports a new PDF without original text, forms or object streams.

OCR requires the detected Tesseract runtime. PDF-to-Word produces reflowed editable text; PDF-to-Excel extracts native tables. Unsupported complex text replacement fails with an explanation instead of covering the original text.

## Document generation and education

Open **Create** or **Study & teaching**. Choose the feature, output language and format, supply content, and edit the outline. Local authoring requires your own body/questions and makes real PDF/PPTX files with zero AI charge. To enable AI generation, configure provider mode, model and API key in admin first; requests occur only after a quote is confirmed. An optional outline stage has its own quote before full generation. Supporting illustrations need the separate image model. Handwriting accepts a single image or one-page PDF through a qualified vision-model adapter; inspect uncertainty markers against the original.

After successful handwriting transcription, review and correct the text against the source, then save it. Exporting this reviewed content has a zero-AI-credit quote and makes no additional provider call. Changing the source requires a new transcription.

Education projects require explicit saving consent. Submit answers in saved practice to see persisted results and weak topics. Teacher exports separate learner material and private answer keys. Only learner artifacts can receive a share link; revoke it from the app and the link stops working.

Use **Saved workflows** for an ordered sequence of supported file operations, **Templates** for reusable settings, and **Batch processing** for independent inputs with individual outcomes. A retry cannot duplicate a settled child charge.

## Admin review

Switch the environment filter to **Development / test** to inspect local jobs, account activity and sandbox purchases. Staff roles separately control operations, support, finance and analyst views. Sensitive actions require a reason and append an audit event. Support replies appear in the customer's same ticket thread. Staff access and encrypted integration settings require the Administrator role.

The existing local account contains real test history produced during verification. The private GitHub repositories contain source and synthetic verification fixtures; the local database, credentials and private uploads remain on this machine. Nothing has been deployed publicly. Live provider, real-device and production infrastructure checks are listed separately in `verification.md`.
