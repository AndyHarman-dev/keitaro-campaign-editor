# Vision — Stats & Trends in the campaign editor

> Living document, like [`campaign_editor.md`](campaign_editor.md): *what* we are building, *why*,
> and *how we will approach it*. Not an implementation plan. The plan comes after this vision is
> approved (a draft exists: `.claude/plans/stats_trends.md`, status Pending, to be revised).

---

## 1. The problem: shares are set blind

The editor lets you split a flow's traffic between offers: 34 / 33 / 33, pin one, push. But a
share is a **bet**: "send a third of my paid clicks to this offer". Whether the bet is good
depends on one thing the editor does not show today: **how much each offer earns per click**.

To decide today, a buyer has to leave the editor, open Keitaro's report builder, filter by the
campaign, group by flow and offer, pick the metrics, compare the rows in their head, come back,
and type new shares. Then wait, and do it all again to see if it helped. Most people do it
rarely, so traffic keeps flowing to offers that stopped performing.

**Stats & Trends put the evidence next to the lever.** Each offer row shows how it performed
and which way it is heading, in the same place you change its share. Measure → decide → change
→ measure becomes one screen.

### Why that makes the product valuable

A split between offers is a classic **explore / exploit** problem (the "multi-armed bandit"):
most traffic should go to the offer that earns most (exploit), while a smaller part keeps testing
the others, because offers change (exploit the best, explore the rest). Shares are exactly that
allocation. Without stats the editor only *executes* the allocation; with stats it *informs* it.

Illustrative arithmetic (sample numbers, the same as on the design canvas):

| Offer | Share | Clicks / week | EPC (earnings per click) |
|---|---|---|---|
| A | 34 % | ~3,000 | $0.89 |
| B | 33 % | ~2,900 | $0.58 |
| C | 33 % | ~2,900 | $0.66 |

Moving 10 points of share from B to A moves about 880 clicks a week from earning $0.58 each to
earning $0.89 each: about **+$270 a week** from one edit, on the same paid traffic, **if A's EPC
holds** as it gets more clicks (caps, audience depth and payout changes can lower it). The gap
itself is an estimate from a week of data, which is why the move is partial, and why the next
week's numbers on the same screen tell you whether to continue (explore / exploit again).

The trend keeps the buyer honest in both directions. B's `▼ −17 %` week over week sounds
alarming, but on about 90 vs 75 conversions it is within normal noise (Rule 3), and the screen
says so instead of drawing a red arrow. That is the value: better use of traffic the buyer has
already paid for, without chasing noise.

What the feature deliberately does **not** do (yet): pick the shares for you. It shows the
evidence; the buyer decides. Automatic suggestions are a possible later step (§ 9).

---

## 2. What the user sees

Designs: canvas *Campaign Editor Design*, artboard **2 · Editor** (live columns, period switch,
metric tweak) and artboard **4 · Stats & trends** (every cell state and the maths).

- **Stats period** switch above the table: Today · 7 days · 14 days · 30 days. "7 / 14 / 30
  days" are **complete days** (yesterday and before), so the 7-day stats are the same days as
  the trend's newest week. "Today" is the partial day so far and carries the caption "today:
  mostly pending".
- **Stats column**, per offer in a flow:
  - the main metric in bold (e.g. `EPC $0.91`);
  - `2,980 clicks · CR 5.1 %`;
  - `18 % still pending`: the share of this offer's conversions the call centre hasn't decided
    yet, i.e. how much of the EPC is not yet certain;
  - `34 % of this flow's clicks went here (over the period)`: the split Keitaro actually
    delivered.
- **Trend column**: a 14-day sparkline of the main metric, plus the change of one settled week
  against the week before (`▲ +24 %`, `▼ −38 %`, `within noise`), with each week's conversion
  count beside it (`90 → 75 conv.`). Up is blue, down is orange; they also differ in lightness
  and arrow direction, so they don't rely on colour alone. The last 2 days of the sparkline are
  drawn **lighter**: still filling in.
