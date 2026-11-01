# Editor UX brief: PDF and PPTX (revision 2)

Anchors re-checked 2026-11-01. Paths are relative to the workspace that holds both repositories (dw/ = document-web, dp/ = document-platform); bare .vue files are in dw/app/components/editor/, bare .py files in dp/apps/studio/ except services.py and allowance.py (dp/apps/core/).

## 1. Personas and top tasks

- **Dilnoza, student (uz, Free):** phone only; AI essays and decks due tomorrow; 15 file tasks and 5 AI documents a week, 3 AI edits per file (dp/docs/product/plan_seed.json:14-16).
- **Gulnora, teacher (ru/uz, Plus):** low-end Android, old Telegram, slow 3G; types Uzbek in Cyrillic; quiz decks; unlimited file tasks (dp/docs/product/plan_seed.json:38).
- **Rustam, office administrator (ru):** phone, plus phone-sized Telegram Desktop at work; Cyrillic Word contracts and scans, so PdfCraft fallbacks are his main path.

Of 27 real change requests, 22 were decks (dp/tests/test_edit_reading.py:37-93). 12 concern pictures: 6 add fitting pictures, 5 want one on every slide or page, 1 removes one; none uses the customer’s photo. 4 of the 5 PDF requests want pictures in AI-made PDFs. Also: Cyrillic letters (3), dictated covers (2), picture style (2), language (2), "send as PDF" (1).

| Task | Freq | Imp |
|---|---|---|
| T1 Fix a name, date or word in a PDF | daily | 5 |
| T2 Sign, fill a blank | daily | 5 |
| T3 Fitting pictures on every slide; swap or remove one | weekly | 5 |
| T4 Cover details, slide typos, Cyrillic to Latin | weekly | 5 |
| T5 Result back in the chat | daily | 5 |
| T6 Black out personal numbers | weekly | 5 |
| T7 Delete, rotate, reorder pages | weekly | 4 |
| T8 Add, delete, reorder slides; resize the quiz | weekly | 4 |
| T9 Redesign; fuller slides via AI | weekly | 4 |
| T10 Fill a form | weekly | 3 |

## 2. Principles

