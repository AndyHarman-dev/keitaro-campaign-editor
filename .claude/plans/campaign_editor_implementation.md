---
status: InProgress
---

# Implementation plan — Keitaro Campaign Editor

What we build and why: [`.claude/vision/campaign_editor.md`](../vision/campaign_editor.md)
(locked). This plan says **how**, in phases that each end in a check you can run.
Working mode: **ub-mode**. Make it work (TDD, smallest edit), then make it right (crapper,
dryer, mutator), and follow practice (log, small commits).

---

## 0. Context

### Where the repo is today (`chore/scaffold`)

- **Backend skeleton (FastAPI):**
  - `app/config.py`: pydantic-settings reads the gitignored `.env`.
  - `app/keitaro/client.py`: a thin httpx client with only `get`.
  - `app/main.py`: `/api/health` and `/api/keitaro/ping`.
  - `app/db/session.py`: engine and `Base`. There are no models yet.
  - Alembic is initialised but has no revisions. There is one test, `test_health`.
- **Frontend:** none yet.
- **Settled:** the live API behaviour we depend on (vision §4) and every product decision
  (vision §5). No open questions remain.
- **Design reference:** the prototype at <https://claude.ai/artifact/LfS4PMzD6co4FU84iK22kL>.
  It is a reference only. Its source lives in a gitignored folder, and no phase depends on
  reading those files. Where the prototype and the vision disagree, the vision wins.

### Branching

- The implementation branch is `feat/campaign-editor`, created from `chore/scaffold`.
  `main` does not have the scaffold yet.
- Every phase commits and pushes **that branch**.
- Merging into `chore/scaffold` or `main` happens **only after explicit approval**. This
  overrides ub-mode's "push to the main line at the end".

### Parity gate

Not applicable. This is greenfield work and nothing existing is replaced or deleted.

`/api/keitaro/ping` and `KeitaroClient.get` stay and are extended, never swapped out. If a
phase ends up replacing either one, it first pins today's observable output with a test, so
the key-missing and reachable/unreachable responses stay the same.

---

## 1. Decisions locked

These are planning decisions that come from the vision. Changing one means editing this
plan, not drifting in code.

1. **Share allocation lives in one place: the Python domain core.**
   - The frontend never computes shares. It sends intents (remove, add, set share, pin…)
     and renders the flow view the backend returns.
   - The prototype's JS `rebalance` is not ported.
2. **The editor state is `base + pending ops`.** The working copy is never stored on its own.
   - `base` holds what Keitaro had at the last fetch or push, plus local-only memory: pins,
     remembered offers, and the archived flag.
   - `pending` is an ordered list of user operations.
   - `working = replay(base, pending)`, a pure function.
   - **Cancel** clears `pending`. **Dirty** means `working ≠ base`.
   - **Fetch** builds a new base and replays the same pending ops on top of it. That is
     how "your pending edits stay on top" becomes literal (vision §5, "Push conflict").
3. **Shares are stored, then rebalanced on every local change.**
   - Keitaro's fetched shares (for example 50/25/25) are shown as they are.
   - Any local operation rebalances the unpinned rows: equal split, with the remainder going
     to the first unpinned rows in Keitaro's order.
   - When pins do not fit, auto-unpin releases the oldest pin first.
   - Removed rows are always at 0 %.
4. **Pins are local only.** A pin is `(share, seq)`, where `seq` is a per-flow counter that
   orders pins by age. A removed pinned row keeps a *dormant* pin that comes back on Bring
   back.
5. **Offers are keyed by `offer_id`, never by link `id`.** A re-added offer gets a new link
   id in Keitaro (vision §4).
6. **Push sends the complete list, safely.** `PUT /streams/{id}` with `offers` replaces
   every offer in the flow. The payload therefore:
   - carries every active row, including offers this key cannot read (403, shown as `[id]`);
   - keeps each offer's original `state`;
   - sums to exactly 100, checked before the HTTP call;
   - is sent only after a fresh re-read of the flow matches the signature from our last
     fetch. Otherwise the server answers **409**, and Fetch is required (vision §5).
