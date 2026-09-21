# Audition Collective — Design & Interactive Query Proposal

Companion wireframe: `audition-board-mockup.html` (static HTML, same folder).

---

## 1. Professional Design Improvements

### Benchmark observations
Serious industry boards (League of American Orchestras Job Bank, ROPA, ICSOM, individual orchestra HR/careers pages) share a consistent visual language: dark navy/charcoal + a single metallic accent (gold or brass, evoking instruments/concert halls), serif display type paired with a clean sans-serif for UI chrome, dense but legible data tables, minimal stock photography, and a restrained "institutional" tone rather than a consumer job-board feel (no bright primary colors, no rounded bubbly UI).

### Recommendations

**Typography**
- Headings: a serif such as **Georgia, Lora, or Playfair Display** — signals editorial/institutional credibility, matches orchestra program-note aesthetics.
- Body/UI: a neutral sans-serif — **Arial/Helvetica** or **Source Sans Pro** — for tables, filters, nav, buttons. Never mix more than these two families.
- Both are Google Fonts / system-safe, so no custom font licensing needed; Elementor's Global Fonts panel can set these once and they propagate site-wide.

**Color palette**
- Primary: deep navy `#1b2a3d` (header, footer, hero background)
- Accent: muted gold/brass `#b7893f` (links, active states, CTA borders) — used sparingly, never as a full-fill background except on primary buttons
- Neutral background: warm off-white `#f7f4ee` (not pure white — reads warmer/more editorial)
- Ink text: near-black `#22242a`, muted gray `#6b7280` for secondary text
- This is a 3-4 color system, implementable with Elementor's Global Colors so every widget inherits it automatically.

**Hero section**
- Full-width navy band, serif headline stating the value prop directly ("Live Orchestra & Opera Auditions, Tracked Daily"), one sentence of supporting copy in sans-serif, and 3 live stat counters (orchestras tracked / open auditions / closing this week). Stats can be an Elementor "Number Counter" widget or a simple WPDataTables aggregate query — either way it signals the board is actively maintained, addressing the #1 credibility risk for a niche directory (looking abandoned/stale).
- No stock photography of musicians — it reads as generic. If imagery is wanted later, a single monochrome/duotone concert-hall photo treated in the navy palette is the only place to add it.

**Layout**
- Single main content column, max-width ~1180px, consistent with the mockup — matches how ROPA/ICSOM structure their listings pages (no busy sidebars).
- Filter panel as its own bordered card above the results table, not inline with the table header — keeps the interaction model obvious and separates "query building" from "results."
- Section headers get a small gold rule/tick mark (see mockup `.filters h2::before`) — a small recurring device that ties hero, filters, and footer together without needing a heavier rebrand.

**Navigation**
- Flat top nav, 4 items max (Auditions / Orchestras / Resources / About) — resist adding more; niche boards succeed by being narrow and deep, not broad.
- Log In / Join Free as distinct, visually separated actions in the top-right, consistent with PMPro's existing account/login flow — do not bury membership CTAs in a dropdown.

**Implementation notes (Elementor + WPDataTables, no custom dev)**
- Elementor Theme Builder: set global colors/fonts once, they apply to header/footer templates and any Elementor-built pages.
- Hero + filter panel: standard Elementor sections/containers with the color/typography above — no custom code required.
- The results table itself is WPDataTables output embedded via shortcode inside an Elementor page/section, styled via WPDataTables' own "Custom CSS" per-table option (border colors, header background, zebra striping) to match the palette rather than fighting Elementor's page CSS.
- All of this is achievable by one person maintaining the site with the currently installed plugin stack — no new plugins needed for the visual layer.

---

## 2. Interactive Query Interface (WPDataTables + PMPro)

### Goal
Let free-tier members filter/search the `view_auditions_with_orchestra` view by the four DB "buckets" — **state, instrumentation, position/rank, deadline proximity** — without needing SQL or a developer, using WPDataTables' built-in filtering rather than a custom search page.

