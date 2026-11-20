---
status: InProgress
---

# Stats & Trends: implementation plan

Implements the **approved and locked** vision [`.claude/vision/stats_trends.md`](../vision/stats_trends.md).
Every number, label and rule comes from it; where this plan and the vision disagree, the vision
wins and this plan is wrong. This file replaces the draft plan of 2026-11-20 (its exploration
notes are kept below, its decisions are superseded).

Design canvas: "Campaign Editor Design", artboards *2 · Editor* and *4 · Stats & trends*.

## Context

### What exists today (`main` at 78b69b7)

- **Backend** (`backend/app`): FastAPI app built by `create_app(settings)` in `main.py`.
  - `config.Settings` (pydantic-settings, `.env` + environment).
  - `keitaro/client.py`: `KeitaroClient`, typed async calls, `clean_archive` refused before I/O.
  - `keitaro/fake.py`: `FakeKeitaro`, an in-process model of the API behind an
    `httpx.MockTransport`, with JSON persistence (`save`/`load`).
  - `keitaro/seed.py`: the demo tracker for `KEITARO_FAKE=1`.
  - `api/fake_controls.py`: `/api/_fake/*`, mounted only in fake mode.
  - `domain/flow.py`: pure share logic, tested with examples and hypothesis.
  - `api/views.py`: builds `EditorView` from stored flows.
  - `api/deps.py`: `Keitaro`, `Db`, `Config` dependencies, `TtlCache`.
- **Frontend** (`frontend/src`): React + openapi-fetch, types generated from the backend's
  OpenAPI (`npm run gen:api`).
  - `OfferRowView.tsx` renders Stats and Trends as `—` placeholders (`aria-label="No stats yet"`
    and `"No trends yet"`).
  - `FlowSection.tsx` renders the flow header.
  - `useEditor.ts` runs editor requests through a serial queue.
- **Start-up:** `uv run uvicorn app.main:app`; `app.main` builds the app at import time from
  `load_settings()`. There is no launcher of our own.
- **Gates:** `scripts/check.sh`: ruff, pytest under crapper (CRAP < 10), dryer (≥ 0.8), mutator
  (full runs); frontend typecheck, lint, vitest under crapper, dryer, mutator. Playwright e2e
  runs against the fake (`playwright.config.ts`, port 8765).

### Verified about Keitaro's report API (2026-11-20, read-only, own campaigns only)

- `POST /report/build` → 200 with our key.
- Request: `range` (`from`/`to` or `interval`, plus `timezone`), `dimensions`, `measures`,
  `filters` (`name`, `operator`, `expression`), `sort`.
- `EQUALS` / `IN_LIST` on `campaign_id` work.
- Response `{"rows": [{column: value}], "total": n}`; no dimensions → one totals row.
- Unknown column → 400 `{"error": "Column 'x' is not defined. ... contains only: <names>"}`.
  The names include `stream_id`, `offer_id`, `day`, `clicks`, `leads`, `sales`, `rejected`,
  `lead_revenue`, `sale_revenue`.
- Glossary: `conversions` = lead + sale (rejected not included); statuses are current, so a
  confirmed lead moves from `leads` to `sales`.

**Still assumed** (vision § 5; no real grouped rows can be observed until the tracker's domain
resolves): A1 rows carry `stream_id`, `offer_id`, `day` (`YYYY-MM-DD`), values may be numbers
or numeric strings; A2 `range.to` is inclusive; A3 revenue = lead + sale revenue (we request
both and add them ourselves); A4 days follow `range.timezone`. Parsing is lenient where data
enters, and the fake follows A1–A4, so a wrong guess shows up as one failing contract check.

## Decisions locked

From the vision (not reopened here):

- **V1. Metrics.** Main EPC = Σ(lead_revenue + sale_revenue) ÷ Σclicks. Second CR =
  Σ(leads + sales) ÷ Σclicks. Pending share = Σleads ÷ Σ(leads + sales + rejected). Observed
  split = offer clicks ÷ **all** the flow's clicks (rows with no offer included). Trash is never
  requested. Confirmed EPC and Approve % are not shown.
- **V2. Sum first, divide once.** A ratio whose denominator is 0 is `None` ("No clicks"), never 0.
- **V3. Periods.** Today = the partial current day; 7 / 14 / 30 = that many complete days
  ending yesterday.