7. **Push is idempotent by construction.** After a successful PUT the flow is re-read and
   becomes the new base.
   - If the app crashes between the PUT and the database commit, the next Push sees a
     signature mismatch and asks for a Fetch.
   - That Fetch replays the pending ops onto a Keitaro state that already contains them, so
     `working = base` and the flow comes up clean.
8. **Campaign create is a saga with compensation.** The steps are: create the campaign, then
   the forced flow (position 1), then the offer flow (position 2).
   - If a flow fails, the half-made campaign is archived (`DELETE /campaigns/{id}`).
   - Each request carries a client-generated idempotency key. A double submit returns the
     campaign that was already created.
9. **Parse at the boundary.** Every Keitaro response is parsed into pydantic models in
   `app/keitaro/`. The domain and service code trust those types.
10. **API types are generated, not hand-written twice.** The TS client types come from
    FastAPI's OpenAPI schema (`openapi-typescript`). The pydantic schemas are the only
    definition.
11. **The clean_archive ban is enforced in code.**
    - `KeitaroClient` refuses any path that ends in `clean_archive`, before any I/O, and a
      test covers it.
    - `GET /campaigns/deleted` is never used. It is slow and not needed.
12. **Tests never touch the live tracker by default.** All automated tests run against
    `FakeKeitaro`, an in-process model of the verified behaviour.
    - Live contract checks are opt-in (`pytest -m live`).
    - They work only on a throwaway campaign they create in the default group from `.env`,
      and they archive it afterwards.
13. **Archived-offer detection is an assumption, not observed behaviour.**
    - We could not archive an offer to see how it shows up, because offers are read-only for
      this key.
    - The rule we assume: an offer is *archived in Keitaro* when its id appears in
      `GET /offers/deleted`.
    - An offer the key simply cannot read (403) is **not** treated as archived.
    - See the Phase 3 tripwire.
14. **Single writer per flow.** Only `FlowService` writes flow rows. Each flow row has a
    `version`, and every mutating request carries the version it saw. A mismatch (for
    example, two tabs open) returns **409** instead of a lost update.

### Glossary

The glossary lives in `docs/glossary.md`, created in Phase 0.

| Term | Meaning |
|---|---|
| Flow | Keitaro's routing rule (the API calls it **stream**). |
| Offer row | One offer inside one flow, as the editor sees it. |
| Base | Keitaro's state at the last fetch or push, plus local memory. |
| Pending op | A staged user action that has not been pushed. |
| Working | `replay(base, pending)`, the state the editor shows. |
| Signature | The ordered list of `(offer_id, share, state)` from Keitaro, used for conflict checks. |
| Removed | A row at 0 % that is not sent on push. It is either *removed locally* or *removed in Keitaro*. |
| Archived | The offer itself is archived or deleted in Keitaro. It cannot be restored, and Remove forgets it. |
| Pin / dormant pin | A frozen share. A pin goes dormant while its row is removed. |

---

## 2. Target architecture

```
frontend/ (React + Vite + TS)            backend/app/
  api/ generated types + fetch wrapper     domain/      pure: models, allocate, ops, merge, push_plan
  screens/ Campaigns, Editor               keitaro/     client (deny-list), schemas (boundary parse), fake
  components/ ShareField, OfferRow, …      db/          SQLAlchemy models, repository (version check)
                                           services/    CampaignService (create saga), FlowService
                                           api/         routers: campaigns, flows, offers, lookups
```

**Data shapes (domain, frozen dataclasses or pydantic):**

```python
class RowStatus(StrEnum): ACTIVE = "active"; REMOVED = "removed"
class RemovedBy(StrEnum): LOCAL = "local"; KEITARO = "keitaro"

@dataclass(frozen=True)
class Pin:            share: int; seq: int

@dataclass(frozen=True)
class OfferRow:
    offer_id: int
    status: RowStatus
    share: int                    # 0 when REMOVED (enforced in __post_init__)
    kt_state: str                 # Keitaro's offer-link state, sent back unchanged
    pin: Pin | None               # dormant while REMOVED
    removed_by: RemovedBy | None  # set iff REMOVED
    archived: bool                # archived in Keitaro → no Bring back

@dataclass(frozen=True)
class FlowState:  rows: tuple[OfferRow, ...]; next_pin_seq: int

Op = Remove | BringBack | Add | SetShare | TogglePin   # tagged union, each carries offer_id
```

