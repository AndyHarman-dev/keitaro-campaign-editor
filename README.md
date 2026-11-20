# Keitaro Campaign Editor

A local web app for creating Keitaro campaigns and editing the offers inside their flows,
with a staged **fetch → edit → push** workflow, share pinning, and recovery of offers that
were removed directly in Keitaro.

- **Campaigns screen**: search existing campaigns, or create one from a name, one or more
  GEOs and an offer. The campaign gets the preset domain / group / traffic source and two
  flows: *Flow 1* (forced) sends the chosen countries to google.com, *Flow 2* (regular) sends
  everyone else to the offer at 100 %.
- **Editor**: offers grouped by flow. Remove, Bring back, Add, edit a share inline (Enter or
  leaving the field applies it; Escape cancels) and pin shares. Nothing is written to
  Keitaro until you **Push**; **Cancel** discards pending edits. Push is refused if the flow
  changed in Keitaro since your last fetch; **Fetch & merge** pulls Keitaro's version and keeps
  your edits on top.

Product decisions and the verified Keitaro API behaviour: [`.claude/vision/campaign_editor.md`](.claude/vision/campaign_editor.md).
Domain vocabulary: [`docs/glossary.md`](docs/glossary.md).

## Requirements

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- A Keitaro tracker and an Admin API key (or none at all, with the fake tracker below)

## Setup

```bash
cp .env.example .env          # fill in KEITARO_BASE_URL, KEITARO_API_KEY and the defaults
cd backend && uv sync && uv run alembic upgrade head && cd ..
cd frontend && npm ci && cd ..
```

`.env` is gitignored. The API key is read only by the backend: it is sent to Keitaro in the
`Api-Key` header and is never logged, returned by the API, or exposed to the browser.

`KEITARO_DEFAULT_DOMAIN`, `KEITARO_DEFAULT_GROUP` and `KEITARO_DEFAULT_SOURCE` are names as
shown in Keitaro. The create form pre-selects them and lets you override each one under
*Advanced*; problems (unset or not found) are shown on the form.

## Database migrations

The schema is managed by Alembic; the app never creates tables itself, so run migrations
before the first start and after every pull that adds a file under `backend/migrations/versions/`.
Alembic uses the same `DATABASE_URL` as the app (from `.env`; default `<repo>/data/app.db`).
Run these from `backend/`:

```bash
uv run alembic upgrade head      # apply all pending migrations
uv run alembic current           # show the revision the database is at
uv run alembic history           # list all revisions
uv run alembic downgrade -1      # undo the latest migration
```

To target another database, prefix the command, e.g.
`DATABASE_URL=sqlite:////tmp/kce-demo.db uv run alembic upgrade head`.

**Changing the schema**: edit the models in `backend/app/db/models.py`, then

```bash
uv run alembic revision --autogenerate -m "short description"   # writes a new file in migrations/versions/
uv run alembic upgrade head
uv run alembic check             # "No new upgrade operations detected" = models and migrations agree
```

Read the generated file before committing it: autogenerate misses some changes (renames,
for example, come out as drop + add). The e2e configs (`npm run e2e`, `npm run e2e:live`)
recreate their own database and run `alembic upgrade head` themselves.

## Run

**Development** (hot reload on both sides):

```bash
cd backend && uv run uvicorn app.main:app --reload        # API on :8000
cd frontend && npm run dev                                # UI on :5173, proxies /api to :8000
```

**Production-style** (FastAPI serves the built UI):

```bash
cd frontend && npm run build && cd ../backend
uv run uvicorn app.main:app                               # open http://127.0.0.1:8000
```

Connectivity check: `http://127.0.0.1:8000/api/keitaro/ping`.

## Run on the fake tracker

`KEITARO_FAKE=1` swaps Keitaro for an in-process fake, so no tracker or API key is needed. Use it
to try what a real key may not allow, such as share edits across several offers.

