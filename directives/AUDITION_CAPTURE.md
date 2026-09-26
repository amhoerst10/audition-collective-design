# Directive: Audition Capture & Database Sync

## 1. Purpose

This directive governs how the agent audits orchestra websites, extracts audition data, compares it to the live database, and outputs structured JSON describing every proposed change. It defines the full workflow, fallback strategy, naming conventions, and output schema.

---

## 2. Workflow (in order)

### Step 1 — Pull Current DB State

Before touching any website, query the database for **all existing audition records** for the orchestra being processed.

```python
SELECT id, position, instrumentation, application_deadline, preliminary_audition, final_audition
FROM auditions
WHERE orchestra_id = <id>
```

Store this as `db_state`. If the only record is `"No auditions reported at this time"`, treat `db_state` as effectively empty.

Also check `orchestras.scrape_flags` / `orchestras.scrape_notes` for this org before scraping (see Step 1B below) — if a known quirk is on file, skip straight to the right approach instead of rediscovering it.

---

### Step 1B — Check the Site-Quirks Registry First

`orchestras` has two internal-only columns (never exposed in `view_auditions_with_orchestra` or on the public site) used to remember scraping quirks across audit cycles, so the same site doesn't get rediscovered from scratch every pass:

- `scrape_flags` — short comma-separated tags, e.g. `JS_ONLY`, `PDF_LINKS`, `CAPTCHA_BLOCKED`, `WIX`
- `scrape_notes` — free-text explanation of the quirk and the known workaround

Known tag meanings:
| Tag | Meaning | What to do |
|-----|---------|------------|
| `JS_ONLY` | Static scrape (Firecrawl/requests) returns nav/menu only, real content is JS-rendered | Go straight to the Chrome browser fallback (Step 2B); for a stubborn one, pull `document.body.innerText` via `javascript_tool` rather than `get_page_text` |
| `PDF_LINKS` | Audition dates/positions live only inside a linked PDF that won't render inline | Fetch/read the PDF directly rather than expecting the page text to contain the details |
| `CAPTCHA_BLOCKED` | Firecrawl/static requests hit a reCAPTCHA or bot-check wall | Use the Chrome browser fallback — it works fine live even when scraping is blocked |
| `WIX` | Wix-built site whose real nav links are hidden from static scraping | Browser fallback required to find the real audition URL; the top-level URL alone may 404 statically even though the site is live |

**When you discover a new quirk during a normal audit pass, write it back:**
```sql
UPDATE orchestras SET scrape_flags = 'JS_ONLY', scrape_notes = '<what you found and the workaround>' WHERE id = <id>;
```
Append to existing flags with a comma rather than overwriting if the org already has one. This is how the registry grows — every agent that hits a new quirk should leave it flagged for the next pass, not just work around it silently.

---

### Step 2 — Scrape the Live Audition Page (Firecrawl First)

Use `execution/firecrawl_tool.py` with the orchestra's `url` from the `orchestras` table.

```python
result = firecrawl_scrape(url, formats=["markdown"])
markdown = result['data']['markdown']
```

**If Firecrawl succeeds:** proceed to Step 3.

**If Firecrawl fails or returns empty/unusable content** (token exhaustion, timeout, blocked):
- Log the failure reason
- Fall back to **Step 2B**

---

### Step 2B — Fallback: Claude Chrome Extension

> **Note:** The Chrome extension (`mcp__Claude_in_Chrome__*`) must be installed and connected before this fallback is available. If it is not yet installed, flag the orchestra as `STATUS: NEEDS_MANUAL_REVIEW` and move on.

Use the Chrome extension tools to navigate to the URL and extract page text:

1. `navigate` to the orchestra's audition URL
2. `get_page_text` to extract visible content
3. Use the extracted text as `markdown` and continue to Step 3

Log that this orchestra required the Chrome fallback.

---

### Step 3 — Analyze the Page Content

Read the scraped content and identify all audition listings. Look for:

- **Position names** (see Section 4 for naming conventions)
- **Instrumentation** (instrument family or specific instrument)
- **Application deadline** (date by which materials must be submitted)
- **Preliminary audition date** (first round, sometimes called "Preliminary" or "Round 1")
- **Final audition date** (final round, sometimes called "Finals" or "Round 2")

If **no auditions are mentioned** — the page says something like "no current openings", "check back later", is completely blank, or only lists past seasons — mark as `NO_AUDITIONS`.

If the page is **ambiguous** (audition language present but no specific positions or dates), mark as `AMBIGUOUS` and note what was found.

### Step 3B — Cross-Check Before Accepting a No-Dates Finding

Before finalizing any record with all date fields NULL (TBD, rolling submission, or no-openings cases), do a general web search cross-check (e.g. a plain web search for "<orchestra name> auditions <instrument>") rather than relying solely on the one scraped URL. Two failure modes this catches:

1. **The scraped URL isn't the authoritative page.** A generic "audition application form" page may only be a submission form with a stray/stale instrument dropdown left over from a past posting, while a separate dedicated "Auditions" page on the same site holds the real, current, authoritative status. When a site has multiple audition-related pages, prefer whichever one explicitly states current status ("no openings at this time" / lists a real date) over one that's just a bare form.
2. **The primary scrape missed real content the wider web has indexed.** If a cross-check search surfaces specific dates or details the direct scrape didn't find, investigate further — but also verify those dates against the *current* live page before trusting them, since search engines and AI-generated summaries can surface stale/cached data from a prior season. When the live page and an external search disagree, the live page wins — but only after confirming you're looking at that site's actual authoritative page, not a form/dropdown remnant.

If, after cross-checking, the record is still genuinely dateless (TBD/rolling), proceed as normal per Section 5's rules for those cases.

---

### Step 4 — Compare Live vs. DB

For each position found on the live page:

| Scenario | Action |
|----------|--------|
| Position exists in DB with **matching dates** | `ACTION: STABLE` |
| Position exists in DB but **dates have changed** | `ACTION: UPDATE` |
| Position found live but **not in DB** | `ACTION: INSERT` |
| Position in DB but **not on live page** and deadline has passed | `ACTION: PURGE` |
| Position in DB but **not on live page** and deadline is future/unknown | `ACTION: FLAG` — do not auto-delete |
| Page has no auditions, DB has placeholder | `ACTION: STABLE` |
| Page has no auditions, DB has real records | `ACTION: FLAG` — possible expired records |
| Page is unreachable | `ACTION: SKIP` — log and move on |

---

### Step 5 — Output JSON

Every orchestra processed must produce a JSON block in this exact schema:

```json
{
  "orchestra_id": 67,
  "orchestra_name": "Alabama Symphony",
  "url": "https://alabamasymphony.org/auditions/",
  "scrape_method": "firecrawl | chrome_extension | failed",
  "scrape_timestamp": "2026-06-13T14:00:00",
  "status": "CHANGES_FOUND | NO_CHANGES | NO_AUDITIONS | AMBIGUOUS | NEEDS_MANUAL_REVIEW",
  "overall_confidence": "HIGH | MEDIUM | LOW",
  "confidence_reasoning": "One sentence explaining the overall confidence level for this orchestra — e.g., 'Page was clearly structured with labeled fields' or 'Dates were buried in paragraph text with no clear labels'",
  "auditions": [
    {
      "action": "INSERT | UPDATE | STABLE | PURGE | FLAG",
      "position": "Principal Oboe",
      "instrumentation": "Oboe",
      "application_deadline": "2026-08-01",
      "preliminary_audition": "2026-09-15",
      "final_audition": "2026-09-16",
      "confidence": {
        "overall": "HIGH | MEDIUM | LOW",
        "position": "HIGH | MEDIUM | LOW",
        "dates": "HIGH | MEDIUM | LOW"
      },
      "notes": "Optional: what was ambiguous, what raw text was found, why a field was left null, or any red flags"
    }
  ],
  "db_before": [
    {
      "id": 110,
      "position": "Section Bass",
      "instrumentation": "Bass",
      "application_deadline": "2026-04-27",
      "preliminary_audition": "2026-05-11",
      "final_audition": "2026-05-11"
    }
  ],
  "directive_suggestions": [
    "Optional: if this orchestra revealed a gap in the directive — a naming edge case, a website pattern not covered, a rule that should be added — write it here. These get folded back into AUDITION_CAPTURE.md after the state run."
  ]
}
```

**Confidence scoring rules:**

| Score | Meaning |
|-------|---------|
| `HIGH` | Information was clearly labeled, unambiguous, and directly matches a known pattern (e.g., a table with "Position", "Deadline" columns) |
| `MEDIUM` | Information was present but required interpretation — e.g., dates mentioned in paragraph prose, position name needed normalization, or one field was missing and inferred |
| `LOW` | Significant ambiguity — e.g., page mentions auditions but no specific dates, or the position name doesn't map cleanly to standard titles, or the page structure was unusual |

**Per-field confidence:**
- `position`: How sure are we the position name is correct and normalized?
- `dates`: How sure are we the dates are accurate and correctly assigned (deadline vs. prelim vs. final)?

**Overall orchestra confidence** is the *lowest* of all field-level scores across all its auditions.

**Rules:**
- `db_before` always shows what was in the DB before any changes.
- `auditions` shows every position found on the live page, with its action.
- If `status` is `NO_AUDITIONS`, `auditions` should be an empty array `[]`.
- Dates must be ISO format (`YYYY-MM-DD`). If only a month/year is found, use the last day of that month as a conservative estimate and add a note.
- Never omit `db_before`. Even if it is an empty array, include it.
- Never omit `directive_suggestions`. If there is nothing to suggest, use an empty array `[]`.
- `notes` on any audition entry should include the **raw text snippet** from the page that the data was extracted from, so the human reviewer can verify the interpretation.