**Pure functions (the whole business logic):**

- `rebalance(rows) -> (rows, notes)`
- `apply(state, op) -> (state, notes)`
- `replay(base, ops) -> (state, notes)`
- `merge_fetch(old_base, kt_offers, archived_ids) -> (new_base, notes)`
- `diff(base, working) -> FlowDiff`
- `push_plan(working) -> list[KtOfferLink]`, which raises if the shares are invalid

**Database (one Alembic revision to start):**

- `flows`
  - `stream_id` (PK), `campaign_id`, `name`, `type`, `position`, `summary`
    (for flows without offers, e.g. "forced · country in AU → https://google.com")
  - `base` (JSON), `pending` (JSON), `kt_signature` (JSON), `fetched_at`, `version`
- `created_campaigns`: `idempotency_key` (PK), `campaign_id`, `created_at`. It also records
  which campaigns this app created.

---

## 3. Phases

Every phase has the same exit checks:

- **Make it work:** the tests listed in the phase were written failing first, and now pass.
- **Make it right:**
  - `ruff check` passes.
  - `crapper --changed --threshold 10` passes. Coverage comes from coverage.py LCOV through
    `pytest-cov` for Python, and from Vitest for TS.
  - `dryer --changed` reports no pair at ≥ 0.8.
  - `mutator --changed` has no survivors in `domain/`, `keitaro/` and `services/`. Elsewhere,
    each survivor is killed or justified in the change log.
- **Practice:**
  - One or more small commits that say why, what changed and how it was proven.
  - Push `feat/campaign-editor`.
  - Add a change-log entry.

---

### Phase 0: Tooling, glossary, branch

**Model: Sonnet 5.** Mechanical setup with no design decisions. The checks below fail loudly
if anything is wrong.

- **Current State:**
  - No `pytest-cov`, so crapper and mutator get no Python coverage.
  - `.metrics/` and `target/` are not ignored.
  - There is no single command that runs all the checks, and no glossary.
- **Desired State:**
  - `feat/campaign-editor` exists.
  - `make check` (or `scripts/check.sh`) runs ruff, pytest with LCOV, crapper, dryer and
    mutator for the backend. It is extended to the frontend in Phase 5.
  - `docs/glossary.md` exists.
- **Problems:** The gates in the exit checks cannot run yet.
- **Solutions:**
  1. Run `git checkout -b feat/campaign-editor chore/scaffold`.
  2. Add `pytest-cov` to the dev group. Configure `--cov=app --cov-report=lcov`.
  3. Add `.metrics/`, `target/`, `coverage/`, `lcov.info` and `frontend/dist/` to `.gitignore`.
  4. Write `scripts/check.sh`, running from the repo root.
  5. Write `docs/glossary.md` from the table in §1.
  6. Run crapper, dryer and mutator once on the scaffold to record the baseline.
- **Verify:** `scripts/check.sh` passes on the scaffold, and crapper prints scores *with*
  coverage (not N/A).

### Phase 1: Domain core, part A (allocation and operations)

**Model: Sonnet 5.** Every rule has a numeric example in the vision. Table-driven tests
pin each one, so a wrong implementation fails loudly. The module is pure, with no I/O.

- **Current State:** No domain code.
- **Desired State:**
  - `app/domain/flow.py` holds `OfferRow`, `FlowState`, `Pin` and the `Op` union, plus
    `rebalance`, `apply`, `replay`, `diff` and `push_plan`.
  - Illegal states cannot be constructed:
    - a removed row with share > 0
    - an active row with a `removed_by`
    - a pin share outside 0..100
- **Problems:** None yet. This phase is the foundation every later phase builds on, so it
  goes first.