### Data source
Point the WPDataTables "MySQL query" data source directly at the existing view:
```sql
SELECT * FROM view_auditions_with_orchestra
```
No schema changes, no new tables. One computed column is added at the table level (not the DB): a `deadline_bucket` derived column using WPDataTables' formula/computed-column feature (or a `CASE WHEN DATEDIFF(application_deadline, CURDATE()) ...` expression in the query itself) that buckets each row into:
- `Closing This Week` (deadline within 7 days)
- `Closing This Month` (deadline within 30 days)
- `Open` (deadline further out or null/rolling)

This keeps "deadline proximity" as a real filterable column instead of asking members to reason about raw dates.

### WPDataTables filter configuration
WPDataTables supports **per-column dropdown filters** (its native "filtering" feature, no extra plugin) — configure these on the table:

| DB bucket | Table column | Filter type |
|---|---|---|
| State | `orchestra.state` | Dropdown select, populated from distinct values |
| Instrumentation | `auditions.instrumentation` | Dropdown select, populated from distinct values |
| Position / Rank | `auditions.position` (normalized rank prefix, per AUDITION_CAPTURE.md §4A) | Dropdown select — use the standardized rank tokens (Principal, Associate Principal, Assistant Principal, Section, Extra/Per-Service) rather than free-text position, so the filter stays a clean bucket instead of matching hundreds of unique title strings |
| Deadline proximity | computed `deadline_bucket` | Dropdown select (3 options above) |

Additional configuration:
- Enable global search box (free text) alongside the four dropdowns, for members searching by orchestra name.
- Default sort: `application_deadline` ascending (soonest deadlines first) — this is the single highest-value default for a job-seeking musician.
- Enable column sorting on Position and Deadline (visible sort arrows) so members can re-sort after filtering.
- Server-side processing should stay **on** given growth toward hundreds of orchestras — WPDataTables supports this out of the box, keeps the page fast as row count grows.
- Filters render as the dropdown row shown in the mockup, positioned above the table as a distinct "Filter Auditions" panel rather than tiny per-column filter boxes squeezed into the header — better for a non-technical audience and matches the wireframe.

### PMPro interaction — free vs. gated fields
Recommendation: **keep the query interface itself fully open to free members** — filtering/searching by state, instrument, rank, and deadline proximity is exactly the discovery function that makes the board worth returning to, and gating it would kill the core value loop before anyone converts.

Gate individual **detail fields**, not the search itself:
- Free tier sees: position, instrument, orchestra, state, deadline, prelim/final round dates, and the deadline-proximity badge — everything currently in the DB schema that answers "does this audition exist and when."
- Paid tier (Collective+) unlocks: a "Members Only" teaser column/cell (see mockup — `salary/contact` column shown as a locked badge for free users) which is really a placeholder for **fields not yet in the current schema** but flagged as a natural paid-tier expansion: direct HR contact info, salary/stipend ranges when published, excerpt-list/repertoire links, and saved-search email alerts.
- Mechanically in WPDataTables: use its **PMPro integration / conditional column visibility** — WPDataTables can hide specific columns based on the visitor's PMPro membership level, rendering a "Members Only — Upgrade" lock icon in that cell for non-members instead of the real value (shown in the mockup's `lock-tag` cells). This requires no new plugin, only configuring column-level visibility rules against the existing `wp_pmpro_membership_levels` table.
- Row-level gating (e.g., hiding entire premium-only listings) is not recommended — it would fragment the "one true feed" that makes the board trustworthy. Gate only extra fields, never the row itself.

### Why this split
This mirrors how LAO's own Job Bank and most trade job boards monetize: the listing (the thing people came for) stays free and indexable, while contact-level convenience and alerting are the upsell. It keeps free members as the SEO/traffic engine and reserves the paid tier for people who convert from "I found an audition" to "I want this to be effortless to track."

---

## Summary of concrete next steps
1. Set Elementor Global Colors/Fonts to the palette/type above.
2. Rebuild the hero section as an Elementor section matching the mockup.
3. Point a new WPDataTables table at `view_auditions_with_orchestra`, add the `deadline_bucket` computed column, and configure the four dropdown filters + global search.
4. Configure WPDataTables' PMPro column-visibility integration to gate only the future contact/salary column(s), leaving all current schema fields free.
5. Embed the table via shortcode inside the new page layout, styled with WPDataTables custom CSS to match the palette.
