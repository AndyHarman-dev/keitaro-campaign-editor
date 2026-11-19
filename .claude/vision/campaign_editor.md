# Vision — Keitaro Campaign Editor

> Living document. It consolidates *what* we are building and *how we will approach it*.
> It is deliberately **not** an implementation plan: no file-by-file steps, no code.
> Implementation plans live under `.claude/plans/` and reference this file.

---

## 1. Context — what Keitaro is and why this tool exists

**Keitaro** is a self-hosted ad tracker. Technically it is a *link router with a ledger*:

1. A media buyer buys traffic on a **traffic source** (Facebook, TikTok, Google Ads, push/pop
   networks…). The ad points at a **campaign URL** hosted on a **domain** parked in Keitaro,
   e.g. `https://track.example.com/aB3xYz`.
2. Every click hits Keitaro first. Keitaro records the click (geo, device, IP, sub-ids, cost)
   and decides where to send the visitor by walking the campaign's **flows** (streams).
3. The chosen flow redirects the visitor to an **offer** — the advertiser's product page,
   usually provided by an **affiliate network** — optionally through a **landing page**
   (pre-lander) first.
4. When the visitor converts (lead / sale), the affiliate network sends a **postback** back to
   Keitaro, tying revenue to the original click. Cost (from the source) vs revenue (from
   postbacks) per campaign / flow / offer = profitability.

### Object model (the parts this tool touches)

| Object | What it is | Why it exists |
|---|---|---|
| **Campaign** | Container: one tracking URL + an ordered set of flows. | One ad link → one campaign. |
| **Domain** | Host the campaign URL lives on. | Buyers rotate many domains; campaign URL = `domain/alias`. |
| **Group** | A folder for campaigns (also exists for offers/landings/domains). | Organisation, filtering, per-team access. |
| **Traffic source** | Template describing where traffic comes from. | Its parameters (sub-ids, cost, creative id…) get appended to the campaign URL so clicks carry source data. |
| **Flow (stream)** | A routing rule inside a campaign: *filters* (who) → *schema* (where). Types: `forced` (checked first, intercepts), `regular`, `default` (fallback). | Lets one link send different visitors to different places. |
| **Offer** | Global object: a destination URL + payout + affiliate network. Attached to flows with an integer **share %**. | Split-testing: a flow rotates traffic between its offers by share. |

**Terminology: flow = stream.** They are one object under two names. *Flow* is the current
name in the Keitaro UI and docs. *Stream* is the older name, and it is still used in the Admin
API (`/streams`, `stream_id`, `/stream_filters`) and in doc URLs. Keitaro's own docs label the
section "Campaigns and Flows (Streams)". In this project, prose and UI say **flow**. **Stream**
appears only where we quote the API (paths, fields, and the backend code that maps them).

### The campaign shape we create

```
Campaign  (domain, group, source preset)
├── Flow 1  — forced, filter: country ∈ {GEO}  → redirect https://google.com
└── Flow 2  — regular                         → offers: [OFFER_ID @ 100%]
```

Visitors from the given GEO are diverted to google.com; everyone else reaches the offer —
i.e. the GEO is excluded from the offer (e.g. AU → google.com, everyone else → the offer).

---

## 2. Product vision

One local web app, two capabilities, **one entry point**:

- **Campaign picker / creator** (landing screen)
  - Pick an existing Keitaro campaign → opens the **editor**.
  - Or create a new one: *name*, *GEO*, *offer* (autocomplete search over Keitaro offers) →
    campaign is created in Keitaro with the preset domain / group / source and the two flows
    above → user lands in the editor of the new campaign.
- **Campaign editor**
  - A table grouped by flow. Each flow that has offers renders as a header row
    (`Stream: Flow 2 (#2) · stream_id …`) followed by one row per offer.
  - Flows without offers are not parsed into rows; they are listed below the table by name
    only (`Stream: Flow 1`).
  - Columns: **Offer** (name, id, preview link) · **Share** (% + pin toggle) · **Stats** ·
    **Trends** · **Actions**. Stats and Trends are kept as visible placeholders (out of scope
    for now).

### The editing model — staged changes, explicit push

The app is **not** a live mirror of Keitaro. It keeps its own memory of every flow and offer
it has ever seen and treats Keitaro as a remote it *fetches from* and *pushes to*.

- **Fetch KT** pulls flows + offers from Keitaro and merges them into local state.
- **Remove** marks an offer *removed* locally: row greys out, share shows 0 %, the action
  turns into **Bring back**. Nothing is sent yet.
- **Add** (combobox with autocomplete over all Keitaro offers + **Add** button at the bottom
  of a flow) appends an offer to that flow locally. Nothing is sent yet.
- **Shares recalculate** on every local change: unpinned active offers split what pinned
  offers leave, equally.
- Once a flow has pending changes, the flow is visually marked as *dirty* and gets
  **Push to KT** and **Cancel**.
  - **Push** writes the flow's resulting offer list + shares to Keitaro.
  - **Cancel** discards every pending change since the last push/fetch.
- **External removals are preserved.** If an offer disappears from a flow in Keitaro
  (removed by someone in the Keitaro UI), the next Fetch does not drop it: it is shown as
  *removed* (greyed, 0 %, **Bring back**). Bring back + Push re-attaches it with the
  properties it had when we last saw it.

### Share & pin rules

- Shares are **integers** (Keitaro API: `share: integer`) and must total **100** across the
  flow's active offers.