- **Solutions:** TDD in this order, with one test table per rule. These are the examples
  from vision §2 and §5:

  | Case | Input | Expected |
  |---|---|---|
  | Equal split | 3 active, no pins | 34/33/33 |
  | Remainder after a pin | pin 25, 2 free over 75 | 38/37, in Keitaro order |
  | Remove with a pin | 4×25, pin one, remove one | 25 pinned, 38/37 |
  | Inline edit auto-pins | set 3717 → 50 | 3717 pinned at 50, others split 50 |
  | Auto-unpin | pins 60 (older) + 50 | 60 is released, so 25/50P/25 |
  | Everything pinned, ≠ 100 | all pinned, sum 90 | oldest pin released |
  | Pinned remove → Bring back | 34/33/33, pin first, remove, bring back | 50/50, then 34P/33/33 |
  | Bring back no longer fits | dormant pin 60, others pinned 50 since | auto-unpin oldest |
  | Add | append offer | goes to the end, rebalanced |
  | Archived row | Bring back | refused (operation invalid) |
  | `push_plan` | removed rows | excluded, sum = 100, `kt_state` kept |
  | `push_plan` | sum ≠ 100 or 0 active | raises `InvalidPush` |
  | `diff` | replay of a cancelled pair (remove + bring back) | not dirty |

  - Notes such as "Auto-unpinned [3749]…" are returned values, never side effects.
- **Verify:**
  - The tables pass.
  - mutator has zero survivors in `domain/flow.py`.
  - crapper is under 10 for every function.

### Phase 2: Domain core, part B (fetch merge with pending ops on top)

**Model: Opus 5.** The vision says "pending edits stay on top", but it does not define what
that means in each edge case. This is the one remaining design decision. A plausible but
wrong merge passes casual testing and silently loses edits or offers.

**Escalate/stop if:** a case below has no answer that agrees with vision §5. Bring the
case to the user; don't pick one.

- **Current State:** `replay` exists (Phase 1), and `merge_fetch` does not.
- **Desired State:** `merge_fetch(old_base, kt_offers, archived_ids)` builds the new base.
  `replay(new_base, pending)` then yields the working copy. Every op is *total*: when its
  target no longer applies, the op becomes a no-op and returns a note. It never raises.
- **Problems:** The merge has to be defined case by case, below.
- **Solutions:** Table-driven tests first. Proposed rules, each pinned by a test:

  | Case | Rule |
  |---|---|
  | Offer in Keitaro, not in the old base | New active row at its Keitaro position and share. |
  | Offer in the old base, gone from Keitaro | Kept as `REMOVED`, `removed_by = KEITARO`, share 0, last-known `kt_state` kept (for Bring back). |
  | Removed offer id in `archived_ids` | `archived = True`. Bring back becomes impossible; Remove forgets it. |
  | Keitaro order changed | New base follows Keitaro's order. Rows Keitaro removed keep their old relative place after their predecessor. |
  | Pinned offer whose share changed in Keitaro | Keitaro wins: the share is the Keitaro value, and the pin stays at that value with the same seq. |
  | Pending Remove of an offer Keitaro already removed | No-op, with a note. |
  | Pending Add of an offer Keitaro already added | No-op, with a note. The row is active from the base. |
  | Pending SetShare on an offer Keitaro removed | No-op, with a note. The edit is not resurrected. |
  | Pending BringBack of an offer now archived | No-op, with a note "archived in Keitaro · can't be restored". |
  | Pending ops that now equal Keitaro (post-crash replay) | `diff` is empty, so the flow is clean (decision 7). |
  | Forget archived (Remove on an archived row) | A **direct base edit**, not a pending op. The row is dropped from the base, nothing is sent, and the change is local only. |

  - `kt_signature` is computed from `kt_offers` here, as a pure function.
- **Verify:**
  - The table passes.
  - A property test (hypothesis) checks that for random bases and op sequences,
    `replay` keeps Σ active = 100 (or 0 active rows) and never yields a removed row with a
    non-zero share.
  - mutator has zero survivors.

### Phase 3: Keitaro gateway and FakeKeitaro

**Model: Sonnet 5.** The endpoints and payload shapes are verified in vision §4, so this is
mostly transcription. The fake is checked against the live tracker by opt-in contract tests.

**Escalate/stop if:** the opt-in contract check finds that an archived offer shows up some
way other than through `/offers/deleted` (decision 13). The merge rule from Phase 2 then
needs revisiting with the user.

- **Current State:** `KeitaroClient.get` returns raw `httpx.Response`. There is no write
  support, no parsing and no fake.