---

### Step 6 — Write to Database (after JSON is reviewed/approved)

For each entry in `auditions`:

- **INSERT**: `INSERT INTO auditions (orchestra_id, position, instrumentation, application_deadline, preliminary_audition, final_audition) VALUES (...)`
- **UPDATE**: `UPDATE auditions SET ... WHERE id = <existing_id>`
- **PURGE**: `DELETE FROM auditions WHERE id = <id>` — only after explicit confirmation
- **STABLE / FLAG**: No DB write. FLAG items are logged for manual review.

If no real auditions exist and no placeholder is present:
```sql
INSERT INTO auditions (orchestra_id, position, instrumentation)
VALUES (<id>, 'No auditions reported at this time', 'N/A')
```

**Placeholder & date field rules:**
- The exact and only accepted placeholder wording is: `No auditions reported at this time`
- Every orchestra must always have at minimum one audition record. If no auditions are found, the placeholder must be present.
- When inserting real auditions for an orchestra currently holding a placeholder, delete the placeholder as part of the same operation.
- When all real auditions for an orchestra are purged and no other real auditions remain, insert a placeholder to replace them in the same operation.
- If an orchestra has at least one real audition record (any position other than the placeholder), do NOT also insert a placeholder. The placeholder is only for orchestras with zero current auditions.
- `NULL` is the correct value for any date field (application_deadline, preliminary_audition, final_audition) that has not been announced. Never insert strings like "TBD", "N/A", or "Unknown" into date fields.
- `confidence` and `notes` used in the human-review report are **never uploaded to the database**. They exist only in the agent's output for the reviewer.
- **`last_verified_at` must be stamped on every INSERT and UPDATE**, e.g. `..., last_verified_at) VALUES (..., NOW())` or `UPDATE auditions SET ..., last_verified_at = NOW() WHERE id = ...`. This is an **internal-only** timestamp — it is not selected by `view_auditions_with_orchestra` and must never be exposed on the public site. Its purpose is to let future audit cycles run incrementally (only re-check records older than N days) instead of always doing a full state re-scrape from scratch.

---

### Step 6B — Maintenance Scripts (run between audit cycles, not mid-audit)

Three formalized scripts in `execution/` replace what used to be ad hoc SQL run by hand. Run these as a quick sweep before starting a new round of state audits, not as part of a single-orchestra capture:

- **`execution/find_expired_auditions.py`** — lists (or, with `--purge`, deletes) every real audition record whose relevant dates have fully passed. Safe to run anytime; always review the printed list before passing `--purge` on a fresh, unreviewed run.
- **`execution/find_duplicate_orchestras.py`** — three-pass duplicate/data-integrity scan: exact normalized name+state matches, shared URLs across different orchestras (a strong signal one of them has the *wrong* URL, not that they're the same org — verify before assuming a merge), and fuzzy name similarity within a state (mostly surfaces legitimately different orgs with similar names — e.g. "Allentown" vs "Altoona" — but worth a human glance each run).
- **`execution/check_orchestra_urls.py`** — cheap HTTP status sweep of every stored `orchestras.url`, optionally scoped with `--state <name>`. A non-200 here is a lead, not proof — some sites block bare HTTP requests even though they load fine in a real browser, so anything flagged still needs the Section 2C live-browser workflow before touching the DB.

---

## 2C. Broken/Incorrect URL Handling

If an orchestra's stored `url` returns a 404/4xx/5xx, redirects to an unrelated domain, or otherwise appears wrong:

1. Do NOT guess-fix the URL yourself as part of a routine data-entry pass.
2. Flag it and hand off to the QA agent, whose job is to search for and propose what it believes is the correct current URL for that orchestra's audition/careers page (checking the orchestra's main site navigation, a web search, etc.).
3. The QA agent's proposed replacement URL goes to the project manager (orchestrating agent) for approval before the `orchestras.url` column is updated — this is a schema-level change to a different table than `auditions`, so it follows the same never-auto-commit rule as any other DB write.
4. Until a replacement URL is approved, treat that orchestra as `NEEDS_MANUAL_REVIEW` for this cycle rather than guessing at audition content from a broken link.

---

## 3. Token / Rate Limit Handling

- Firecrawl has API rate limits. If a scrape fails with a rate limit error, wait 10 seconds and retry once.
- If the retry also fails, fall back to Chrome extension (Step 2B).
- Never silently skip an orchestra. Every orchestra must appear in the output JSON, even if `status: SKIP`.
- Process orchestras one at a time within a state, not in bulk, to avoid hammering Firecrawl.

---

## 4. Position & Instrumentation Naming Conventions

Orchestra positions follow a strict naming hierarchy. Always use these standardized names when inserting into the database.

### 4A. Position Title Format

`[Rank] [Instrument]`

### 4A2. Numbered Chair Titles