- **V4. Trend.** EPC over days −9…−3 vs −16…−10. "Not enough traffic" if either week has
  < 100 clicks or 0 conversions. Otherwise "within noise" if |change| < 2 × √(1/c₁ + 1/c₂)
  (c = the week's leads + sales), else up / down. The sparkline shows daily EPC for days −14…−1,
  the last 2 lighter.
- **V5. Rule 5.** Flow totals = every report row of the flow over the period, including rows
  with no offer and offers no longer in the flow.
- **V6. Beside the editor.** Read-only, loaded separately, never stored, never part of the staged
  state. Failures show a banner; editing and pushing are unaffected. Reload after Fetch, after
  Push and on period change, never on a share edit.
- **V7. Beta.** Off unless started with `--stats-beta` (or `STATS_BETA=1`). Off: placeholders,
  no period switch, no report call.
- **V8.** Fixed timezone from config (default UTC), currency `$`.

Implementation decisions (this plan):

- **P1. Data shape first.** One additive record, `Counts(clicks, leads, sales, rejected,
  lead_revenue, sale_revenue)`, and one report row type, `DayRow(stream_id, offer_id | None, day,
  counts)`. Everything else (ratios, splits, trends) is a pure function of a list of `DayRow`s
  and a date. Money is `Decimal` inside the domain, formatted only at the edge.
- **P2. One request per campaign and period**: `dimensions [stream_id, offer_id, day]`, the six
  measures of P1, `campaign_id EQUALS id`, `range` from `today − max(days, 16)` to `today`
  (inclusive, A2), timezone from config. `days` is 0 for Today and 7 / 14 / 30 otherwise, so
  Today still fetches the 16 days the trend needs.
- **P3. The stats endpoint is the only switch the UI reads.**
  `GET /api/campaigns/{id}/stats?period=today|7|14|30` always answers 200 with a tagged union:
  - `{"status": "disabled"}` when the beta is off. Keitaro is never called.
  - `{"status": "unavailable", "reason": "..."}` on a Keitaro error or timeout.
  - `{"status": "ok", ...}` with the numbers.

  `status` is a required `Literal` with **no default**: with a default, the OpenAPI schema
  drops it from `required` and the generated TS type makes it optional, which breaks narrowing.
  `period` is a **string** at the API edge, `Literal["today", "7", "14", "30"]`: FastAPI does
  not coerce `"7"` to an int literal (probed: `?period=7` → 422). The route maps it to the
  domain's `Period`.

  The UI shows placeholders for `disabled` and decides nothing by itself (one decision, one
  place). No separate "features" endpoint.
- **P4. The endpoint knows nothing about staged edits.** It returns stats for every
  (flow, offer) pair in the report, plus flow totals. The UI joins them to its rows by
  `(stream_id, offer_id)`:
  - a row with `change === "added"` → "New: no traffic yet";
  - a row with no entry → "No clicks in N days";
  - a removed row → greyed history.
- **P5. The backend computes, the UI formats.** No arithmetic in TypeScript beyond formatting
  and the sparkline's pixel coordinates.
- **P6. Cache:** a per-(campaign, period) cache of 60 s. A Fetch **and a Push** pass
  `refresh=true`, which skips it (after a Push the 60 s cache would otherwise hand back the
  pre-push numbers). The fake traffic controls and `fail-next` clear it.
  - The cache is built in `create_app` before the fake controls (which receive it), kept on
    `app.state`, and **read only through a `get_stats_cache` dependency**, never as
    `request.app.state` inside the service.
  - Why a dependency and a reset: the conftest `api` fixture reuses the module-level
    `app.main.app` for every test and only swaps `dependency_overrides`, so `app.state` alone is
    as global as `offers_cache`. Every `FakeKeitaro` hands out ids from 1000, so campaigns in
    different tests share ids, and `fake.record()` doesn't pass through the controls that clear
    the cache. The `api` fixture therefore overrides `get_stats_cache` with a fresh cache per
    test (as it already clears `offers_cache`).
- **P7. "Today" is a dependency, not a call to `date.today()`.** A `get_today` dependency
  returns the current date in the configured timezone. Tests override it with a fixed date; the
  fake simulator is given the same callable, so day buckets and "today" never disagree. Settings
  are likewise read only through `get_settings`, so the fixture controls `stats_beta`.
- **P8. Launcher:** `backend/app/__main__.py`. `uv run python -m app --stats-beta [uvicorn
  args]` sets `STATS_BETA=1` in the environment, then hands the remaining arguments to uvicorn,
  with `app.main:app` as the default target. The environment, not a module global, carries the
  flag, because `app.main` reads settings at import and `--reload` imports it in a child process.
- **P9. Fake traffic is stored as daily `DayRow`s** in the fake's state. There are two ways to
  write them:
  - **exact:** a test states the counts itself, which is how the formulas are proven;
  - **simulated:** seeded, from offer profiles and the flow's current shares, for demos, e2e
    and the statistical checks.

## How the formulas are proven correct

Four layers, each catching a different class of mistake:

1. **Domain examples (Phase 1).** The vision's worked numbers become literal tests:
   - 53 ÷ 1,010 = 5.2 % (not 17.5 %);
   - 3 % at $25 → EPC $0.75 beats 5 % at $10 → $0.50;
   - band(90, 75) = 31 %, band(900, 750) = 10 %, so −17 % is noise in the first and real in the
     second;
   - the lag table (40 / 22 / 0 leads) gives CR 4.0 % → 4.0 % → 2.6 %;
   - the flow EPC is the click-weighted blend, not the average of offer EPCs;
   - 0 clicks → `None`.

   These are what mutation testing measures against.
2. **Domain properties (Phase 1, hypothesis).**
   - **Additivity:** splitting any day's row into two rows with the same keys changes nothing.
     This is the property that catches any averaging of ratios.
   - The order of rows doesn't matter.
   - Flow totals equal the sum over the offers plus the no-offer rows.
   - A ratio is `None` exactly when its denominator is 0.
   - Each observed split is between 0 and 1, and the offers' **clicks** sum to at most the
     flow's clicks. (Stated over integers: the float splits can sum past 1, e.g. 9/28 + 18/28 +
     1/28 > 1 in floating point.)
   - The noise band shrinks as counts grow: multiplying both weeks by k > 1 never turns a real
     change into noise.
   - The verdict depends only on the two settled weeks: changing days −2, −1 or today never
     changes it.