- **Desired State:**
  - **`app/keitaro/schemas.py`:** pydantic models for the responses we read: Campaign, Stream
    (offers, filters, `action_payload` *or* `action_options.url`), Offer, Domain, Group,
    TrafficSource. Unknown fields are ignored.
  - **`app/keitaro/client.py`:** typed methods:
    - `list_campaigns`, `get_campaign`, `create_campaign`, `archive_campaign`
    - `list_streams(campaign_id)`, `get_stream`, `create_stream`, `put_stream_offers`
    - `list_offers`, `list_deleted_offers`
    - `list_domains`, `list_groups(type="campaigns")`, `list_traffic_sources`

    Errors map to `KeitaroError(status, message)`. The key is never logged, and errors
    contain no headers. A deny-list guard rejects `*clean_archive` paths.
  - **`app/keitaro/fake.py`:** `FakeKeitaro`, an ASGI app mounted on an `httpx.MockTransport`.
    It reproduces:
    - PUT `offers` replaces the whole list;
    - a re-added offer gets a new link id;
    - PUT without `offers` keeps them;
    - no share validation;
    - DELETE archives (GET → 404);
    - offers this key cannot read → 403;
    - `/offers/deleted`.
- **Problems:**
  - Raw responses leak into callers.
  - There is no way to test services without the network.
- **Solutions:**
  - Unit tests drive the client against the fake (round trips).
  - A test asserts the clean_archive guard fires before any request.
  - A test asserts the API key never appears in `repr`/`str` of a `KeitaroError` or a log
    record.
  - `tests/live/test_contract.py`, marked `live` and skipped by default, runs one check
    sequence against the real tracker:
    1. create a throwaway campaign in the default group from `.env`
    2. create both flows
    3. replace the offers
    4. assert the same observations the fake encodes
    5. archive the campaign

    It never reads `/campaigns/deleted`.
- **Verify:**
  - Default `pytest` passes offline.
  - `pytest -m live` passes once, run by the user's choice, and the throwaway campaign is
    archived afterwards.

### Phase 4: Persistence

**Model: Sonnet 5.** A standard SQLAlchemy and Alembic pattern on SQLite. The repository
tests catch any serialisation mistake.

- **Current State:** `Base` exists. There are no models and no revisions. `data/app.db`
  exists but is empty.
- **Desired State:**
  - `app/db/models.py` defines `flows` and `created_campaigns` (shapes in §2).
  - There is a first Alembic revision.
  - `FlowRepository` provides `load(stream_id)` and `save(flow, expected_version)`. `save`
    raises `StaleVersion` on a mismatch.
  - JSON (de)serialisation of `FlowState` and `Op` lives in one module.
- **Problems:** There is nowhere to keep pins, pending ops and remembered offers.
- **Solutions:**
  - TDD on the repository with a temporary SQLite file:
    - a round trip keeps every field;
    - the version increments on save;
    - a stale save raises.
  - Run `alembic upgrade head` on an empty database in a test.
- **Verify:** The tests pass, and `uv run alembic upgrade head` works on a fresh `data/app.db`.

### Phase 5: Read side, campaign create, and HTTP API

**Model: Sonnet 5.** Wiring between tested pieces. The create saga's failure paths are
explicit test cases against the fake.

- **Current State:** There is only `/api/health` and `/api/keitaro/ping`.
- **Desired State:**
  - **Endpoints** (pydantic request and response models):
    - `GET /api/campaigns?q=`
    - `GET /api/lookups`: domains, groups and sources, with the `.env` defaults resolved by
      name to ids.
    - `GET /api/offers?q=`: visible offers, cached in memory for 60 s, plus an "in flow"
      marker when given `stream_id`.
    - `POST /api/campaigns`, taking name, GEOs, offer_id, optional domain/group/source
      overrides, and an idempotency key.
  - **`CampaignService.create` runs the saga** (decision 8):
    - GEOs are validated as ISO-2 codes, uppercased, at least one.
    - The alias is a random URL-safe token.
    - The forced flow is `schema: redirect`, `action_type: http`, with `action_payload`
      set to `https://google.com` and a `country` accept filter.
    - The offer flow is `schema: landings`, `action_type: http`, with `[{offer_id, share:
      100, state: active}]`.
  - **Wiring:**
    - The FastAPI dependency for `KeitaroClient` comes from settings; tests override it with
      the fake.
    - The frontend scaffold is created here: `frontend/` with Vite + React + TS, Vitest, and
      `npm run gen:api` (openapi-typescript).
    - `scripts/check.sh` is extended to the frontend: tsc, eslint, vitest with coverage, and
      crapper, dryer and mutator on `frontend/src`.