Terminal 1, from the repo root (backend on the fake, with its own database `data/fake.db` and
the fake's data in `data/fake-keitaro.json`):

```bash
cd backend && mkdir -p ../data && export KEITARO_FAKE=1 DATABASE_URL="sqlite:///$(cd .. && pwd)/data/fake.db" KEITARO_FAKE_STATE="$(cd .. && pwd)/data/fake-keitaro.json" && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
```

Terminal 2, from the repo root:

```bash
cd frontend && npm run dev                                # open http://localhost:5173
```

What the fake holds:

- Five offers to pick from: Flexacil PE, Oxys BE, Joint Rx RO, Oxys [BEAUTY-CL-BE], Cardio Fresh CZ.
- **Demo campaign** (#1000): Flow 1 (forced, AU → google.com) and Flow 2 with three offers at
  34 / 33 / 33.
- Domain, group and source use the names from `.env` (or placeholders when unset). Nothing
  reaches a real tracker.

Keep in mind:

- **The fake's data is saved in `data/fake-keitaro.json`** (set by `KEITARO_FAKE_STATE`). It is
  written after every change (create, push, archive, the controls below) and loaded on start, so
  campaigns you create survive restarts, including `--reload` restarts. If the file is missing,
  the fake starts from the demo data and creates it.
- **Start over** by stopping the backend and deleting both files, then running the command again:
  `rm data/fake.db data/fake-keitaro.json`. Delete them together: the database remembers flows
  the JSON file holds.
- Without `KEITARO_FAKE_STATE` the fake lives in memory only and starts from the demo data every
  time (the e2e tests run that way). Your real `data/app.db` is never touched.

Simulate someone editing Keitaro directly (these endpoints exist only in fake mode):

```bash
# list a campaign's flow ids
curl -s localhost:8000/api/campaigns/1000/editor | python3 -c 'import json,sys; [print(f["stream_id"], f["name"]) for f in json.load(sys.stdin)["flows"]]'
curl -X POST localhost:8000/api/_fake/streams/1002/detach/3717    # remove an offer from a flow
curl -X POST localhost:8000/api/_fake/offers/3717/archive         # archive an offer
```

After a detach, Push is blocked until you Fetch & merge. Fetch shows the offer as "removed in
Keitaro" and, because Keitaro's remaining shares no longer total 100, stages a rebalance: the
unpinned offers take up the freed share (pins stay) as a pending change that Push saves. After an
archive, Fetch tags the row "archived in Keitaro".

## Stats & trends (beta)

Each offer row can show its numbers from Keitaro's reports and a week-over-week trend. This is a
**beta**, off unless you start the app with the flag:

```bash
cd backend && uv run python -m app --stats-beta --reload      # any uvicorn option works after it
# or: STATS_BETA=1 uv run uvicorn app.main:app --reload
```

Without the flag the editor looks exactly as before: the Stats and Trends columns show `—` and
the app never asks Keitaro for a report. Two more settings live in `.env`:
`STATS_TIMEZONE` (default `UTC`, the timezone report days follow) and `STATS_CURRENCY`
(default `$`).

What the numbers mean (full definitions and the reasoning: `.claude/vision/stats_trends.md`):

- **EPC** = (lead + sale revenue) ÷ clicks; **CR** = (leads + sales) ÷ clicks, Keitaro's own
  conversions. Every number is summed first and divided once.
- **Periods:** Today is the partial current day; 7 / 14 / 30 days are complete days ending
  yesterday. "% still pending" says how much is undecided, since leads turn into sales or
  rejections over the next days.
- **Trend:** EPC over days −9…−3 against the week before (days −16…−10), so both weeks have
  settled. A change smaller than the noise band (2 × √(1/c₁ + 1/c₂), c = each week's
  conversions) reads **within noise**; a week under 100 clicks or with no conversions reads
  *Not enough traffic*.
- **Flow totals** cover every report row of the flow over the period, including clicks that
  reached no offer and offers no longer in the flow, so they describe history, not your edits.

**Within noise is the feature working.** At about 80 conversions a week the band is roughly
±30 %, so most trends read "within noise". In the fake's demo campaign, Oxys BE (3717) drops
about 16 % week over week, which looks alarming, and the screen declines to flag it because a
change that size happens by chance at that volume. Flexacil PE (3749) rises far beyond its band
and gets a real ▲.

### Fake traffic

In fake mode the demo campaign gets 30 days of seeded traffic ending today, regenerated on every
start. These controls exist only in fake mode and clear the stats cache:

```bash
# a week of traffic for campaign 1000 (offers split by the current shares)
curl -X POST localhost:8000/api/_fake/traffic -H 'Content-Type: application/json' \
  -d '{"campaign_id": 1000, "days": 7, "clicks_per_day": 1000, "drift": {"3717": -0.4}}'
# how an offer converts: chance of any postback, share approved, payout
curl -X PUT localhost:8000/api/_fake/offers/3717/profile -H 'Content-Type: application/json' \
  -d '{"cr_all": 0.05, "approve": 0.6, "payout": "20"}'
curl -X DELETE 'localhost:8000/api/_fake/traffic?campaign_id=1000'   # no traffic at all
curl -X POST localhost:8000/api/_fake/fail-next -H 'Content-Type: application/json' \
  -d '{"status": 503}'                                                  # the next report fails
```

`drift` is a weekly change (−0.4 = 40 % lower a week later); `lag` (default on) leaves recent
postbacks pending the way a real network does.

## Tests and quality gates

```bash
cd backend && uv run pytest            # backend, offline (FakeKeitaro + temp SQLite)
cd frontend && npm test                # frontend unit/behaviour tests (Vitest)
cd frontend && npm run e2e             # Playwright, built app on the fake tracker
scripts/check.sh                       # ruff, tsc, eslint, tests, CRAP, duplication, mutation
scripts/check.sh --fast                # the same without mutation testing
```

`scripts/check.sh` needs the `crapper`, `dryer` and `mutator` tools on `PATH`.

**CI** (`.github/workflows/ci.yml`) runs on every pull request and every push to `main`:
`scripts/check.sh --fast`, `alembic check` and the Playwright suite on the fake tracker. A
nightly run adds mutation testing (the full `scripts/check.sh`). It uses no secrets and never
talks to a real Keitaro. The tools are cloned from their public repos at pinned commits.

**Opt-in live contract checks** prove the fake still matches the real tracker:

```bash
cd backend && uv run pytest -m live
```

They create one throwaway campaign per test with your `.env` defaults, work only inside it,
and archive it at the end. They are never part of a default run.

**Opt-in browser session on the real tracker** (`cd frontend && npm run e2e:live`) drives the
built UI against your `.env`: create a `kce-ui-check-…` campaign, pin and push, fetch, and
(when the key sees two or more offers) add, re-share, remove and push again. It archives that
one campaign at the end and refuses to archive anything with another name. Screenshots,
video and trace land in `frontend/test-results/live/` (gitignored).

## Safety rules

- The app never calls Keitaro's `clean_archive` endpoints: they permanently empty the archive
  of the **whole tracker**. The client refuses such paths before any request is made.
- Keitaro's flow update replaces the **whole** offer list. Every push therefore sends the
  complete list, including offers this API key cannot read (shown as "no access to this
  offer"), each with its original state, and only after the shares are checked to total 100.
- The tracker may be shared. The app writes only to campaigns it created or that you opened
  in the editor.
- The API answers only on `localhost` / `127.0.0.1` and refuses writes whose `Origin` is another
  site, so a web page open in the same browser cannot drive it (DNS rebinding, cross-site POST).
  Requests without an `Origin` header, such as `curl`, still work. To use the app from another
  device, add its address to `ALLOWED_HOSTS` (see `.env.example`).

## Layout

```
backend/app/domain/    pure rules: shares, pins, staged ops, fetch merge, push plan
backend/app/keitaro/   typed Admin API client, response schemas, FakeKeitaro, demo seed
backend/app/db/        SQLAlchemy models, repository (optimistic versions), JSON codec
backend/app/services/  campaign create saga, editor use cases (fetch/ops/push/cancel)
backend/app/api/       FastAPI routers, request/response models, view building, errors
frontend/src/          React + TS; API types generated from OpenAPI (`npm run gen:api`)
frontend/e2e/          Playwright specs
```

## License

Proprietary — all rights reserved. See [LICENSE](LICENSE).
