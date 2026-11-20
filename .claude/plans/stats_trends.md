---
status: Pending
---

# Stats and Trends columns

Fill the editor's Stats and Trends placeholders with per-offer performance from Keitaro's
report API, so share decisions rest on data. Built and demoed on the fake tracker; the real
tracker is used only for a read-only contract check.

Design canvas: "Campaign Editor Design", artboards *2 · Editor* (filled columns) and
*4 · Stats & trends* (cell states and the calculation).

## Context: what the report API does (explored 2026-11-20)

Source: Keitaro's Admin API spec (`admin-api.docs.keitaro.io/openapi.json`, `POST /report/build`)
plus a read-only probe with our key, filtered to campaigns this app created.

**Verified on the real tracker**
- The key may read reports: `POST /report/build` → 200.
- Request: `{"range": {"interval" | "from","to", "timezone"}, "dimensions": [...],
  "measures": [...], "filters": [{"name","operator","expression"}], "sort": [...]}`.
  `metrics` is accepted as a synonym of `measures` (the spec's example uses it); we send `measures`.
- `IN_LIST` / `EQUALS` filters on `campaign_id` work.
- Response: `{"rows": [ {<column>: value, ...} ], "total": <int>}`: rows are flat objects keyed by
  column name (the spec wrongly types them as strings).
- No dimensions → one totals row, e.g. `{"clicks": 0, "conversions": 0, "revenue": 0}`.
- An unknown column → 400 `{"error": "Column 'x' is not defined. ... contains only: <183 names>"}`.
  The list includes `stream_id`, `offer_id`, `day`, `clicks`, `campaign_unique_clicks`,
  `conversions`, `leads`, `sales`, `rejected`, `approve`, `revenue`, `confirmed_revenue`,
  `sale_revenue`, `lead_revenue`, `cost`, `cr`, `epc`, `epc_confirmed`.

**Assumptions (not observable: our campaigns have no traffic)**
- A1. Dimensioned rows carry the dimension values under their names (`stream_id`, `offer_id`,
  `day` as `"YYYY-MM-DD"`). Ids and money may arrive as numbers or numeric strings.
- A2. `range.to` is inclusive.
- A3. `conversions` = leads + sales + rejected (all postbacks); `revenue` counts approved +
  pending money as Keitaro books it, `confirmed_revenue` only approved.
- A4. Day buckets follow `range.timezone`.

Parsing is lenient where data enters (A1), and the fake follows A1–A4, so a wrong guess shows up
as one failing contract test, not as a redesign. The first campaign with real traffic settles them
(see Phase 5).

## Decisions locked

- **D1. One report call per campaign**, `dimensions: [stream_id, offer_id, day]`, additive
  measures only (`clicks, conversions, leads, sales, rejected, revenue, confirmed_revenue`),
  filter `campaign_id EQUALS <id>`, range = the last `max(window, 14)` days through today.
  The stats window and the trend are both sliced from it locally.
- **D2. Ratios are derived, never fetched or averaged.** CR = Σconversions / Σclicks,
  EPC = Σrevenue / Σclicks over the window. Keitaro's `cr`/`epc` per day are not summed or
  averaged. Zero clicks → no ratio ("no clicks"), never 0 %.
- **D3. Keyed by (flow, offer)**: one offer can sit in two flows.
- **D4. Trend = last 7 complete days vs the 7 before** (today excluded, it is partial). The
  sparkline shows the daily value for 14 days; the last 2 days are drawn lighter (conversions can
  still arrive). Change shown when both halves have ≥ 100 clicks, else "not enough traffic".
  |change| < 5 % → "flat".
- **D5. Stats live beside the editor, not in it**: `GET /api/campaigns/{id}/stats?days=N`, its
  own request, never stored, cached ~60 s per campaign+window. A 403, 400 or timeout shows
  "Stats unavailable" and never blocks editing or pushing.
- **D6. Observed traffic split** (offer clicks ÷ flow clicks) is shown as "observed", since the
  share may have changed inside the window.
- **D7. Calculation is a pure domain function** (`app/domain/stats.py`) with example and
  property tests (hypothesis).

**Open for the user** (the canvas has them as tweaks): primary metric (EPC on `revenue` vs
`confirmed_revenue` vs CR), report timezone, currency label.

## Phase 1: Domain calculation

**Model: Sonnet 5**: pure function, fully specified by D2–D4; example tests plus hypothesis
properties (Σ over flows equals the totals row; zero clicks never yields a ratio) catch mistakes.

- **Current State.** No stats code; the columns render "—".
- **Desired State.** `stats.summarize(rows, window, today) -> {(stream_id, offer_id): OfferStats}`
  with `clicks, conversions, revenue, cr|None, epc|None, observed_split|None` and
  `Trend(daily: list[float|None], change: float|None, direction: up|down|flat|thin)`.
- **Problems.** Ratios averaged by mistake; partial today skewing trends; offers with no rows.
- **Solutions.** Sum first, divide once; slice by complete days; offers present in the flow but
  missing from the report get zero clicks (`direction: thin`).

## Phase 2: Keitaro client + fake report

**Model: Sonnet 5**: the client call mirrors existing ones; the fake follows the request shape
verified above. **Escalate if** the live contract test (Phase 5) contradicts A1–A4.

- **Current State.** `KeitaroClient` has no report method; `FakeKeitaro` serves no `/report/build`.
- **Desired State.**
  - `KeitaroClient.report(campaign_id, since, until, tz)` returns typed `ReportRow`s, parsed
    leniently (str or number).
  - `FakeKeitaro` stores daily aggregates per (campaign, flow, offer, day). Its `/report/build`
    supports the dimensions and measures of D1, `EQUALS`/`IN_LIST` filters and a date range, and
    answers 400 in Keitaro's format for an unknown column.
  - Fake-only `POST /api/_fake/traffic?days=7&clicks_per_day=1000` simulates traffic. Each flow's
    clicks are split by its **current** shares. Every fake offer has a fixed CR and payout from a
    seeded RNG, so results are deterministic. Traffic is saved to the fake's JSON state.
- **Solutions.** Same transport pattern as the other fake endpoints; persistence reuses `save()`.

## Phase 3: API endpoint

**Model: Sonnet 5**: one read-only route in the existing pattern.

- **Desired State.** `GET /api/campaigns/{id}/stats?days=1|7|14|30` → per flow, per offer stats +
  trend + flow totals; errors mapped to `{"available": false, "reason": ...}` with 200, so the UI
  can show the banner without treating it as a failure.

## Phase 4: UI

**Model: Sonnet 5**: follows the canvas; behaviour tests with mocked API.

- Period selector in the editor header (Today / 7 / 14 / 30 days, remembered per browser).
- Stats cell: primary metric bold, then `clicks · CR`; flow header carries flow totals.
- Trends cell: 14-day sparkline + direction arrow (blue up / orange down, differing in lightness)
  + "▲ 18 %"; `aria-label` spells it out.
- States: loading skeleton, no clicks, not enough traffic, new offer (not pushed), removed offer
  (history greyed), stats unavailable banner.
- Stats reload after Fetch, after Push and on period change; never on share edits.

## Phase 5: Contract check, e2e, docs

**Model: Sonnet 5.**

- Live test (opt-in, read-only): the report request of D1 on a throwaway campaign returns 200,
  `rows` is a list, the totals row has the requested keys.
- e2e on the fake: simulate traffic → stats appear → push a new split → simulate more → the
  observed split and the trend move.
- README: the traffic endpoint; the metric definitions.
- When a campaign with real traffic exists: one manual look to settle A1–A4.

**Routing:** all phases → Sonnet 5 (each is specified here and covered by tests; the contract
check guards the one unverified boundary).

## Change Log

- **2026-11-20**: context: explore the report API and design Stats/Trends. Actions: read the
  official spec, probed `/report/build` read-only on app-created campaigns, wrote this plan,
  added the columns and a states artboard to the design canvas. Decisions: probe limited to
  our own campaigns (shared tracker); assumptions A1–A4 recorded instead of guessed silently.
  Verification: request/response shape verified live; dimensioned rows unverified (no traffic).

## Decisions Log

<!-- Owner's hand only. Format: YYYY-MM-DD: context, problem, decision (mark overrides/rejections). -->