- **Problems:** Nothing can be created or listed yet.
- **Solutions:** API tests through `TestClient`, with the fake injected:
  - create succeeds, and the fake holds exactly two flows of the right shape;
  - forced-flow creation fails, so the campaign is archived in the fake and the API returns
    the error from design state D;
  - a double submit with the same key returns the same campaign and creates nothing new;
  - an invalid GEO gives 422 and makes no Keitaro call;
  - a missing `.env` default makes lookups report it as "not set" rather than crash.
- **Verify:** The API tests pass, and `npm run gen:api && npm run build` succeeds.

### Phase 6: Editor service (fetch, ops, push, cancel)

**Model: Opus 5.** This is the only code that writes offer lists to a shared tracker, and
a full-list replace means one bug silently detaches offers for everyone. Correctness spans
the domain, the repository and the client at once: signature check, version check, and
re-read after the PUT.

**Escalate/stop if:** the post-PUT re-read ever differs from the pushed plan in the fake or
in the live check. That would mean Keitaro normalises something (state, order) that our
signature has to account for.

- **Current State:** The domain, client and repository exist separately. There is no
  editor API.
- **Desired State:**
  - **`FlowService`:**
    - `open(campaign_id)`: first open = fetch.
    - `fetch(campaign_id)`: `merge_fetch` + `replay`, stores the new base, signature and
      `fetched_at`. Pending ops are kept.
    - `apply_op(stream_id, op, version)`: appends to `pending` (or edits the base directly
      to forget an archived row).
    - `cancel(stream_id | all)`.
    - `push(stream_id | all)`:
      1. re-read the stream
      2. compare signatures, 409 on mismatch
      3. `push_plan`
      4. PUT
      5. re-read
      6. new base and empty pending, in one transaction
  - **Endpoints:**
    - `GET /api/campaigns/{id}/editor` returns a `FlowView` DTO per flow: rows with name or
      null, share, pinned, status tags, dirty, pending count. Flows without offers come as
      name + summary.
    - `POST /api/campaigns/{id}/fetch`
    - `POST /api/flows/{stream_id}/ops`
    - `POST /api/flows/{stream_id}/push`
    - `POST /api/flows/{stream_id}/cancel`
    - the "all" variants of push and cancel
- **Problems:** Without this, the editor cannot fetch, stage edits or push.
- **Solutions:** Behaviour tests through the API against the fake:
  - **Unreadable offer kept.** A flow holds an offer this key gets 403 for. Remove a
    *different* offer and push. The unreadable offer is still attached in the fake, with
    its original `state`.
  - **External removal.** Remove an offer directly in the fake, then fetch. The row comes
    back `removed by Keitaro`. Bring back + push re-attaches it.
  - **Conflict.** Change the flow in the fake after our fetch, then push. The answer is 409
    and the fake is unchanged. Fetch keeps the pending ops, and the second push succeeds.
  - **Crash between PUT and commit.** Simulated by making the repository raise after the
    PUT. The next push gives 409; fetch then shows the flow clean.
  - **Stale version** (two tabs) gives 409.
  - **Shares that don't sum to 100** can never be produced through the API. A direct test
    of `push_plan` covers the guard.
  - **Push all** with one conflicting flow: the others push, and the conflicting one reports
    409. Each flow is its own transaction.
- **Verify:**
  - The tests pass, with zero mutator survivors in `services/flow_service.py`.
  - The opt-in live check is extended with one fetch → remove → push → re-read round on the
    throwaway campaign.

### Phase 7: Frontend — Campaigns screen

**Model: Sonnet 5.** Rendering generated types against an existing API, following the design
reference.

- **Current State:** The Vite scaffold from Phase 5.
- **Desired State:**
  - **Campaigns screen:**
    - search + list (pick → editor);
    - a "New campaign" form: name, multi-GEO, offer autocomplete, and a collapsed Advanced
      section with domain/group/source dropdowns that default from lookups;
    - validation and Keitaro error states (design board 3, state D).
  - The API wrapper is typed by the generated schema.
  - There is a plain router with two routes: `/` and `/campaigns/:id`.