3. **End-to-end oracle through the fake (Phases 2–4).** Tests write exact counts into the fake
   (P9) and call `GET /stats`. They compare against values computed by hand in the test, not by
   the code under test. A cross-check asks the fake's `/report/build` for the same range
   **without dimensions**, the way Keitaro itself would total it. The flow totals' clicks, leads
   and sales must equal that totals row, and CR = (leads + sales) ÷ clicks taken from it.
4. **Statistical checks on the simulator (Phase 3).** These are seeded, so they are
   deterministic.
   - **Calibration of the noise band:**
     - 200 seeds of two weeks with the same offer profile flag a "real" change in ≤ 10 % of runs
       (a 2σ band should be about 5 %);
     - a −40 % drift at about **300 → 180** conversions a week is flagged as down in ≥ 95 % of
       runs. Expected power is above 99 %: band ±19 %, and the SD of the log-ratio is about
       0.09.

       At 150 → 90 the power is only about 93 %, so a correct simulator could fail a 95 %
       threshold. That is why the volume is set here and not left to taste.

     These two tests show the band is neither too tight nor too loose.
   - **Profile recovery:** with lag off, 100,000 clicks at cr_all 5 %, approve 60 % and payout
     $20 give a settled CR within 3σ of 3 % and an EPC within 3σ of $0.60.
   - **Lag:** with lag on, yesterday's pending share is close to the configured 60 %
     (reachable only because the relabel draws from **all** postbacks, rejected ones included;
     relabelling only sales caps it at 0.6 × approve). The trend is the same with lag on or
     off up to the 0.02 tail: assert `|change_lag − change_nolag| < 0.03` for every seed, and an
     equal verdict only when `|change|` is more than 0.03 away from the band. This needs the
     **same draws**:
     - postbacks and sales are drawn identically either way;
     - lag only relabels some of them as leads (seeded per day, separately from the outcome
       draws).

     Otherwise the two runs would be different samples and the test would flake near the band
     edge.
   - **Split:** after a push to 60 / 20 / 20, a simulated week's observed split is within ±2
     points of the new shares. A 14-day window spanning the push shows the blend (Rule 5).

## Phase 1: Domain: `app/domain/stats.py`

**Model: Sonnet 5.** The maths is fully specified (V1–V5). The examples, hypothesis properties
and mutation testing fail loudly on any mistake.

- **Current State.** No stats code. `domain/flow.py` shows the house style: frozen dataclasses,
  pure functions, notes returned rather than printed.
