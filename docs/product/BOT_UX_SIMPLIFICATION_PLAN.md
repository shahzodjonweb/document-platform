# Friendlier, shorter Telegram journeys

24 September 2026. Implemented scope: bot messages, buttons, onboarding, file tasks, account navigation, billing, support and delivery in English, Uzbek and Russian.

## Plan

1. Audit every bot-owned message and button across all three locales. Use short, natural sentences and a consistent action vocabulary. Pair useful emoji with words; never make users decode an emoji-only action. Keep prices, approval meaning, expiry, account boundaries and recovery instructions explicit.
2. Put the four frequent tools on Home. Keep the complete catalog one tap away, with compact two-column choices instead of pagination.
3. Recognize uploads and show the next useful action. A lone PDF asks what to do; a second PDF selects merging. Images and Office documents select their matching conversion. Preserve an explicitly selected compatible tool.
4. Show the quote and Start button automatically when the files and required options are ready. Allow optional settings and show the revised quote after editing. Uploading or viewing a quote does not process or charge anything.
5. Remove redundant reset confirmations after a submitted task. Keep confirmation when new work would be discarded. Make Cancel during a text-entry step leave that step and retain the uploaded files.
6. Exercise these journeys through the real dispatcher in all three locales, including callback replay, stale controls, repeat uploads, edits, account linking, payments and worker delivery. Deploy the platform independently after checks pass.

## Action budget

Count taps, file sends and typed replies after Home; exclude opening Telegram and the initial language choice except in the first-contact row. The final Start tap stays explicit because it authorizes processing and allowance use.

| Journey | Before | After | What is removed |
| --- | ---: | ---: | --- |
| Merge two PDFs from Home | 6: category, tool, send twice, Review, Start | 4: Merge, send twice, Start | Category and Review taps |
| Convert one image to PDF from Home | 5: category, tool, send, Review, Start | 3: Images → PDF, send, Start | Category and Review taps |
| First contact with an image | 5: send, language, resend, Review, Start | 3: send, language, Start | Repeat upload and Review tap |
| Convert one image sent directly | 3: send, Review, Start | 2: send, Start | Review tap |
| Convert one Word document sent directly | 3: send, Review, Start | 2: send, Start | Review tap |
| Work on a PDF sent directly | Defaulted to merge and asked for more files | Send, choose a useful PDF action, Start when ready | Wrong default and extra navigation |
| Add a file to an unsubmitted merge/image task | Send, choose Add, Review | Send | Add and Review taps; files and cost refresh visibly |
| Start after a submitted task | New task, confirm | New task | Reset confirmation with no unsubmitted work at risk |
| Leave support/text entry | Cancel, confirm discard | Cancel | Confirmation; draft files are preserved |

Extract, delete and reorder still need the user's page choice. Authentication linking, paid purchases and support-ticket submission keep explicit confirmation. A draft containing unsubmitted work still needs confirmation before being discarded. Replacing the sole input or switching to a tool that needs a different file type also asks first. A single-file tool selected from a merge draft offers the existing PDFs directly, avoiding a repeat upload.

## Copy contract

- A short heading, one next-step instruction and the buttons needed now.
- One familiar emoji per action or status where it improves scanning; words carry the meaning.
- English uses direct phrases; Uzbek uses natural Latin-script wording with consistent apostrophes; Russian uses clear, polite everyday wording.
- Button labels describe the result: merge, download, send, stop, open. Avoid developer terms such as callback, quote token, meter and JSON.
- Error text explains the recovery. Do not imply a task ran, payment succeeded or account linked unless the corresponding service confirms it.
- Keep user file names and support text unchanged, HTML-escape them, and stay within Telegram's message limit.
- Public language choices remain recognizable in their own language.

## Release acceptance

The shortest happy paths work in every locale. Uploads and option edits create no job or consumption; one Start creates one job even if replayed. Editing invalidates an older Start control. A support/input cancel preserves the draft; a confirmed draft reset invalidates previous controls. A submitted job continues and its result remains accessible after New task. Foreign/stale buttons never mutate another account or a newer draft.

The accompanying [complete flow](BOT_UX_FLOW.md) describes recovery, identity, worker delivery and operational isolation.