- **Flow header**: flow totals for the period (`7 days: 8,790 clicks · CR 4.0 % · EPC $0.71`).
- **States**: loading; "No clicks in 7 days"; "New: no traffic yet" (added, not pushed); "Not
  enough traffic" for the trend; removed offers keep their history, greyed; "Stats unavailable"
  banner when the report fails. Editing and pushing work in every state.

---

## 3. The numbers, and how they are calculated

### Where they come from

Keitaro records every **click** and, via **postbacks** from the affiliate network, every
**conversion** and its money. Its report API aggregates both. Conversion statuses
([Keitaro glossary](https://docs.keitaro.io/en/glossary.html)):

- **lead**: the visitor signed up or ordered (for COD offers: filled in the form);
- **sale**: the action you get paid for (for COD: the order was confirmed by the call centre);
- **rejected**: the network or the buyer turned it down;
- **trash**: junk (duplicates, fake data).

### The metrics

Definitions follow Keitaro's glossary so our numbers match what the buyer sees in Keitaro.

| Metric | Formula | What it answers |
|---|---|---|
| **Clicks** | count of clicks (total, not unique) | how much traffic the offer got |
| **Observed split** | offer clicks ÷ all the flow's clicks | did Keitaro deliver the share I set? |
| **CR** (conversion rate) | (leads + sales) ÷ clicks | how often a click turns into a lead or a sale |
| **EPC** (earnings per click) | (lead revenue + sale revenue) ÷ clicks | what one click is worth, counting pending money |
| **Pending share** | leads ÷ (leads + sales + rejected) | how much of the result the call centre hasn't decided yet |
| **Confirmed EPC** | sale revenue ÷ clicks | what one click is worth, counting only money that is certain (not shown) |
| **Approve %** | Keitaro: how many leads move to sale | how many orders survive the call centre (not shown) |

`leads`, `sales` and `rejected` count conversions **currently** in that status: when the call
centre confirms an order, it moves from leads to sales; when it refuses one, from leads to
rejected. Keitaro's `conversions` is leads + sales (rejected is not included), so CR as defined
here matches Keitaro's own CR. Trash is excluded everywhere.

Clicks are total clicks, as in Keitaro's CR and EPC. Bot clicks inflate every offer's clicks
roughly equally, so they lower all the numbers but hardly change how offers compare.

**EPC is the number that compares offers fairly.** Offers pay different amounts per conversion,
so a higher CR does not mean more money: an offer converting 3 % at $25 earns more per click
(EPC $0.75) than one converting 5 % at $10 (EPC $0.50). That's why it is the proposed main
metric (settled: EPC main, CR second).

### Rule 1: add up first, divide once

Every ratio is computed from **summed counts over the whole period**, never by averaging daily
ratios. Example: Monday 1,000 clicks at CR 5 %, Tuesday 10 clicks at CR 30 %. The average of the
two daily CRs says 17.5 %; the truth is 53 conversions ÷ 1,010 clicks = **5.2 %**. Averaging
ratios gives a quiet day the same weight as a busy one: a weighting error, and the main way
dashboards end up showing wrong numbers.

So the app asks Keitaro only for countable things (clicks, conversions by status, revenue) and
derives CR, EPC and the pending share itself.

### Rule 2: zero is not a rate

0 clicks gives no CR at all ("No clicks"), never "CR 0 %". A rate of nothing is unknown, not zero.

### Rule 3: small numbers lie

3 conversions from 40 clicks is a 7.5 % CR, but one more or one fewer conversion swings it by
2.5 points. What sets the noise in CR and EPC is the number of **conversions**, not clicks: with
c conversions, the relative noise is about 1/√c (3 conversions ≈ ±58 %, 100 ≈ ±10 %). A week
over week change compares two such numbers, so its noise is about √(1/c₁ + 1/c₂). Therefore:

- **Stats** always show, with the click count beside them so the volume is visible.
- **Trend** needs **at least 100 clicks in each of the two weeks**; below that it says "Not enough
  traffic".
- **Noise band**: a change smaller than **2 × √(1/c₁ + 1/c₂)** reads "within noise", where c₁, c₂
  are the two weeks' conversions (leads + sales). Each week's conversion count is shown beside
  the arrow. Examples: 90 vs 75 conversions → band ±31 %, so −17 % is within noise; 900 vs 750
  → band ±10 %, so −17 % is a real drop. A week with 0 conversions has no band and reads "Not
  enough traffic".

This is a rough noise band (it assumes each offer's payout is roughly fixed, so EPC is as noisy
as its conversion count), not a significance test (§ 9). It is enough to stop the screen from
drawing an arrow on noise.

### Rule 4: per flow, not just per offer

The same offer can sit in two flows with different audiences, so numbers are kept per
(flow, offer) pair.

### Rule 5: what the flow totals contain

- The flow's clicks are **every click the flow got**, including report rows with no offer (for
  example a visitor who left a landing page before reaching an offer). They are the denominator
  of the observed split, so the offers' splits may sum to less than 100 %.
- **Removed offers** stay in the flow totals for the days they were in the flow, and show as
  "removed".
- **The observed split is over the period.** If the shares were changed inside the period, the
  split is a mix of the old and new shares and won't match the current ones.
- Keitaro can keep sending a **returning visitor** to the offer they saw before, so the split
  of total clicks can differ from the share set even when rotation works.
- **Flow EPC is a mix.** It is the share-weighted blend of the offers' EPCs, so it moves when
  you change shares even if no offer performs differently. Offers in a flow are compared with
  each other; the flow total is context, not a performance signal.

### The trend and the "lag"

**Trend** = the main metric over **days −9 to −3** against **days −16 to −10** (day −1 is
yesterday). Today is excluded because it isn't over, and the 2 most recent complete days are
excluded from the percentage because their conversions are still arriving (below). Both weeks
are then equally settled. The sparkline still draws all 14 days up to yesterday, the last 2
lighter. The price: the arrow is 2 days older than the chart.

**Why recent days are provisional.** By default Keitaro files a conversion under the **day of the
click**, not the day the postback arrived
([report by conversion date](https://docs.keitaro.io/en/reports/conversion-day-report.html)).
With COD offers, a lead becomes a sale days later, when the call centre confirms it:

```
Day 0    1,000 clicks → 40 leads,  0 sales,  0 rejected   Confirmed EPC $0.00
Day +2   same day:      22 leads, 18 sales,  0 rejected   Confirmed EPC $0.36
Day +5   same day:       0 leads, 26 sales, 14 rejected   Confirmed EPC $0.52  (final)
```

So the last few days of any chart keep changing after the fact, and every metric moves:
- **CR** can only fall: a rejected lead leaves leads + sales (40 → 26 conversions above).
- **EPC** can rise or fall, depending on the offer: if the network books money on the lead,
  EPC starts high and drops as leads are rejected; if it pays only on the sale, EPC starts near
  zero and rises like Confirmed EPC. Which applies is per offer and not visible in the report,
  which is why each offer shows its **pending share**: the higher it is, the less final its EPC.

The design draws the last 2 days of the sparkline **lighter** to say "still filling in", and
leaves them out of the trend percentage. (A Keitaro admin can switch the tracker to
conversion-date reporting; then past days stop changing, but conversions land on the day they
arrive rather than the day of the click. We assume click date, Keitaro's default; see Decisions settled.)

**Testing does not wait for lag**: the fake tracker's clock and approvals are ours (§ 4).

---

## 4. Approach (no implementation detail)

- **One report per campaign**, grouped by flow, offer and day, countable measures only, covering
  the longest window needed (30 days for the 30-day view, else 14 for the trend). Every column
  is cut from that one answer.
- **Stats sit beside the editor, not inside it.** They are read-only, loaded separately, never
  saved, and never part of the staged edit state. A refused or slow report shows a banner;
  editing and pushing are unaffected. They reload after Fetch, after Push and when the period
  changes, never on a share edit.
- **The calculation is pure**: counts in, numbers out, testable without a network.
- **Testing on two trackers:**
  - **The fake tracker with synthetic traffic** carries the functional testing. Each fake offer
    gets a conversion rate, payout and approval rate (defaults chosen from a fixed seed, so the
    same setup always gives the same numbers; any of them can be overridden). A fake-only control
    simulates N days of traffic, split by each flow's **current** shares. Approvals arrive
    instantly by default; an optional delay reproduces the lag on purpose. That covers every
    state, several offers that disagree on CR versus EPC, and the full loop: push a new split,
    simulate a week, watch the observed split and the trend move.
  - **The real tracker** (one offer, no traffic) proves the plumbing: the request is accepted,
    the answer parses, and a real campaign shows "No clicks" cleanly rather than an error.

---

## 5. Research notes (Keitaro report API)

Sources: Keitaro's Admin API spec
([admin-api.docs.keitaro.io](https://admin-api.docs.keitaro.io/), `POST /report/build`) and
read-only probes with our key, limited to campaigns this app created.

### Verified on the live tracker (read-only, 2026-11-20)

- The API key may read reports (200).
- Request: `range` (`interval`, or `from`/`to`, plus `timezone`), `dimensions`, `measures`,
  `filters` (`name`, `operator`, `expression`), `sort`. `metrics` is accepted as a synonym of
  `measures` (the spec's own example uses `metrics`, its schema says `measures`).
- Filters `EQUALS` / `IN_LIST` on `campaign_id` work.
- Response: `{"rows": [ {column: value, …} ], "total": n}`. Rows are objects keyed by column
  name (the spec wrongly types them as strings). No dimensions → one totals row.
- Unknown column → 400 listing all 183 columns. Among them: `stream_id`, `offer_id`, `day`,
  `clicks`, `campaign_unique_clicks`, `conversions`, `leads`, `sales`, `rejected`, `trash`,
  `approve`, `revenue`, `lead_revenue`, `sale_revenue`, `confirmed_revenue`, `cost`, `cr`, `epc`,
  `epc_confirmed`.

### Assumed (not observable without traffic)

- **A1.** Grouped rows carry `stream_id`, `offer_id`, `day` (as `YYYY-MM-DD`); ids and money may
  come as numbers or numeric strings, so parsing accepts both.
- **A2.** The range's end date is included.
- **A3.** `revenue` = lead + sale revenue (as in Keitaro's EPC formula). To avoid depending on
  it, the app requests `leads`, `sales`, `rejected`, `lead_revenue` and `sale_revenue` and adds
  them up itself. (Corrected 2026-11-20: an earlier draft assumed `conversions` includes
  rejected; Keitaro's glossary defines it as lead + sale, so it doesn't.)
- **A4.** Days are cut in the request's `timezone`.

### The "Flow 1 check" (attempted 2026-11-20, blocked)

The plan was to see real grouped rows without sending traffic to the offer: a throwaway campaign
whose GEO is the user's own country, so the forced Flow 1 catches the clicks and redirects to
google.com. It could not run: **the tracker's only domain has no DNS record**, so no campaign
link can receive a click from anywhere. A request sent straight to the server was refused (409).
The campaign was archived. A1, A2 and A4 stay assumptions until a domain resolves; then the
check takes five minutes.

---

## 6. Decisions settled (2026-11-20 conversation)

- Stats and trends are the next feature; push preview and push history are deferred (no real
  tracker traffic to justify them yet).
- Functional testing runs on the fake tracker with synthetic traffic, lag optional and off by
  default; the real tracker is used for contract and "no clicks" checks only.
- Real-row verification waits for a resolving domain; no workaround against the shared tracker.

- **Q1 → Metrics:** EPC is the main number, CR the second. Approve % and Confirmed EPC are
  not shown for now.
- **Q2 → Timezone:** one fixed timezone cuts days, set in backend config (default UTC). Set it
  to the tracker's own timezone so day edges match what the buyer sees in Keitaro.
- **Q3 → Currency:** `$`. This assumes the tracker reports in USD.
- **Q4 → Thresholds:** a trend needs ≥ 100 clicks in each week; |change| < 5 % reads "flat".
  *Revised after the skeptic review, below: the 5 % band is replaced by the noise band.*
- **Q5 → Attribution:** assume Keitaro's default, click date. Recent days may still change, so
  the trend skips today and draws the last 2 days lighter. If the tracker turns out to report by
  conversion date, only the lighter tail and its label change; the maths stays.

**Skeptic review (2026-11-20).** An adversarial review of this vision went metric by metric.
Folded in, with the user's approval:
- CR = (leads + sales) ÷ clicks, matching Keitaro's glossary; A3 corrected.
- The trend compares days −9…−3 with −16…−10, so both weeks are equally settled.
- "Flat" becomes "within noise": |change| < 2 × √(1/c₁ + 1/c₂) on conversions, with the counts
  shown; the 100-click floor stays.
- Each offer shows its pending share; the claim that EPC lags less than Confirmed EPC was
  dropped (it depends on the offer's payout model).
- The lead-to-sale illustration shows statuses moving; Approve % has no made-up formula.
- Periods other than Today are complete days; Today is captioned.
- Flow totals and the observed split are defined (Rule 5).
- The value example uses a smaller shift and "if EPC holds".
- Not taken: a flow-level trend beside each offer's trend (more scope than value for now).

## 7. Open questions

None. All five were answered on 2026-11-20 (see above).

## 8. Decisions Log

<!-- Owner's hand only. Format: YYYY-MM-DD: context, problem, decision (mark overrides/rejections). -->

## 9. Out of scope (for now)

- Suggesting or applying shares automatically (a bandit-style "rebalance by EPC" button).
- Cost, profit and ROI: they need cost data from the traffic source, which this tracker may
  not have.
- Statistical significance tests beyond the volume floor and the rough noise band (e.g.
  confidence intervals on CR, sequential testing).
- Alerts ("offer B dropped 30 %"), landing-page stats, breakdowns by country, device or sub-id.

## 10. Further reading

Keitaro:
- [Glossary](https://docs.keitaro.io/en/glossary.html): official formulas for CR, EPC, ROI,
  CPA, Approve %, and the conversion statuses.
- [Report by conversion date](https://docs.keitaro.io/en/reports/conversion-day-report.html):
  click date vs conversion date, the source of the lag.
- [Custom report](https://docs.keitaro.io/en/reports/custom-report.html) and
  [Trends](https://docs.keitaro.io/en/reports/trends.html): the same data in Keitaro's own UI.
- [Admin API reference](https://admin-api.docs.keitaro.io/): `POST /report/build`.

The statistics behind the rules:
- Evan Miller, [How Not To Sort By Average Rating](https://www.evanmiller.org/how-not-to-sort-by-average-rating.html):
  why a rate from a few events can't be trusted (Rule 3).
- Evan Miller, [How Not To Run an A/B Test](https://www.evanmiller.org/how-not-to-run-an-ab-test.html):
  why checking too early and too often misleads.
- [Simpson's paradox](https://en.wikipedia.org/wiki/Simpson%27s_paradox): why a blended total
  (like flow EPC) can move opposite to every part of it (Rule 5).
- [Multi-armed bandit](https://en.wikipedia.org/wiki/Multi-armed_bandit): the explore/exploit
  framing of offer shares (§ 1). Book: John Myles White, *Bandit Algorithms for Website
  Optimization* (O'Reilly, 2012).