- **Pin** freezes an offer's current share. Adds/removes never change a pinned share.
- Unpinned active offers split `100 − Σ pinned` equally; the integer remainder goes to the
  first rows in display order (matches the existing editor's behaviour: 3 → 34/33/33,
  75 over 2 → 38/37).
- Removed offers have 0 % and do not participate.

Observed in the existing editor: 4 offers at 25 %, pin one at 25 %, remove one →
the two remaining unpinned offers become 38 % / 37 %, the pinned one stays 25 %.

---

## 3. Approach (no implementation detail)

- **Stack (fixed):** FastAPI + SQLAlchemy (+ Alembic migrations). Python managed with `uv`.
  React + Vite + TS frontend, SQLite DB.
- **Keitaro access** only through the backend; the API key never reaches the browser.
  Key + tracker URL come from a gitignored `.env`.
- **Local DB is the source of truth for things Keitaro does not know about**: pins, pending
  (unpushed) changes, snapshots of offers we've seen in each flow (needed for Bring back and
  for "removed externally" detection).
- **Domain-first core:** share allocation (pins, equal split, rounding) and the
  fetch-merge / push-diff logic live in pure functions with unit tests; HTTP and DB are
  thin layers around them.
- **Push is safe by construction:** before writing a flow, re-read it from Keitaro and
  compare with what we last fetched. If it changed in the meantime, stop and ask instead
  of overwriting (Keitaro's flow update most likely replaces the whole offer list).
- **Verify against the live tracker before trusting the public API spec.** The target
  tracker runs Keitaro 10.3.x; the public OpenAPI describes the current version.

---

## 4. Research notes (Keitaro Admin API v1)

- Base: `https://<tracker>/admin_api/v1`, auth header `Api-Key: <key>`.
- Campaigns: `GET/POST /campaigns`, `GET/PUT /campaigns/{id}`, `GET /campaigns/{id}/streams`.
  Create requires `name` + `alias` (generate alias ourselves). Relevant fields: `domain_id`,
  `group_id`, `traffic_source_id`, `type` (`position` | `weight`).
- Flows: `POST /streams`, `GET/PUT/DELETE /streams/{id}`. Fields: `type`
  (`forced`/`regular`/`default`), `schema` (`landings`/`redirect`/`action`), `action_type`,
  `action_payload`, `filters[] {name, mode: accept|reject, payload[]}`,
  `offers[] {offer_id, share:int, state}`.
- Lookups: `GET /offers`, `GET /domains`, `GET /groups?type=campaigns`,
  `GET /traffic_sources`, `GET /stream_filters`, `GET /streams_actions`, `GET /stream_schemas`.
- Campaign preset: domain / group / source defaults come from `.env`
  (`KEITARO_DEFAULT_DOMAIN`, `KEITARO_DEFAULT_GROUP`, `KEITARO_DEFAULT_SOURCE`, by name);
  rotation *by position*, cost model CPC.

---

## 5. Decisions settled (scope interview, 2026-11-19)

| Topic | Decision |
|---|---|
| GEO input | **Several** countries (multi-select). One forced flow whose country filter holds all of them. |
| Domain / group / source | **Defaults from `.env`, overridable** in a collapsed "Advanced" section of the create form, with dropdowns loaded from the API. |
| Frontend | **React + Vite + TypeScript.** In production, FastAPI serves the built bundle. |
| Local DB | **SQLite**, schema managed by Alembic. |
| Bring back | Re-attach the offer to the flow. If the global offer was archived, restore it first. If it was purged, recreate it from our snapshot. |
| Share editing | The % is **editable inline**. Typing a value **auto-pins** that offer, and the unpinned offers rebalance around it. |
| Push conflict | **Block and re-fetch.** If the flow changed in Keitaro since our Fetch, Push is refused. Fetch merges the change and keeps pending edits on top. The user then pushes again. |
| Pin limits | **Auto-unpin**: when pins make the numbers impossible (pinned > 100, or everything pinned and total ≠ 100), the oldest pin is released automatically and the user is told which. |
| Push/Cancel scope | **Per flow + global.** Each dirty flow has its own Push/Cancel. The top bar shows Fetch when clean, and "Push all (n)" / "Cancel all" when anything is pending. |
| Extras | Include **View in KT** link, **Show all offers**, **offer preview** link. |
| Show all offers | Opens a searchable list of **every offer registered in Keitaro** (not only the ones in this campaign). Removed rows always stay visible in their flow. |
| Row order & remainder | Rows follow **Keitaro's order of offers in the flow** (as the API returns them); newly added offers go at the end. The +1 leftover points from integer rounding go to the first unpinned rows in that order, so the same input always yields the same shares. |

## 6. Open questions

- [ ] Tracker admin base URL → `.env`.
- [ ] Verify on the live instance: country filter name + payload format, redirect
      `action_type` for google.com, whether `domain_id` is accepted on create in 10.3, and
      whether `PUT /streams/{id}` with `offers` replaces or merges.
- [ ] Removing a pinned offer: does its pin go away with it, and does it come back on
      Bring back? Default: the pin is kept, dormant, and returns on Bring back; auto-unpin
      applies if the numbers no longer work.

## 7. Decisions Log

<!-- Owner's hand only. Format: YYYY-MM-DD: context, problem, decision (mark overrides/rejections). -->

## 8. Out of scope (for now)

- Stats and Trends columns (kept as placeholders).
- Landing pages inside flows, flow filters other than the GEO one, flow creation/deletion in
  the editor.
- Multi-user / auth (local tool).