- **Problems:** There is no UI.
- **Solutions:** Vitest + Testing Library behaviour tests:
  - an invalid GEO shows the inline message and does not submit;
  - submit disables the button and sends the idempotency key;
  - a Keitaro error renders the alert;
  - a successful create navigates to the editor.
- **Verify:** The tests pass, and the frontend part of `scripts/check.sh` passes.

### Phase 8: Frontend — Editor screen

**Model: Sonnet 5.** The screen renders the backend's `FlowView` and sends intents. It holds
no share logic, and the one stateful widget (`ShareField`) has precise rules from vision §5.

- **Current State:** The editor route is empty.
- **Desired State:**
  - **Table grouped by flow:**
    - header `Flow 2 #564221` with type and position;
    - a dirty badge with per-flow Push/Cancel;
    - rows with offer name or `[id]`, the preview link, a `ShareField` + pin toggle, Stats
      and Trends placeholders, and Remove / Bring back;
    - tags: "removed in Keitaro", "will be restored", and "archived in Keitaro · can't be
      restored";
    - an Add combobox.
  - Flows without offers are listed below the table.
  - **Top bar:** Fetch when clean, "Push all (n)" and "Cancel all" when anything is pending,
    plus View in KT and Show all offers.
  - Toasts for backend notes: auto-unpin, external removals, and brought back with a pin.
  - The 409 conflict banner (design state A) with "Fetch & merge".
- **Problems:** There is no editor UI.
- **Solutions:** Behaviour tests:
  - **`ShareField`:**
    - Enter applies;
    - blur applies;
    - Escape cancels;
    - blur with an unchanged value sends nothing;
    - Enter followed by blur sends exactly one op.
  - **Archived row:** shows Remove and no Bring back.
  - **409 on push:** shows the banner, and the Fetch button calls fetch.
  - **Version:** every op sends the last-seen `version`.
- **Verify:** The tests pass, and the frontend gates pass.

### Phase 9: End-to-end, serving, README

**Model: Sonnet 5.** Glue and docs. The e2e suite runs on the fake, so failures reproduce
fast and locally.

- **Current State:**
  - Backend and frontend are tested separately.
  - FastAPI does not serve the bundle.
  - The README says "scaffolding".
  - Playwright browsers are cached on this machine, but the repo has no `@playwright/test`
    yet.
- **Desired State:**
  - **Serving:** FastAPI serves `frontend/dist` with an SPA fallback when it exists. During
    development, the Vite proxy forwards `/api` to `:8000`.
  - **E2E:**
    - `KEITARO_FAKE=1` runs the backend against `FakeKeitaro` with seed data.
    - Playwright specs cover:
      - create campaign → editor shows Flow 2 with the offer at 100 %;
      - add → rebalance → pin → remove → bring back → push;
      - the conflict path;
      - the archived-row path.
  - **README:** setup (`uv sync`, `npm ci`, `.env`), migrate, dev and prod run, tests, the
    opt-in live checks, and the clean_archive warning.
- **Problems:** No proof yet that the pieces work together in a real browser.
- **Solutions:**
  - Add `@playwright/test` to `frontend` dev deps and `e2e/` specs.
  - Make `KEITARO_FAKE` a settings flag. It is never set in `.env.example` defaults.
  - Offer the user a visual check with Playwright screenshots of both screens (global
    CLAUDE.md).
- **Verify:**
  - `npx playwright test` passes.
  - After `uv run uvicorn app.main:app`, the built app loads on `:8000`.
  - One manual live session on a throwaway campaign: create, edit, push, and confirm the
    result in Keitaro. The campaign is archived afterwards.

### Phase 10: Review and hand-off

**Model: Sonnet 5** (the reviewer is always Sonnet, by the global rule).

