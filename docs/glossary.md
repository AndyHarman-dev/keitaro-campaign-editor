# Glossary

Domain terms as the code and UI use them. Keitaro background: `.claude/vision/campaign_editor.md`.

| Term | Meaning |
|---|---|
| **Flow** | Keitaro's routing rule inside a campaign. The Admin API calls it **stream** (`/streams`, `stream_id`); only API-facing code says "stream". |
| **Offer row** | One offer inside one flow, as the editor sees it (`OfferRow`). Keyed by `offer_id`, never by Keitaro's link id. |
| **Share** | Integer percent of a flow's traffic an active offer gets. Active shares total 100. |
| **Base** | What Keitaro had at the last fetch or push, plus local memory (pins, remembered offers, archived flag). |
| **Pending op** | A staged user action not yet pushed: Remove, Bring back, Add, Set share, Toggle pin. |
| **Working** | `replay(base, pending)`: the state the editor shows. |
| **Dirty** | Working differs from base. Only dirty flows can be pushed or cancelled. |
| **Signature** | Ordered `(offer_id, share, state)` list as Keitaro returned it; compared before a push to detect changes made in Keitaro. |
| **Removed** | Row at 0 % that is not sent on push. *Removed locally* (pending Remove) or *removed in Keitaro* (gone on fetch). |
| **Archived** | The offer itself is archived/deleted in Keitaro. It cannot be restored; Remove forgets the row (local only). |
| **Pin** | A frozen share with an age (`seq`). Unpinned active rows split what pins leave. |
| **Dormant pin** | The pin of a removed row. It comes back with Bring back. |
| **Auto-unpin** | When pins cannot fit in 100 %, the oldest pin is released and the user is told. |
| **Push** | Writing a flow's working offer list to Keitaro (replaces the whole list). |
| **Fetch** | Reading flows from Keitaro into a new base; pending ops are replayed on top. |