- **Desired State.**
  ```python
  @dataclass(frozen=True)
  class Counts:
      clicks: int = 0; leads: int = 0; sales: int = 0; rejected: int = 0
      lead_revenue: Decimal = ZERO; sale_revenue: Decimal = ZERO
      def __add__(self, other: Counts) -> Counts: ...
      @property
      def conversions(self) -> int: return self.leads + self.sales        # Keitaro's definition

  @dataclass(frozen=True)
  class DayRow:
      stream_id: int; offer_id: int | None; day: date; counts: Counts

  Period = Literal["today", 7, 14, 30]     # domain type; the API maps "7" → 7 (P3)
  def span(period: Period, today: date) -> tuple[date, date]: ...         # V3
  def report_range(period: Period, today: date) -> tuple[date, date]:      # P2
      days = 0 if period == "today" else period
      return today - timedelta(days=max(days, 16)), today

  @dataclass(frozen=True)
  class Cell:                       # one offer, or a flow's totals, over the period
      counts: Counts
      epc: Decimal | None; cr: float | None; pending: float | None
      split: float | None           # None for flow totals

  class Verdict(StrEnum): UP = "up"; DOWN = "down"; NOISE = "within_noise"; THIN = "not_enough_traffic"

  @dataclass(frozen=True)
  class Trend:
      verdict: Verdict
      daily_epc: tuple[Decimal | None, ...]      # 14 values, days −14…−1; None = no clicks that day
      older: Counts; newer: Counts               # the two settled weeks
      change: float | None; band: float | None   # None when THIN

  @dataclass(frozen=True)
  class FlowStats:
      stream_id: int; totals: Cell; offers: dict[int, OfferStats]   # OfferStats = Cell + Trend

  def summarize(rows: Iterable[DayRow], period: Period, today: date) -> dict[int, FlowStats]: ...
  def noise_band(c1: int, c2: int) -> float: return 2 * math.sqrt(1 / c1 + 1 / c2)
  ```
  Illegal states are hard to write:
  - `Verdict.THIN` ⇔ `change is None` ⇔ `band is None`, checked in `__post_init__`.
  - Ratios are built only through one `_ratio(num, den)` that returns `None` on 0.
- **Problems.**
  - Averaging daily ratios by mistake.
  - Off-by-one on spans: Today vs complete days, an inclusive end.
  - The trend picking up the unsettled days.
  - A boundary case: |change| equal to the band.
  - Float money drift.
- **Solutions.**
  - TDD in this order: `Counts.__add__` → `span` / `report_range` (a test per period,
    including Today) → `Cell` ratios → split and flow totals →
    `noise_band` → `Trend` → `summarize`.
  - Each step starts with the vision's worked example as the failing test, then the hypothesis
    properties (layer 2).
  - Boundary: the vision says "smaller than the band" is noise, so `abs(change) < band` → NOISE
    and equal is real, pinned by a test.
  - Money stays `Decimal` from parsing to formatting.
  - Gates: crapper < 10, mutator with 0 survivors on `domain/stats.py`.

## Phase 2: Report contract: client + fake `/report/build`

**Model: Sonnet 5.** It mirrors the existing client and fake patterns, against a request shape
verified live.
**Escalate/stop if:** the opt-in live check (Phase 6) gets a 400 for the P2 request; that means
the column list or the range format differs from what was verified, and P2 needs revising.

- **Current State.** `KeitaroClient` has no report call. `FakeKeitaro` has no `/report/build`
  route and no traffic.
- **Desired State.**
  - `KeitaroClient.report(campaign_id, since, until, tz) -> list[DayRow]` sends exactly the
    P2 body. Parsing goes through `KtReportRow` in `keitaro/schemas.py`, which is lenient (A1):
    - ints from `int` or `"12"`;
    - money from number or string, into `Decimal`;
    - `offer_id` of `None`, `0` or `""` → `None`;
    - `day` as `YYYY-MM-DD`.

    This is the only place outside data enters; inside, the types are trusted.
  - `FakeKeitaro.traffic: dict[tuple[int, int, int | None, date], Counts]` (campaign, stream,
    offer, day), saved in the state file under `"traffic"` **as a list of plain rows**
    (`{"campaign_id", "stream_id", "offer_id", "day": "YYYY-MM-DD", ...counts, money as
    strings}`): `save()` is `json.dumps`, which raises on tuple keys, `date` and `Decimal`.
    `load` treats a missing key as empty, so existing `data/fake-keitaro.json` files keep
    working.
  - `handle()` saves after every non-GET request today. `/report/build` is a read sent as POST,
    so the fake marks it read-only and skips `save()`; otherwise every stats load rewrites the
    whole state file.
  - A fake `POST /report/build` that:
    - checks every dimension and measure against a column list (an unknown one gets Keitaro's
      400 message);
    - supports `EQUALS` / `IN_LIST` on `campaign_id` and an inclusive `from`/`to`;
    - groups by any subset of `[campaign_id, stream_id, offer_id, day]`, summing measures;
    - with no dimensions, returns one totals row;
    - answers `{"rows": [...], "total": n}`.
  - Test helper `fake.record(campaign_id, stream_id, offer_id, day, Counts)` for exact counts
    (P9).