- **Solutions:**
  1. Run `cd` into the repo and confirm `git rev-parse --show-toplevel` and
     `git branch --show-current`, which must print `feat/campaign-editor`.
  2. Run `/code-review medium feat/campaign-editor`, with no `--fix`, and check that the
     diff it reports matches this branch.
  3. Triage each finding (apply, reject with a reason, or escalate). Add a regression test
     for every applied fix, then re-run `scripts/check.sh`.
  4. Present the branch, the change log and the ub-mode action log. Ask whether to merge or
     open a PR into `chore/scaffold` (or `main`).
- **Verify:** The review scope is confirmed, every finding is triaged, and the checks are
  green after the fixes.

**Routing:** Phases 0, 1, 3, 4, 5, 7, 8, 9, 10 → Sonnet 5 · Phases 2, 6 → Opus 5

---

## 4. Risks and tripwires (summary)

| Risk | Where it is caught |
|---|---|
| A push drops an offer the key cannot read | Phase 6 "unreadable offer kept" test, plus `push_plan` building from all active rows. |
| Archived-offer detection is wrong | Phase 3 tripwire, decision 13. The rule is isolated in `merge_fetch` (one place). |
| Keitaro normalises pushed data, so false conflicts appear | Phase 6 tripwire (post-PUT re-read compared with the plan). |
| A clean_archive call | Client deny-list + test (decision 11), and the project CLAUDE.md. |
| Live tracker pollution | Live checks are opt-in, run on a throwaway campaign that is archived afterwards. |
| The API key leaks | The key is a `SecretStr`, error and log tests cover it, and it never goes into DTOs. |

---

## 5. Change Log

<!-- Format: YYYY-MM-DD: context, actions, decisions (friction and deviations), verification result. -->

- **2026-11-20 — Phase 0.** Context: tooling before any feature work. Actions: branch
  `feat/campaign-editor` from `chore/scaffold`; `pytest-cov` + `hypothesis`; `scripts/check.sh`
  (`--fast` skips mutation); `docs/glossary.md`; tooling output ignored. Decisions: the
  baseline crapper run flagged `keitaro_ping` (CRAP 15.7, untested), so its current output was
  pinned with three tests (this doubles as the parity oracle the plan mentions). Verification:
  verified — check.sh green; mutator 7/8, the survivor sits in `KeitaroClient.get`, which
  Phase 3 rewrites.
- **2026-11-20 — Phase 1.** Context: pure allocation + staged ops. Actions:
  `app/domain/flow.py` (rows, pins, ops, `apply`/`replay`/`rebalance`/`diff`/`forget`/
  `push_plan`), 42 table tests from the vision's numbers. Decisions: ops are **total** (a
  no-op with a note instead of raising), so Phase 2's replay needs nothing extra; the plan's
  "refused" for Bring back on an archived row is that no-op + note. `Add` of a removed offer
  behaves as Bring back. A pin-only change counts as dirty (Push then writes identical offers
  and stores the pin in the base). One hand-computed expectation in the diff test was wrong
  (row 2 keeps 33 %), fixed before implementing. Verification: verified — crapper max 7,
  dryer clean, mutator `--mutate-all` 44/46; the 2 survivors (lines 151, 160: placeholder
  share of a re-added unpinned row, always overwritten by rebalance) are equivalent mutants.
- **2026-11-20 — Phase 2.** Context: fetch merge with pending ops on top. Actions:
  `merge_fetch`, `signature` in `app/domain/flow.py`; 19 tests (the plan's case table, order
  rules, pins, and a hypothesis property: any op sequence keeps active shares at 100).
  Decisions: every case in the plan's table resolved as proposed; no escalation needed.
  Additions beyond the table: a row we removed and pushed keeps `removed_by = local` on later
  fetches (it is not relabelled "removed in Keitaro"); a dormant pin follows the offer if it
  reappears in Keitaro; Keitaro's shares go into the base unchanged even if they don't total
  100 (Keitaro allows that), and the first local op rebalances. Known limit of decision 7: a
  crash-replayed *SetShare/TogglePin* leaves a pin-only diff (dirty, harmless re-push), while
  Remove/Add/Bring back replay clean. Verification: verified — 61 tests, crapper max 7,
  dryer clean, mutator 53/55 (same 2 equivalent mutants).

---

## 6. Decisions Log

<!-- Owner's hand only. Format: YYYY-MM-DD: context, problem, decision (mark overrides/rejections). -->