1. **Fixing never uses AI edits** (as in Gamma, https://help.gamma.app/en/articles/7834324-how-do-ai-credits-work-in-gamma); today every deck fix is a paid AI run (dp/telegram/delivery.py:122-132).
2. **One file task per draft, once.** Today each send is a new quote (views.py:435-442) and every non-AI job counts (allowance.py:58-66): five decks fixed twice would use 10 of Dilnoza’s 15 tasks. Count a send once per editor draft or AI-made file (tag jobs with editor_document_id or root_draft_id); preview jobs never count.
3. **Chat in, chat out.** Edit under every delivered file; tapping Send to chat is the permission to post (dw/docs/product/UI_UX_SPEC.md:172,177).
4. **Tap the thing.** No modes; the bottom bar only creates.
5. **Refuse at the tap, never at Send**, for every engine (today at export, dp/processors/editor.py:105,123,176,200,216).
6. **Edits stay put.** Pin photos, variants, seed and font size; never cut typed words silently.

## 3. Interaction model

**Frame (phone).** Telegram’s BackButton (dw/docs/product/UI_UX_SPEC.md:177); top row: file name, save icon (✓/↑/✕, words in aria-live), Undo, Redo, More.
- PDF bar: ＋ Add text · Sign · Picture · Black out · Pages; More: Highlight, Draw, Note, Forms, Exact position, Background picture.
- Deck bar: Pictures · Layout · Design · Slides · Ask AI, under a slide strip with +.

**Selection.** Order: own mark, text line, picture. Images over 80% of the page (OCR’d scans, certificates, covers) are skipped (More → Background picture); long press cycles stacked items; a cover title beats its photo. A docked bar shows Close plus up to four verbs.

**Text.**
- A field docks under the top row (≥16 px, caret at the tapped word), as Telegram iOS does not resize for the keyboard (https://github.com/TelegramMessenger/Telegram-iOS/issues/1410) and smaller inputs zoom (MarkLayer.vue:349).
- A width bar in the line’s font shows room left: up to 10% longer tightens spacing; more offers "Cover and retype, smaller".
- Tayyor runs PdfCraft text_edit as a job ("Checking…" meanwhile); success offers "Change all {n} places".
- Refusal ("These words can’t be changed in this file") offers Cover and retype (matched serif or sans, PT Serif or Noto Serif bold for Cyrillic, sampled background, as the overlay has only Noto Sans Regular, dp/processors/editor.py:94-99; digits in uploaded files are first erased by the black-out engine, white fill, that page only), Change it in the document’s text (AI-made files), or Make text editable (OCR, a file task, dp/processors/advanced.py:18).
- New text dropped on words asks "Change these words instead?".
- Decks: same field, live budget ("4 of 6 lines"); Cyrillic in an Uzbek deck offers "Lotinga o‘girish" with a preview (uzbek.py:36-99).

**Objects.**
- Marks land on finger lift (today pointerdown, MarkLayer.vue:69-83) and show the real image (today icons, MarkLayer.vue:322-324); attached images cost no extra task (allowance.py:58-66; delete the stale AssetField.vue:4-7 comment).
- One proportional corner handle, 44 px hit area; Move arrows and Exact position avoid drags, and below Bot API 7.7 marks never drag (https://core.telegram.org/bots/webapps); disableVerticalSwipes only while dragging.
- Signatures stay on the device (DeviceStorage, Bot API 9.0+, 5 MB per user; else localStorage), uploaded only at Send as a 24-hour input (dw/docs/product/UI_UX_SPEC.md:173).

**Pictures.** Deck sheet: Add to all slides · Another picture · Remove · From my phone · Photo/Drawing.
- Add to all slides runs the existing Pixabay search and model pick as an uncounted job, up to 12 (dp/docs/product/plan_seed.json:23); writing English image_query is internal, not an AI edit.
- Another picture steps through stored candidates; Find more searches in a job with the model’s English query (search is English-only, photos.py:159).
- From my phone shrinks to 1600 px, ~450 KB before upload (photos.py:58-59); Photo/Drawing sets options.photo_style (execution.py:133).
- AI-made PDFs get pictures as render_pdf image sections between paragraphs (execution.py:160), not overlays.

**Navigation.**
- PDF pages scroll (page chip, pinch zoom); Pages is a 3-column grid with Rotate · Move · Delete, never locked by content edits (today it is, PagesBoard.vue:17).
- Page changes stay in the draft, applied in order: overlays in the source frame; rotate, reorder, delete; black-out; rendered check. Marks display in the new frame but are stored in source coordinates; deleting a page with marks asks "Delete page 3 and its 2 changes?".
- Decks: swipe; the cover stays first (layouts.py:255-259); quiz slides, not sections (slides.py:852), form one fixed closing Questions block with Fewer questions and Remove quiz (5 per slide, pages.py:164).

**Undo and saving.** AI results show Before/After, and Undo does not return the AI edit (allowance.py:82-88). Autosave after 900 ms (dw/app/composables/useEditorSession.ts:42) and on visibilitychange; closing confirmation (Bot API 6.2+) only while unsaved. One draft per file (today one per open, views.py:408). Edit under a result, and /editor (today the bot draft’s input, dp/telegram/bot.py:2858-2862), reopen the source draft, still undoable: store editor_document_id or generation_draft_id on the result’s job (results are new files, services.py:292); the send replaces the result ("Version 2 of this file").

**Send.** The MainButton, Send to chat, commits any open field and opens the review sheet: changes by page, pages before → after, predicted size (over 50 MB arrives as a link, dp/telegram/delivery.py:159-162), cost by plan, new expiry; the quote is made once, here. Confirm states the cost; the bot posts the file (needs a mini_app origin, services.py:296) and the app closes (dw/app/components/DeckSetupView.vue:107-108); then Share to a group (shareMessage, Bot API 8.0+). Phones get decks as PPTX plus PDF; outside Telegram, Download. Allowance and channel gate show at open (today at quote and submit, services.py:199-200,261).

**Ask AI.** "✨ Ask AI to change" (✨ Изменить с ИИ; ✨ AI bilan o‘zgartirish) replaces "Make changes" (dp/telegram/ux_copy.py:190). On decks it acts on the current slide (revise_section_ids, revisions.py:43; dw/app/components/JobDetail.vue:152), with Whole deck and "Uses 1 AI edit; {left} of {limit} left"; only that slide locks during a run (revisions.py:79). Never on uploaded files.

**Desktop** (980 px+, R3) keeps the desktop report’s extras; shortcuts follow input type, not width; Telegram Desktop gets Expand (requestFullscreen, Bot API 8.0+).

## 4. Target flows

Taps exclude typing and scrolling; Send = MainButton plus Confirm.

| Flow | Steps | Taps/s | Today |
|---|---|---|---|
| F1 Fix a word (R2) | Edit→word→Send | 4/30; refused 5/45 | impossible (dp/processors/editor.py:140-152) |
| F2 Sign and date | Edit→Sign→signature→drag→＋ Add text→blank→Send | 8/50 | ~13 taps |
| F3 Pictures on every slide | Edit→Pictures→Add to all slides→Send | 5/≤90 | paid AI |
| F4 Cover details | Edit→Cover details (remembered)→Send | 4/40 | paid AI |
| F5 Black out a number (R2) | Edit→Black out→search→Black out all→Send | 6/25 | 60–120 s |
| F6 Delete a page among edits | Edit→Pages→page→Delete→Send | 6/15 | blocked (dw/app/composables/useEditorPages.ts:167-172) |
| F7 Move and add slides | Slides→drag 7 to 3→+→List→Send | 6/50 | AI only |

## 5. Features (MoSCoW)

**R1 Must** (phone, decks first: 22 of 27 requests)
- Deck: fields on the existing section editor (dw/app/components/StudioView.vue:1807-1925); add, delete, reorder slides; Questions block; fitting layouts only (layouts.py:190); Cover details (Mavzu, Tayyorladi, Qabul qildi, Guruh/Sinf, Maktab; 8 lines, title_lines.py:37-39) with opt-in "Remember for my next decks"; Lotinga o‘girish, its kept text passed to artifact_violations as the user’s own (execution.py:174-187).
- AI-made PDFs: add or remove pictures (render_pdf).
- Pinning: keep each slide’s photo and 4 candidate previews (photos.py:47) on our server (no hotlinking, photos.py:24-26), since every render re-searches and re-asks the model (execution.py:156; photos.py:351-353); store deck_seed, which is design plus title (variants/__init__.py:195-197), and each _variant (slides.py:962); fit-check pinned variants too (slides.py:895-897 skips it), offering "Pick another layout" rather than dropping bullets.
- Export without AI or photo_choice (skip execution.py:57-59); preview is a server PNG of the LibreOffice PDF, fitted in the same metric-compatible fonts, not Noto (slides.py:448): Calibri instead of Corbel (slides.py:47) to match Carlito; Caladea for Cambria.
- PDF: section 3’s marks, page changes and one draft per file; an "inspect for editing" call at open, cached by sha256, giving per page overlay and text-edit support, image boxes and field rectangles (today only counts and names, dp/processors/engine.py:290-292); page boxes normalised, not refused (dp/processors/editor.py:105).
- Shared: Telegram adapter with isVersionAtLeast (dw/docs/product/UI_UX_SPEC.md:181); web_app Edit and /editor buttons (dp/telegram/bot.py:2863 is a URL button); count-once rule; first-use hints ("Tap any words to change them").
- One size measure, json.dumps(..., ensure_ascii=False, separators=(',',':')), for quote, draft and client meter (dw/app/composables/useEditorCommands.ts:302-311), quote limit ≥ draft limit; today 10,000 escaped characters (services.py:190) versus 20,000 (views.py:422), so ~1,500 Cyrillic characters autosave, then fail.
- Per-account rate limits, not REMOTE_ADDR, a shared gateway (dp/apps/core/views.py:59-67; dp/apps/core/auth_views.py:15-16); checks and renders on job workers with a resident LibreOffice, short polling (2 web workers, dp/infra/Dockerfile:28).
- Range loading (Accept-Ranges, pdf.js disableAutoFetch), page 1’s server PNG first (today the whole file, dw/app/composables/useEditorRender.ts:111); deep links skip plans and studio (dw/app/app.vue:146).
- Settled jobs extend their source GenerationDraft to the result’s expiry (today 24 h from creation, domain.py:777).

**R1 Should:** Design sheet; per-slide Ask AI with Before/After; Share to a group. **R2 Must:** pdf.js text layer (none in dw/app); PdfCraft tap-to-edit behind a per-file flag; width bar; Change all; matched Cover and retype; Black out by tap and search (OCR first on scans), imaging only boxed pages (today all, dp/processors/editor.py:227-256); AI-made PDF text editing. **R3:** offline queue; Combine; tap-to-fill fields; desktop extras. **Could:** version history; free one-page engine preview; "Another look". **Won’t now:** free-form canvas; collages; uploaded .pptx; AI picture edits; server-stored signatures pending legal review (possible biometric data: https://kun.uz/en/news/2026/03/27/uzbekistan-amends-personal-data-law-to-facilitate-global-payment-systems).

## 6. Copy and localisation

- Banned: "click", "export", "quote", "rasterize", "DPI", "points", "encoding" (today dw/locales/extended.ts:605,679).
- ✏️ means no AI edit, ✨ one (dp/telegram/ux_copy.py:76 puts ✏️ on AI edits). Until count-once ships, a Free-plan send is never "free": "✏️ Edit · no AI edits used".
- Plus and Premium (unlimited file tasks, dp/docs/product/plan_seed.json:38,61) see string 6, Free string 5. String 7 warns at 80% of whichever limit comes first (size or 100 changes), replacing the change counter (dw/locales/extended.ts:804).
- Russian: formal вы, plurals via count(). Uzbek: Latin only; o‘/g‘ U+2018, tutuq belgisi U+02BC (uzbek.py:18); values inside the sentence (dw/locales/catalog.ts:438 «Mavjud bo‘ladi» says "will be available"). Search treats ‘ ʻ ’ ʼ ' ` alike and accepts ö ğ ş ç.
- Rows 2–3 replace Yashirish/Скрыть, Ko‘rinish/Макет and Dizayn/Дизайн; test both.

| # | en | ru | uz |
|---|---|---|---|
| 1 | ✏️ Edit | ✏️ Редактировать | ✏️ Tahrirlash |
| 2 | ＋ Add text · Sign · Picture · Black out · Pages | ＋ Добавить текст · Подпись · Картинка · Закрасить · Страницы | ＋ Matn qo‘shish · Imzo · Rasm · Bo‘yab yopish · Sahifalar |
| 3 | Pictures · Layout · Design · Slides · Ask AI | Картинки · Расположение · Оформление · Слайды · ИИ | Rasmlar · Joylashuv · Bezak · Slaydlar · AI |
| 4 | Send to chat | Отправить в чат | Chatga yuborish |
| 5 | Uses 1 file task; {left} of {limit} left | Спишется 1 задача с файлами; останется {left} из {limit} | 1 ta fayl vazifasi sarflanadi; {limit} tadan {left} ta qoladi |
| 6 | Included in your plan | Входит в ваш тариф | Tarifingizga kiritilgan |
| 7 | Too much for one file: send now, then keep editing | Слишком много для одного файла: отправьте и продолжайте | Bitta fayl uchun juda ko‘p: yuboring va davom eting |
| 8 | Deleted after 24 hours · Send again · Make again | Удалено через 24 часа · Отправить снова · Сделать заново | 24 soatdan keyin o‘chirildi · Qayta yuborish · Qayta yaratish |

## 7. States and messaging

- **Saving:** icon; string 7 from 80% of the limit; below Bot API 6.2, save on visibilitychange.
- **Confirm:** string 5 or 6 and "nothing is used if it fails" (allowance.py:25-26). If the week’s tasks are spent and the file dies before Monday 00:00 Tashkent (allowance.py:11; views.py:416), say so at open.
- **Refusal:** an open-time banner lists what works per page, and blocked tools say why; a failed rendered check at Send says "One change didn’t come out right; nothing was sent or used" (Show it · Send without it). Black-out asks "Black out {n} places for good?", naming pages that become pictures.
- **Conflict:** "Keep this phone’s (7 changes)" or "Keep the other one (9)", the loser kept in Undo once (today blind, Shell.vue:187-200); needs command ids, updated_at and a device label (dw/app/composables/useEditorCommands.ts:102; dp/processors/editor.py:54; models.py:53-60).
- **Expiry:** "Available until {time}" for whichever expires first, file or sections, amber under 3 h, refreshed after sends; then string 8, Make again prefilling the description; never a silent jump to the launcher (Shell.vue:52-54).
- **Unsupported:** password → Unlock PDF (today "unsupported file", views.py:407); signed → ask for an unsigned copy; scan → Make text editable; pdf.js failure → text tools off, with the reason.

## 8. Accessibility

WCAG 2.2 AA: a button path for every drag (2.5.7), 44 px targets, keyboard placement (today pointer-only, MarkLayer.vue:69-83), switchable single-key shortcuts (2.1.4), a ≥3:1 ring (today ~1.1:1 in dark theme, dw/app/assets/css/extended.css:1012-1019), reduced motion (Shell.vue:148), text ≥13 px. Test NVDA (Russian) and VoiceOver in ru and uz.

## 9. Acceptance criteria

Baseline: 30 days of editor.visual errors by code and command, and quote-to-job drop-off (services.py:224,279). Test five first-time users per persona in Telegram (iPhone 11; 2 GB Android; 4G and 750 kbps/300 ms 3G; current and oldest supported Telegram) and load-test N concurrent users.

- T1: 4 of 5 within budget; refusals shown before typing; longer names never collide.
- T2: ink visible before sending; scrolling never marks; no drag needed below Bot API 7.7.
- T3: pictures on every slide within 3 taps, no AI edit; untouched slides keep theirs; in a month, half of picture requests done here.
- T4: no AI edit; rendered slide p50 ≤2 s, p95 ≤5 s; nothing cut silently; a title edit moves no other slide; Cyrillic in Uzbek decks never fails a send.
- T5: PDF in chat ≤20 s; deck with new pictures ≤90 s, progress shown; on Free, one file task per draft.
- T6–T10: hidden text unextractable, other pages keep their text; page delete plus signature is one task, marks keep their page; cover and quiz fixed, moves need no drag; AI cost before every confirm, redesign without AI edits; fields filled by tapping (R3).
- All: no banned words in three languages; 1,500 Cyrillic characters send; closing never loses work.

## 10. Open questions for the UI design stage

1. How often does PdfCraft accept our ReportLab AI PDFs (TrueType subsets, rendering.py:355)? That sets their default text path.
2. Confirm one file task per deck draft at any slide count (slides.py:13-15 billed by slides).
3. Is a signature image biometric data under the amended law?
4. Should a send restart the 24 hours for file and sections (dw/docs/product/UI_UX_SPEC.md:173)?
5. Caladea’s Cyrillic coverage is disputed (https://en.wikipedia.org/wiki/Cambria_(typeface)); fallback heading font?
6. Cap Add to all slides on Free, given its model calls?
7. Oldest supported Telegram version, from users’ WebApp.version?

Settled here: black-out label (§6), contract digits and image cost (§3), deck preview (§5).

## Declined

None; all six minor issues are applied.