When a position is a numbered non-principal chair (a "stand partner" convention common in winds/brass, e.g. "Second Trumpet," "3rd Horn," "Horn 3," "Bassoon 2"), normalize to:

`[Nth] [Instrument]`

No "Chair" word, no parentheses — just the ordinal number directly followed by the instrument. The number can be written flexibly as it appears on the source (digits "3rd", spelled out "Third", or Roman numerals) — match the source's own style rather than forcing one format.

**Examples:**
- "Second Trumpet" → `2nd Trumpet`
- "3rd Horn" / "Horn 3" → `3rd Horn`
- "Bassoon 2" → `2nd Bassoon`
- "Assistant Concertmaster (3rd Chair)" (Iowa/Dubuque case) — Concertmaster-family ranks keep their own established format per the Concertmaster rank table below; this numbered-chair rule is for section instrumentalists, not Concertmaster titles.

### 4A3. The Word "Section" — Only When the Source Uses It

Do NOT prepend "Section" to a position as a default/filler rank. Only use the word "Section" in a position title if the source itself literally uses that word (case-insensitive match is fine, e.g. source says "SECTION VIOLIN" in caps).

- Source says "Section Violin" or "SECTION VIOLIN" → keep `Section Violin`.
- Source just lists "Violin" or "Violin — 5 positions" with no rank word at all → use the bare instrument name, `Violin` — do NOT invent "Section Violin".
- This applies retroactively as a correction target — many earlier-session records defaulted to "Section [Instrument]" without checking whether the source actually used that word; these should be corrected to match actual source wording when re-audited.

| Rank | Used For |
|------|----------|
| `Music Director` | Top conductor role |
| `Principal` | Section leader (1st chair) |
| `Associate Principal` | Second-in-command of a section |
| `Assistant Principal` | Third in command, some larger orchestras |
| `Principal 2nd` | Leader of the 2nd violin section specifically |
| `Section` | General section member (tutti) |
| `Extra / Per-Service` | Freelance/supplemental, not full-time |
| `Audition Roster` | General pool audition, no specific opening |
| `Concertmaster` | Violin-only rank. The section leader of the entire violin/string section (not just 1st violins) — leads tuning, walks on separately, distinct from "Principal Violin." Never used for any other instrument. |
| `Assistant Concertmaster` | Violin-only rank. Second-in-command to the Concertmaster — distinct from "Assistant Principal," which is the equivalent rank for every other section. Do NOT normalize to "Assistant Principal Violin" — it is a valid, standard rank in its own right. |
| `Associate Concertmaster` | Violin-only rank. Parallel to "Associate Principal" in every other section — sits between Concertmaster and Assistant Concertmaster in seniority at orchestras that use a three-tier violin leadership structure. Do NOT normalize away or merge with Assistant Concertmaster — both are valid, distinct ranks when an orchestra's page uses both terms. |

**Examples:**
- `Principal Oboe`
- `Associate Principal Flute`
- `Principal 2nd Violin`
- `Section Cello`
- `Section Bass`
- `Music Director`
- `Concertmaster`
- `Assistant Concertmaster`

### 4B. Instrumentation Field

The `instrumentation` field should contain the **instrument family or specific instrument** — not the full position title.

| Instrumentation Value | Used When |
|----------------------|-----------|
| `Violin` | Any violin position |
| `Viola` | Any viola position |
| `Cello` | Any cello position |
| `Bass` | Double bass |
| `Flute` | Flute (including Piccolo if not specified separately) |
| `Oboe` | Oboe (including English Horn if not specified) |
| `Clarinet` | Clarinet (including Bass Clarinet) |
| `Bassoon` | Bassoon (including Contrabassoon) |
| `Horn` | French Horn |
| `Trumpet` | Trumpet |
| `Trombone` | Trombone |
| `Bass Trombone` | Bass Trombone (often listed separately) |
| `Tuba` | Tuba |
| `Percussion` | Any percussion |
| `Timpani` | Timpani (often listed separately from Percussion) |
| `Harp` | Harp |
| `Keyboard` | Positions the source calls "Keyboard" (a general keyboard chair) |
| `Piano` | Positions the source calls "Piano" |
| `Celeste` | Positions the source calls "Celeste" |
| `Organ` | Positions the source calls "Organ" |
| `Piano & Celeste` (and similar doublings) | Do NOT collapse to `Keyboard` — preserve a named doubling verbatim when the source uses it. The Audition Board search splits it on " & " so the listing appears under each named instrument (Piano AND Celeste). Keyboard-family values are kept specific on purpose (project owner, 2026-09-26): "our searches need to be specific." Keyboard, Piano, Celeste and Organ always appear in the search dropdown even with no current listings. |
| `Multiple` | **Deprecated — do not use this value at all.** If the source names specific instruments (even several at once, e.g. "Violin, Viola, and Cello openings," or "Flute, Oboe, Clarinet" for a sub list), create one separate audition record per named instrument instead (same position/rank, different instrumentation each) — this applies even when several instruments share one combined audition event (e.g. one sub-list audition day covering six different instruments still becomes six separate records, one per instrument). If the source genuinely names NO instrument at all (a true blanket "accepting substitutes for all positions" with zero instruments specified), that is an AMBIGUOUS case per Step 3 — do NOT insert it; flag it instead rather than guessing or using a placeholder instrumentation value. |
| `N/A` | Placeholder records only |

