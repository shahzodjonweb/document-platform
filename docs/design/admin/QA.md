# Staff visual / interaction QA

2026-09-22. Flow and wireframe design preceded the templates in `interaction-design.md`. Real server-rendered views use the shared ivory/forest/sage direction and locally vendored DM Sans/Manrope fonts with their OFL notices.

- Actual overview captured in English, Uzbek Latin and Russian at 1440 and 390 px. Russian headings wrap; no main document overflow. Tables scroll within labeled regions. Mobile navigation scrolls horizontally.
- Metadata font sizes and muted colors were increased after independent axe findings. Rechecked at desktop/mobile: zero detected WCAG 2 A/AA violations on overview.
- Actual local account/job facts produce measured numbers; production default excludes test records. Missing denominator shows a dash with explanation. Unimplemented financial metrics show an explicit unavailable integration state.
- Labels, values, chart data-table alternative, filter persistence, CSV export and readable staff role/realm have automated tests. Statuses are localized; tool IDs remain stable metadata.
- No staff content-download action or generic customer impersonation exists. Staff forms require CSRF, role checks and an audit reason.

`npm run test:browser` reproduces the two browser tests and six locale/viewport screenshots. This is a local light-theme review. A complete staff dark-theme design, deeper accessibility audit and real-device triage review remain later UX work; the customer app already supports both themes.
