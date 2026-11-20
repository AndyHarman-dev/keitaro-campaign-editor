# Keitaro Campaign Editor — project rules

Product vision, decisions and verified API behaviour: `.claude/vision/campaign_editor.md`.

## Keitaro API safety

- **Never call Keitaro's "clean archive" actions** (`POST /campaigns/clean_archive`,
  `POST /offers/clean_archive`, or any other `*/clean_archive` endpoint). They permanently
  empty the archive for the **whole tracker**, not just our campaigns, and cannot be undone.
  This applies to app code, tests, scripts, and ad-hoc probes alike.
- The tracker is shared with other users. Write only to campaigns this app created or the user
  opened in the editor. Never archive, edit or delete anything else.
- The API key never leaves the backend and is never printed or logged. It lives only in the
  gitignored `.env`.

## Terminology

- Prose and UI say **flow**. **Stream** appears only where we quote the API (`/streams`,
  `stream_id`) and in the backend code that maps it.