### 4C. Opera-Specific Positions — Instrumentalists Only

**Project-wide scope rule: this database tracks paid INSTRUMENTALIST auditions only, regardless of the type of group or ensemble. Vocal/singer auditions are never in scope, anywhere — opera companies, symphony-affiliated choruses, or otherwise.**

For opera companies, only these instrumentalist-relevant positions are in scope:
- `Artistic Director` — instrumentation: `Conductor` (in scope — a conducting role, not vocal)
- `Repetiteur` — instrumentation: `Keyboard` (in scope — a pianist role, not vocal)

**Out of scope, do NOT insert:**
- `Chorus Member` (Voice) — vocal, excluded regardless of organization type
- `Young Artist` (Voice) — vocal training/fellowship programs, excluded regardless of organization type
- Any other singer/vocalist audition, at an opera company, a symphony-affiliated chorus/chorale, or any other ensemble

An opera company itself remains in scope for inclusion in the `orchestras` table ONLY if it has its own resident/contracted orchestra with instrumentalist auditions (same test as any other organization) — its vocal auditions simply aren't captured as `auditions` records, the same way a ballet company's dancer auditions aren't captured under Section 4D.

### 4D. Ballet & Dance Company Scope

Ballet and dance companies are in scope **only for their resident orchestra's instrumentalist positions** (Violin, Cello, Horn, etc. — same rank/instrumentation rules as any other orchestra). A ballet company qualifies for inclusion in the database only if it employs its own orchestra with musician auditions.

Do NOT insert:
- Dancer/performer auditions (out of scope regardless of company type — this was already established with opera-company dance auditions, and applies identically here)
- Vocalist auditions at a ballet/dance company, if any (out of scope for the same reason)

If a ballet company's site only advertises dancer auditions with no distinct orchestra/instrumentalist audition process, classify as out of scope entirely — do not add the organization to the `orchestras` table at all, not even as a placeholder.

### 4E. Determining Paid Status (Scope Criterion 1)

An organization qualifies for the database only if it (1) has a history of paying its musicians, and (2) publicly announces audition information on its own website — a currently-open audition is not required for inclusion, only evidence of both criteria.

For criterion 1 (paid), use these concrete signals rather than guessing from general "professional"-sounding language:

- **Positive evidence:** the audition listing itself states a per-service rate, salary, stipend, or similar figure (e.g. "$155/service," an annual base salary, a trial-week rate). This is the strongest, most direct evidence — prefer it over inferring pay from an orchestra's general self-description.
- **Disqualifying evidence:** the word "volunteer" appearing anywhere on the page or in the organization's description of its musicians. Treat this as definitive — do not include, regardless of how "professional" other language on the site sounds.
- **Also disqualifying, per the project owner (2026-09-25): "unpaid," youth orchestras, and student/training programs.** Youth orchestras (e.g. "APYO", "Youth Symphony"), school/festival student admissions (tuition, application fees, "side-by-side with faculty" — e.g. Aspen Music Festival's student programs), and university ensembles are not paid work and are never in scope. The same goes for any individual position a page labels "unpaid," even at an orchestra whose other positions are paid: capture only the paid positions. *Why this line exists:* Nashville Civic Orchestra's four rolling section auditions were entered even though the page said "This is an unpaid position" and the verifying agent had flagged them as unpaid. They were removed the same week.
- **Check the monitored URL, not just the organization.** An in-scope orchestra can still be tracked at the wrong page, e.g. Arkansas Philharmonic's stored URL pointed at its youth orchestra's audition page (`/apyoauditions/`) rather than the professional orchestra's. When a URL points at a youth, student, or education sub-program, find the orchestra's own musician-audition page instead.
- **Genuinely ambiguous** (no payment figure found, no "volunteer" language either — e.g. vague references to a mixed roster of "professionals," "faculty," and "students" with no dollar figures either way): do not guess. Add to the discovery master list (`.tmp/discovery_candidates_master.json`) as `PENDING_REVIEW` with the exact evidence quoted, rather than including or excluding on a hunch. Cross-referencing against other resources (union rosters, League of American Orchestras directories, etc.) to resolve these may happen in a future pass — for now, leave them pending rather than resolving unilaterally.

---

## 5. Edge Cases & Rules

| Situation | Rule |
|-----------|------|
| Position title not in the standard list | Use the closest match; add a `notes` field explaining the raw text |
| Position title uses an ordinal chair number instead of a plain rank (e.g. "Second Trumpet", "3rd Horn", "Bassoon 2") | Normalize per Section 4A2 to `[Descriptor] (Nth Chair) [Instrument]`. Do not treat the ordinal as an Associate/Assistant Principal rank — those are distinct, formally-titled leadership positions, not numbered stand chairs. |
| Suffix casing/wording varies from the approved list (e.g. "(contact to schedule)", "(roster)") | Suffixes are canonical strings, not free text — always normalize to the exact approved casing (`(Contact to Schedule Live)`, `(Video / Audio Submission)`, `(sub list)`) regardless of how the source site capitalizes it. Never insert a lowercase or reworded variant — except `(sub list)` itself, which is intentionally lowercase per the format below. |
| Orchestra advertises a PAID ongoing open sub/substitute list with no specific audition scheduled, for a named instrument | **"Paid" must be shown, not assumed** (project owner, 2026-09-25): include a sub list only if the page or a directly linked audition document states a payment structure (per-service rate, fee, union scale, "paid per service"). No stated payment structure → do not insert; subs "can be paid, but it's messy." Format as `[Instrument] (sub list)` — lowercase "sub list", no "Section" prefix unless the source itself says "Section." E.g. source lists "Flute, Oboe, Clarinet" for a substitute roster → three separate records: `Flute (sub list)`, `Oboe (sub list)`, `Clarinet (sub list)`. If NO specific instrument is named at all, this is an AMBIGUOUS case (see the `Multiple` deprecation above) — do not insert with a placeholder instrumentation. |
| Firecrawl (or any scraper) returns `403 Forbidden` | Treat as a strong signal to try the Chrome extension fallback (Step 2B) before concluding the URL is broken or the orchestra has no auditions — confirmed cases (El Paso Symphony, Houston Ballet, Milwaukee Symphony) had fully valid, current audition content behind a 403 that only a live browser could bypass. Do not treat a 403 alone as evidence for the Section 2C broken-URL workflow — that's for confirmed 404s/dead domains. |
| Audition requires live resume submission (no dates listed) | Insert with null dates; note "Ongoing / Rolling submission" |
| Page redirects to a general careers/employment page | Scrape that page; flag if no audition-specific content found |
| Orchestra has multiple locations or sub-ensembles | Create separate audition records per position |
| Audition is listed as "TBD" | Insert with null dates; note "Dates TBD" |
| Application deadline (materials submission cutoff) has already passed, but the audition date (preliminary or final) has not | **INSERT normally.** This is expected and correct — the application_deadline is just the materials-submission cutoff, not the end of the listing's relevance. The record must stay visible and searchable until the actual audition itself (the last of preliminary_audition/final_audition) has occurred. Never purge or reject solely because application_deadline is in the past. |
| All of a record's relevant dates have passed — deadline AND preliminary_audition AND final_audition (whichever exist) are all before today | This is the actual signal for staleness/PURGE consideration — not the application_deadline alone. Check the live page first: if the listing is gone, PURGE. If still shown live with no future dates, treat per Step 4's FLAG rule. |
| Position listed as "Audition by invitation only" | Insert with null dates; note "Invitation only" in report only — not uploaded |
| Page returns CBA/union contract tables and a PDF application link but no named open positions | Classify as NO_AUDITIONS — this is a general application hub, not a vacancy listing |
| Page shows an audition listing where ALL of its dates (deadline, preliminary, final) have passed | Do NOT insert. Treat as NO_AUDITIONS unless other current/future listings also exist. Many sites leave fully-expired listings up without removing them. (Note: application_deadline alone being in the past is NOT this case — see the row above.) |
| A scraped date looks potentially stale (e.g. surrounding page text like a footer copyright year predates the season, or the page otherwise reads as an old snapshot) | A copyright year or similar metadata is NOT on its own evidence that the audition date is stale — do not reject or downgrade confidence based on that alone. Instead, corroborate: check other pages/paths on the same site (season calendar, news/events page, PDF season brochure) for a matching or updated date. If corroborated, INSERT normally. If genuinely unconfirmable after checking at least one other page, do not insert or purge — mark `status: AMBIGUOUS` and `notes: "skip until confirmed — could not corroborate date across site"`, and leave the existing DB record (if any) untouched pending manual/future-cycle confirmation. |
| Page renders with only navigation/menu content (JavaScript-rendered site) | Firecrawl failed. Switch to Chrome extension. Known JS-only sites: Alabama Symphony (alabamasymphony.org) — always use Chrome extension for this site |
| Position listed as "POSTPONED to [Season/Period]" with no specific dates | INSERT with all date fields NULL |
| Opera Studio Artist program administered through a university partnership | Classify as NO_AUDITIONS — application goes through university, not the opera company |
| Chorus audition with no posted date (email signup / notify list only) | Classify as NO_AUDITIONS — do not insert a record without at least an application_deadline |
| Multiple openings for one position type (e.g., "Violin 1 (3)") | Create ONE DB record for the position; note quantity in the report only |
| "Doublebass" or "Double Bass" on site | instrumentation = `Bass` (the standard filterable category), but preserve "Double Bass" wording in the position title exactly as the source states it — do NOT collapse the title to just "Bass". E.g. source "Section Double Bass" → position `Section Double Bass`, instrumentation `Bass`. |
| "Resume Date", "Materials Deadline", "Submission Deadline" on site | All are synonyms for application_deadline |
| "Semi-Final and Final Auditions" given as one combined date (distinct from "Preliminary Auditions," which may list multiple dates) | The first preliminary date goes in preliminary_audition; the "Semi-Final and Final" date goes in final_audition — treat "Semi-Final and Final" as a synonym for the final round, same as plain "Final." |
| Position is "Librarian," "Principal Librarian," or any other administrative/staff role (not an instrumentalist or vocalist) posted alongside musician auditions on the same page | **Out of scope — do NOT insert.** This database tracks musician (instrumentalist/vocalist) auditions only. Librarian, personnel manager, operations, and similar staff postings are not musical positions regardless of how they're listed on the page. |
| Position is "Conductor," "Assistant Conductor," "Music Director," or any other podium/conducting role posted alongside musician auditions | **Out of scope — do NOT insert.** Conducting is not an instrumentalist or vocalist position. (Found and purged from the live DB on 2026-09-17 — a "Conductor" instrumentation value had slipped in.) |
| Recorded-only audition with a stated deadline | preliminary_audition and final_audition = NULL; application_deadline = the submission deadline |
| Only ONE live-audition date is given on the source (no separate rounds mentioned) | That single date goes in `final_audition`, NOT `preliminary_audition`. `preliminary_audition` is reserved for when the source explicitly describes multiple rounds (a preliminary round distinct from a later final round) — most commonly at larger orchestras. If the source only ever mentions one audition date, treat it as the final round regardless of how the source itself labels it (even if the site's own wording happens to say "preliminary"). |
| **Fixed audition date is published, but no separate application/materials deadline is stated** (e.g. "reserve a slot by emailing a resume" with no cutoff date given) | The audition date is real and known, so this is NOT a "TBD" or "Contact to Schedule Live" case (both of which are for when no date exists yet or auditions are scheduled entirely on demand). Instead: `application_deadline` = the audition date **minus one day**. Insert the position with a plain title (no suffix) using this computed deadline. |
| **A deadline field exists on the source but its value is a status word rather than a date** (e.g. the page literally shows "Deadline: CLOSED" instead of a date) | This is different from the row above — a real deadline clearly existed and has already passed, but the actual date isn't stated, so don't guess/compute one. Set `application_deadline` = NULL (we know a deadline happened, we just don't know when). The audition itself is still real and upcoming, so still INSERT normally with the known audition date in `final_audition` — a closed application window does not mean the position is unavailable, only that the paperwork cutoff has passed. |
| Orchestra holds auditions on an ongoing/rolling basis (year-round or all season), entirely on-demand, scheduled individually whenever a candidate reaches out — no fixed audition date exists at all | This is the existing `(Contact to Schedule Live)` case (see the table below) — confirmed distinct from the row above. The defining difference: here there is no set audition date on the calendar at all; the entire process (both scheduling AND the audition itself) is initiated by the candidate contacting the orchestra. |
| **Open position, formal audition — dates not yet announced (TBD)** | Position is listed, excerpt sheets may be linked, but no deadline or audition date is posted yet. INSERT using the plain position title with no suffix. All date fields NULL. Dates will be announced and updated in a future audit cycle. Example: "Concertmaster" |
| **Open position — contact to schedule live audition** | Orchestra asks candidates to reach out via email or phone to arrange a live audition. No formal deadline expected. INSERT using suffix `(Contact to Schedule Live)` appended to the position title. All date fields NULL. Example: "Section Violin (Contact to Schedule Live)" |
| **Open position — rolling recording/video submission** | Orchestra asks for a video or audio recording to be sent with no stated deadline. INSERT using suffix `(Video / Audio Submission)` appended to the position title. All date fields NULL. Example: "Section Cello (Video / Audio Submission)" |
| Distinguishing TBD vs Contact vs Rolling | **TBD** (plain title, NULL dates): A formal audition has been announced and dates will be posted — there is no contact mechanism to arrange it, just a wait for the announcement. **Contact to Schedule Live** → suffix `(Contact to Schedule Live)`: The page provides a phone number or email address as the mechanism to arrange the audition — no formal deadline or application portal exists. Any contact info (email or phone) paired with an open position triggers this suffix. **Rolling Submission** → suffix `(Video / Audio Submission)`: The page asks for a recording to be sent, with no stated deadline. The suffix is stored in the position title field in the DB — it is part of the record, not just a note. |
| One combined listing names two distinct numbered chairs of the SAME instrument, sharing one audition day/deadline (e.g. "Horn II & Horn IV" audition, or "Violin I & II Section Auditions" naming multiple open seats across both stands) | Split into one record PER named chair/section, all sharing the same dates. E.g. "Horn II & Horn IV" → two records: `2nd Horn` and `4th Horn` (both Horn, same deadline/final date). "Violin I & II Section Seats" → two records: `Section Violin` (Violin I) and `Section 2nd Violin` (Violin II), both same dates. This differs from the single-combined-title rule in Section 4A/4E (two roles named in one listing with one deadline = one position) — that rule is for genuinely fused single-title postings (e.g. a designated "Assistant Concertmaster/2nd Chair" role); this row is for a page that explicitly names two separately-seated chairs/stands under one shared audition event. Always check the sub-page/PDF linked from a summary listing — a top-level page may compress "Horn II & IV" into one heading while the detail page confirms two distinct chairs with distinct excerpt lists. |

---

## 6. State Processing Order

Process states alphabetically. Current status as of 2026-06-13:

| State | DB Count | Audit Status |
|-------|----------|--------------|
| Alabama | 7 orchestras | **Start here — fresh audit** |
| Alaska | 2 | Pending fresh audit |
| Arizona | 6 | Pending fresh audit |
| Arkansas | 7 | Pending fresh audit |
| California | 44 | Pending fresh audit |
| Colorado | 18 | Pending fresh audit |
| Connecticut | 5 | Pending fresh audit |
| Delaware | 2 | Pending fresh audit |
| Florida | 22 | Pending fresh audit |
| Georgia | 6 | Pending fresh audit |
| ... all remaining states | ... | Pending |

Previous work done by prior agent should be **treated as unverified** until re-audited under this directive.

---

## 7. Output Delivery

After each state is processed, deliver in this exact order:

### 7A. State Summary Header
- Total orchestras checked
- Breakdown by status: Changes Found / No Changes / No Auditions / Flags / Manual Review
- Scrape methods used (Firecrawl / Chrome extension / failed)

### 7B. "Things I'm Unsure About" (always comes second)
Bulleted list of any orchestra where:
- Overall confidence is MEDIUM or LOW
- The page returned thin/empty content
- An unusual site pattern was encountered
- A URL redirected or returned 404
This section exists even if the list is empty — write "None — all data was clear."

### 7B2. Full URLs Required in Every Proposal

Any proposal involving an orchestra — a new discovery candidate, a URL correction, or a flagged existing record — must always include the full URL(s) involved, not just the organization name. This applies to every agent's output, not just this section's table.

### 7C. Proposed DB Changes Table
Show only orchestras where something would change (INSERT, UPDATE, PURGE). Stable / no-audition orchestras are omitted from this table unless there is a note worth flagging.

Format — this table must always be rendered as a full markdown grid. Never collapse, summarize, or drop it:

| ID | Orchestra | Action | Position | Instrument | App Deadline | Prelim | Final | Confidence | Notes |
|----|-----------|--------|----------|------------|--------------|--------|-------|------------|-------|

- `ID` = orchestra_id from the orchestras table
- `Action` = INSERT / UPDATE / PURGE
- Dates in MM/DD/YYYY format for human readability. Use NULL (not blank) when no date exists.
- `Confidence` = HIGH / MEDIUM / LOW
- `Notes` = brief flag if something is unusual (e.g., "3 openings", "recorded only", "contact to arrange — email@org.com", "expired — pending purge")
- Every proposed change gets its own row — no combining, no summarizing rows
- Orchestras with no changes are listed in a separate sentence below the table, never as rows
- If no changes across the whole state, write: "No changes proposed for [State]. All orchestras stable or confirmed no auditions." — still render an empty table header so the format is preserved

### 7D. Approval Prompt
End with a clear statement of what will be written to the DB if approved, and any items being held for further review (e.g., Chrome extension follow-up).

The agent does **not** auto-commit changes. All DB writes require a human "go ahead" after reviewing the table.

---

## 8. Self-Annealing (Directive Improvement)

After each state run is approved and committed, the agent must:

1. Review all `directive_suggestions` collected from that state's JSON output
2. Determine which suggestions represent **reusable rules** (patterns likely to recur in other states) vs. one-off quirks
3. Propose additions or edits to this directive
4. Wait for user approval before editing this file

**Do not edit this directive mid-run.** Suggestions are collected during the run, applied after.

Common things that should trigger a directive suggestion:
- A website structure that required an unusual extraction approach
- A position title that doesn't fit the standard naming hierarchy
- A date format that wasn't in the expected pattern
- An orchestra that redirects to a PDF, ticketing page, or job board (e.g., Indeed, AuditionCafe, Submittable)
- An orchestra whose audition page is behind a login or paywall
- Any field that consistently comes back null across multiple orchestras (may indicate schema gap)