- **Problems.**
  - The real tracker may send strings where we expect numbers.
  - Old state files have no `traffic`.
  - The fake could drift from Keitaro's shape.
- **Solutions.**
  - Client tests with respx, covering the number and string variants and `null` offer_id.
  - A fake test that a request with an unknown column answers 400 in Keitaro's format.
  - A load test with a state file that has no `traffic` key, and a **save → load round-trip**
    test with traffic in it (the conftest fake has no `state_file`, so nothing else reaches
    `save()`; only the README demo would hit the crash).
  - A test that `/report/build` leaves the state file untouched.
  - The fake's column list is a constant shared with the live check (Phase 6), so both enforce
    the same names.

## Phase 3: Fake traffic simulator + controls

**Model: Sonnet 5.** It is new code, but self-contained and seeded, and the statistical checks
(layer 4) fail if it is wrong.
**Escalate/stop if:** either calibration test fails (false positives > 10 %, or power < 95 %
at 300 → 180).
- First recheck the arithmetic of the test itself: volumes, seeds, and the same-draw
  requirement.
- **Never tune the band or the simulator to make it pass.** If the arithmetic holds, the vision's
  band is wrong for this data, and that is a question for the user.

- **Current State.** The fake can only simulate edits made in Keitaro (detach, archive).
- **Desired State.**
  - `OfferProfile(cr_all, approve, payout)`. The defaults come from a seeded RNG keyed by
    `offer_id`, so they are stable across runs, and `fake.profiles[offer_id]` overrides them.
    `cr_all` is the chance a click produces any postback.
  - `fake.simulate(campaign_id, days, clicks_per_day, *, today, seed, lag=False,
    drift: dict[int, float] = {}, no_offer=0.0, today_fraction=0.5)`. `drift` is a **weekly**
    ratio: −0.17 means the rate is 17 % lower a week later. For each regular flow and day:
    1. Split the day's clicks by the flow's **current** active shares, using largest
       remainders. A `no_offer` fraction gets `offer_id=None` (Rule 5). Today gets
       `today_fraction` of a day.
    2. Draw postbacks ~ Binomial(clicks, p), with
       `p = min(1, cr_all × (1 + drift) ** (i / 7))` and `i` counted from the oldest simulated
       day (0) forward, and their final
       outcome: sales ~ Binomial(postbacks, approve), the rest rejected. These draws never
       depend on `lag`.
    3. With lag on, relabel some of the postbacks (any final outcome) as still undecided
       (leads), from a separate seeded stream: 0.9 today, 0.6 at −1, 0.35 at −2, and **0.02 from −3 on**.

       Days −3 and older are as settled as the older week, matching the vision's "both weeks
       equally settled". With money booked on the lead, a 10 % undecided tail on days −3 to −5
       would lift the newer week's EPC by about 3 % and bias every trend.
    4. Money is booked on the lead: `lead_revenue = leads × payout`,
       `sale_revenue = sales × payout`.
    5. Write the result into `traffic`, replacing those days: idempotent, so re-running gives
       the same state.
  - Controls (fake mode only, in `api/fake_controls.py`):
    - `POST /api/_fake/traffic` with `{campaign_id, days, clicks_per_day, seed?, lag?, drift?,
      no_offer?}`;
    - `PUT /api/_fake/offers/{id}/profile`;
    - `DELETE /api/_fake/traffic?campaign_id=`;
    - `POST /api/_fake/fail-next` with `{status}`: routes the existing `fake.fail_next` so the
      next report fails (e2e step 4).

    All four clear the stats cache, so a warm cache never hides the change.
  - In fake mode the app exposes the fake as `app.state.fake`, so app-mode tests can read
    `fake.requests` (today it is a local inside `_keitaro_factory`).
  - Traffic restored from an old state file keeps its old dates. On start in fake mode, the seed
    re-simulates the demo campaign relative to today, so the demo never goes thin.
  - Seed: the demo campaign gets 30 days of traffic, so a fresh `KEITARO_FAKE=1 --stats-beta`
    run shows every state at once:
    - 3749 with a strong upward drift, a real ▲;
    - 3717 with a −17 % drift at about 80 conversions a week, so it reads **"within noise"**
      with the band shown (the vision's offer B);
    - 11111 flat.

    At realistic volumes (about 80 conversions a week, band about ±30 %) most trends read
    "within noise", and that is the feature working. So the demo is built to show **why** a
    quiet Trend column is useful, not only arrows: a scary-looking −17 % that the screen
    declines to flag. The README's demo walkthrough says so.
- **Problems.**
  - Randomness makes tests flaky.
  - Shares may be changed mid-simulation.
  - The demo needs both a real arrow and "within noise".
- **Solutions.**
  - Everything is seeded (`random.Random(seed)`, Python ≥ 3.12 `binomialvariate`).
  - The statistical tests of layer 4 use fixed seeds and loop over seed ranges; there is no
    wall clock.
  - "Shares changed mid-window" is just two `simulate` calls around a push.
  - The demo drifts are tuned in a test that asserts the seeded demo shows up, down and
    within-noise. The local venv is Python 3.14 and CI runs 3.12: before tuning, diff CPython
    3.12's `random.binomialvariate` against 3.14's. If the draw order differs, the demo test
    asserts verdicts with margin rather than exact counts, and runs on 3.12 in CI either way.
  - Layer-4 tests are marked `@pytest.mark.slow`. Time one first: mutator reruns the suite for
    every mutant, so the 200-seed loops may need to be excluded from the mutator's test command
    (the domain's examples and properties are what kill its mutants).

## Phase 4: Settings, launcher, service and endpoint

**Model: Sonnet 5.** It follows existing patterns (settings, deps, routers), and the beta-off
behaviour is pinned by a test asserting zero report requests.
**Escalate/stop if:** `uvicorn.main` cannot take our remaining arguments unchanged (the
`--reload` child would not inherit the flag). The launcher shape (P8) would then need another
design.

- **Current State.** There is no `stats_beta` setting, no launcher and no stats route.
- **Desired State.**
  - `Settings.stats_beta: bool = False` (env `STATS_BETA`), `stats_timezone: str = "UTC"`,
    `stats_currency: str = "$"`.
  - `app/__main__.py`:
    ```python
    def main(argv: list[str] | None = None) -> None:
        parser = argparse.ArgumentParser(prog="python -m app", add_help=False)
        parser.add_argument("--stats-beta", action="store_true")
        ours, rest = parser.parse_known_args(argv)
        if ours.stats_beta:
            os.environ["STATS_BETA"] = "1"
        # uvicorn reads its APP argument from UVICORN_APP when none is given, so an explicit
        # target still wins. This replaces a ":"-in-argument check, which misread `--host ::1`.
        os.environ.setdefault("UVICORN_APP", "app.main:app")
        uvicorn.main.main(args=rest)   # click Command.main; exits via sys.exit
    ```
  - `get_today` returns `datetime.now(ZoneInfo(settings.stats_timezone)).date()`. In fake mode
    the simulator gets the same callable.
  - `services/stats.py`: `StatsService(kt, today, cache).campaign(campaign_id, period,
    refresh)`. It computes the P2 range, calls `kt.report`, and returns
    `summarize(rows, period, today)`. A `KeitaroError` becomes the `unavailable` reason, with
    the same wording as the canvas banner (403 → "this API key may not read reports"; timeout
    or 5xx → "Keitaro didn't answer in time").
  - `api/stats.py`: `GET /api/campaigns/{id}/stats?period=&refresh=` → the P3 union.
    Pydantic models live in `api/schemas.py`:
    - money as a string quantized to 4 decimals (`ROUND_HALF_EVEN`), so EPCs under a cent
      survive; unquantized `Decimal` division serialises as 28 digits;
    - ratios as floats;
    - `as_of` (today), `timezone`, `currency`.

    Beta off returns `disabled` before any dependency touches Keitaro.
- **Problems.**
  - The flag has to survive `--reload`.
  - "Today" has to be the same for the bucket and the label.
  - Beta off must stay invisible.
- **Solutions.**
  - **Test isolation for the environment.** `Settings(_env_file=None, ...)` disables only the
    `.env` file; pydantic-settings still reads the process environment. So:
    - launcher tests set and clear `STATS_BETA` / `UVICORN_APP` only through
      `monkeypatch.setenv` / `delenv` (which restores them), never by writing `os.environ`
      directly from the test;
    - the conftest `settings` fixture and `test_app_modes._settings` pass `stats_beta=False`
      explicitly, so a developer shell exporting `STATS_BETA` cannot flip them.
  - Launcher tests:
    - `main(["--stats-beta", "--port", "9"])` with `uvicorn.main` stubbed sees `STATS_BETA=1`,
      `UVICORN_APP=app.main:app`, and receives `["--port", "9"]`;
    - an explicit target (`main(["other:app"])`) is passed through and wins;
    - without the flag, `STATS_BETA` stays unset.
  - App-mode tests (existing `test_app_modes.py` style):
    - beta off → `disabled`, and `app.state.fake.requests` holds no `/report/build`;
    - beta on → `ok`.
  - One endpoint test per period value (`today`, `7`, `14`, `30`) → 200, and `?period=5` → 422.
  - The OpenAPI schema lists `status` as required on each union member.
  - Oracle tests (layer 3) through `LocalClient`, with exact fake counts and `get_today`
    overridden to a fixed date.
  - Run `npm run gen:api` to regenerate the TS types.

## Phase 5: UI

**Model: Sonnet 5.** Behaviour tests with the mocked API (`mockApi`) and pure formatters; it
follows the canvas.

- **Parity gate (before touching `OfferRowView`).** Add a characterization test: with the stats
  endpoint answering `disabled`, the editor renders exactly what it renders today. That means:
  - the two `—` cells with `aria-label`s "No stats yet" and "No trends yet";
  - no period switch, no flow totals line;
  - no request other than the editor's own plus one stats call.

  No current test pins the placeholders, so this oracle must exist first. The beta-off e2e run
  (Phase 6) repeats it in a browser.
- **Current State.** The placeholders are hard-coded in `OfferRowView`, and `useEditor` knows
  nothing about stats.
- **Desired State.**
  - `stats/useStats.ts`: `useStats(campaignId, period, reload)` → `loading | disabled |
    unavailable(reason) | ok(data)`. `useEditor` exposes `statsReload = {epoch, refresh}`: the
    epoch goes up after Fetch, Push and Push all, never after an op (V6), and `refresh` is true
    for all three, so the request skips the 60 s cache (P6). A period change reloads with
    `refresh=false`.
  - A non-200 reply or a network error maps to `unavailable` with a generic reason; only the
    200 union decides the other states.
  - `mockApi` gets a default `GET /api/campaigns/{id}/stats` route answering `disabled`, so the
    existing EditorScreen tests make no unmocked call (an unmocked route answers 404). The
    banner uses `role="status"`, not `role="alert"`, so `findByRole('alert')` in the existing
    tests still finds exactly one element.
  - `stats/format.ts` (pure, tested):
    - money with the currency;
    - percent to 1 decimal;
    - the delta label (`▲ +42 %`, `▼ −44 %`, `within noise`);
    - the conversion label (`80 → 72 conv. (−17 %, band ±32 %)`);
    - the pending line, with the `today: mostly pending` wording;
    - the aria sentence;
    - sparkline points (the only arithmetic in the UI: pixels).
  - Components:
    - `PeriodSwitch` (Today / 7 / 14 / 30; remembered in `localStorage` inside try/catch,
      default 7);
    - `StatsCell`;
    - `TrendCell` (inline SVG; the last 2 points drawn at lower opacity; up blue / down orange,
      which also differ in lightness and arrow direction);
    - the flow-header totals line;
    - `StatsBanner` ("Stats unavailable." + reason + Try again).
  - Row states (P4): loading skeleton, No clicks, New: no traffic yet, Not enough traffic,
    removed greyed.
- **Problems.**
  - Stale responses after a fast period switch.
  - Stats must never block edits.
  - `localStorage` may throw.
- **Solutions.**
  - Each request carries its (period, epoch). A late reply for an old key is dropped, pinned
    by a test with a delayed mock.
  - Stats state lives outside the editor queue, so edits never wait for it.
  - Storage access is wrapped, with a test that stubs it to throw.

## Phase 6: e2e, contract check, docs

**Model: Sonnet 5.**

- **Desired State.**
  - **Playwright:** two web servers, each with **its own database file**. Playwright starts
    them one after another, and today's command runs `rm -f ../data/e2e.db`, so a shared file
    would be deleted under the first server.
    - Today's server on port 8765 (beta off, `e2e.db`) keeps every existing spec and adds one
      asserting the placeholders.
    - A new server on port 8766 (`e2e-beta.db`) starts through **the launcher itself**
      (`uv run python -m app --stats-beta --port 8766`) with `KEITARO_FAKE=1`.
    - Two projects with their own `baseURL`; `testMatch` puts `stats.spec.ts` on the beta
      project only and `testIgnore` keeps it off the other, so `editor.spec.ts` does not run
      twice.
  - `e2e/stats.spec.ts` runs on 8766:
    1. Simulate traffic, then check the stats and trends appear with the seeded verdicts.
    2. Switch the period and check the numbers change.
    3. Push 60 / 20 / 20, simulate 7 days, Fetch, and check the observed split moves toward the
       new shares.
    4. Fail the next report (`POST /api/_fake/fail-next`) and check the banner shows while
       editing still works.
  - **Live check (opt-in, `-m live`, read-only):** the P2 request on the throwaway campaign
    returns 200, `rows` is a list, and the totals row has the six measures. It also checks that
    every column the fake accepts is in the 400 message's list, so the fake never invents a
    column.
  - **README:** start with `--stats-beta` or `STATS_BETA=1`; the fake traffic controls with a
    curl example; the metric definitions, linking the vision.
  - **When a domain resolves** (needs user action): one manual look at real grouped rows to
    settle A1, A2 and A4, recorded in the Change Log.
- **Gates:** `scripts/check.sh` (full, with mutation) green; `npm run e2e` green; then
  `/code-review medium` on the branch, findings triaged (never `--fix`).

**Routing:** all phases → Sonnet 5. Each is specified here, and the four verification layers
fail loudly. The tripwires in Phases 2–4 name the conditions that send a phase back for a
decision.

## Change Log

- **2026-11-20**: context: explore the report API and design Stats/Trends. Actions: read the
  official spec, probed `/report/build` read-only on app-created campaigns, wrote the first
  draft of this plan, added the columns and a states artboard to the design canvas. Decisions:
  probe limited to our own campaigns (shared tracker); assumptions A1–A4 recorded instead of
  guessed silently. Verification: request/response shape verified live; dimensioned rows
  unverified (no traffic).
- **2026-11-20**: context: the user approved the "Flow 1 check" to observe real grouped rows
  (A1, A2, A4) without sending traffic to the offer. Actions: created `kce-flow1-check-…`
  through the app, tried 3 clicks, queried its report, archived it. Decisions: stopped after the
  tracker refused the direct-to-server request (409) instead of working around it.
  Verification: **blocked**. The tracker's only domain has no DNS record; A1, A2, A4 remain
  assumptions until a resolving domain exists (needs user action).
- **2026-11-20**: context: the vision was approved and locked (after the skeptic review and the
  beta flag); the user asked for a detailed implementation plan covering today's system, the
  `--stats-beta` switch and how the fake imitates statistics to prove the formulas. Actions:
  read the backend (settings, app factory, client, fake, seed, controls, views, deps) and the
  editor UI; rewrote this plan around the locked vision. Decisions: the stats endpoint is the
  UI's only switch (no features endpoint); the trend window is 16 days, so the report range is
  `max(period, 16)` days plus today; exact and simulated fake traffic; four verification layers;
  a parity gate before replacing the placeholders. Verification: plan only, nothing implemented.

- **2026-11-20**: context: the user asked for a second, more technical skeptic pass on this
  plan (Opus), then approved folding in all of its findings. Actions: verified the claims
  (probed `?period=7` → 422 on FastAPI/pydantic in the venv; 9/28 + 18/28 + 1/28 > 1; read
  conftest, `playwright.config.ts`, `mockApi.ts`) and revised the plan: string `period` at the
  API and `report_range` with Today = 0 days; the split property over integer clicks;
  `STATS_BETA` isolated through monkeypatch and explicit `stats_beta=False`; `get_today` and
  `get_stats_cache` dependencies with a per-test cache; `app.state.fake`; traffic saved as a
  list, `/report/build` skips `save()`, a `fail-next` control, demo re-seeded relative to
  today; weekly `drift` with p ≤ 1 and the lag test's tolerance; required `status`, money to
  4 decimals, `refresh` after Push, non-200 → unavailable, a default stats route in `mockApi`;
  one database per e2e server and specs split by project; the launcher defaults the target
  through `UVICORN_APP`; a Python 3.12 check of `binomialvariate`, and slow layer-4 tests timed
  against mutation. Decisions: none reopened; the vision is unchanged. Verification: plan only.

## Decisions Log

<!-- Owner's hand only. Format: YYYY-MM-DD: context, problem, decision (mark overrides/rejections). -->
