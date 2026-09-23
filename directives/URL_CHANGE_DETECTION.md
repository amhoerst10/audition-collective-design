# Directive: URL Change Detection

## Goal
Detect when an orchestra's audition page has meaningfully changed (a new posting,
an updated deadline, a removed listing) without requiring a human or agent to
manually revisit all ~400 orchestra URLs. This is "item 2" of the automation
roadmap, following the automated expiry-purge system ("item 1").

## Why not just hash the page?
An earlier attempt hashed page metadata (copyright year, "last updated" stamps)
and failed in both directions:
- **False positives**: a copyright year or auto-generated timestamp changes on
  every page load / every Jan 1, making the hash "change" constantly even when
  nothing about the actual audition listings changed. This trains a human to
  ignore the tool.
- **False negatives risk**: reacting to false positives by narrowing the hashed
  region too aggressively risks cropping out the exact area where a new
  audition listing would actually appear.

The fix: don't compare a bare hash. Extract and store the full cleaned body
text every run, strip known noise patterns first, and when the cleaned text
changes, generate a real diff -- not just a boolean "something changed" flag.
A human (or agent) reviewing a 3-line diff can instantly tell "that's just the
footer year" from "new Principal Oboe posting added," even when the noise
list isn't perfect yet.

## Inputs
- `orchestras` table: `id`, `name`, `state`, `url`
- `url_change_snapshots` table (one row per orchestra):
  - `orchestra_id`, `clean_text` (LONGTEXT -- full cleaned text from the last
    check), `content_hash` (sha256 of clean_text, cheap equality check),
    `last_checked_at`, `last_changed_at`
- `url_change_flags` table (one row per detected change):
  - `orchestra_id`, `detected_at`, `diff_summary` (unified diff of
    added/removed lines), `status` (`unreviewed` / `confirmed_real` /
    `noise_dismissed`), `reviewed_at`, `reviewer_notes`

## Tool
`execution/detect_url_changes.py`
- Fetches each orchestra's `url` (same polite GET + User-Agent header pattern
  as `check_orchestra_urls.py` -- reuse that pattern, don't reinvent it)
- Extracts visible body text via BeautifulSoup, stripping `<script>`,
  `<style>`, `<nav>`, `<header>`, `<footer>` tags outright
- Runs the cleaned text through the **noise denylist** (regex patterns below)
  to strip known-noisy substrings before hashing/diffing
- Normalizes whitespace (collapse multiple blank lines/spaces) so incidental
  reflow doesn't trigger false diffs
- Compares the new cleaned text's hash to the stored `content_hash`:
  - **No existing snapshot** (first run for this orchestra): store as
    baseline, no flag. We have nothing to diff against yet.
  - **Hash unchanged**: update `last_checked_at` only.
  - **Hash changed**: compute a unified diff (Python `difflib`), insert a row
    into `url_change_flags` with `status='unreviewed'`, update the snapshot
    (`clean_text`, `content_hash`, `last_checked_at`, `last_changed_at`).
- A non-200 response or fetch error is logged to console but does NOT touch
  the snapshot or create a flag -- same "needs live-browser check, not proof
  of anything" caution as `check_orchestra_urls.py`.

## Operational rule: any denylist change requires a FULL re-baseline

**Confirmed the hard way, 2026-09-22/23**: a new noise pattern added during a
flag-review session (the accessibility-form vocabulary heuristic below) was
too broad -- it matched a single common word alone (e.g. a standalone "Name"
line, an extremely common generic form-field label on totally unrelated
sites) instead of requiring the intended multi-word combination. Because
only the 2 specifically-affected orchestras' snapshots were cleared after
deploying that fix -- not all ~400 -- every other orchestra's stored baseline
still contained "Name" from *before* the new pattern existed. The next run
stripped "Name" from the freshly-fetched text (correctly, per the new
pattern) but compared it against an old baseline that still had it,
producing a false "content changed" diff on every site with a plain "Name"
label anywhere on the page. Result: ~40-60 false-positive flags across
unrelated orchestras over two nights, discovered only because the user asked
for a status check-in, not because anything alerted on its own.

**Rule going forward: whenever `NOISE_PATTERNS` or `clean_text_from_html()`
changes in any way, `TRUNCATE url_change_snapshots` and do a full re-baseline
run before the next scheduled cron fire.** A partial re-baseline of only the
"obviously affected" orchestras is not sufficient -- a noise-pattern change
can affect any orchestra whose page happens to contain matching text,
which isn't knowable in advance. Also: prefer regex patterns that require
multiple specific words/tokens together over single common words, even ones
that seem safe in isolation -- "Name" alone is common; "Concert Other,
Seating" together is not.

## Noise Denylist (living list -- update this as false positives appear)
Strip (case-insensitive) any line/substring matching:
- `©` or `Copyright` followed by a 4-digit year
- "Last updated," "Page generated," "All rights reserved"
- A bare 4-digit year adjacent to nothing else meaningful (standalone footer year)
- ISO 8601 timestamps on their own line (e.g. `2026-07-14T18:18:20+00:00`) --
  confirmed on the very first real test run (Alabama Symphony): WordPress
  leaks its post "modified" meta timestamp into visible body text, and this
  bumps on ANY content edit, not just audition-relevant ones
- CMS author bylines standalone on their own line (e.g. `richard-admin`,
  `admin`, "Posted by ...") -- also confirmed on the first test run
- **Gravity Forms anti-spam honeypot fields** -- confirmed on the first full
  408-orchestra scan (Atlanta Opera, Quad City Symphony, and others):
  Gravity Forms (a very common WordPress form plugin) injects a decoy field
  whose label RANDOMLY ROTATES on every single page load ("Name" / "Phone" /
  "URL" / "X/Twitter" / "Instagram" / "LinkedIn" / "Comments" / "Company" /
  etc), always immediately followed by the constant line "This field is for
  validation purposes and should be left unchanged." Both the random label
  and the marker line are stripped -- this is not page content and would
  otherwise flag nearly every Gravity-Forms site as "changed" on every run.
- Common CMS-injected noise: session tokens, cache-busting query strings that
  leak into visible text, "You are here:" breadcrumb trails that include a
  timestamp
- **"Page printed" server-rendered timestamps** -- confirmed on Portland
  Baroque Orchestra's page (e.g. "Printed 9/18/26 - 7:04:37"), rendered fresh
  on every single request and ticking every single check regardless of any
  real content change. This is the exact failure mode described in this
  directive's intro (hashing publication/print timestamps).
- **Accessibility-accommodation / ticket-request form fragments** --
  confirmed on North Carolina Symphony's employment page: a "Request
  Accommodations" form embeds one "Desired Concert" dropdown per upcoming
  show, each defaulting to whichever concert is next; as the calendar
  advances the default selection rotates, and text extraction fragments the
  surrounding labels into short word-soup lines (e.g. "Concert Other,
  Seating"). Stripped via a heuristic: a line made of 2-5 words drawn
  from a small known form-vocabulary set (concert, seating, preferred,
  accessible, other, name, desired, location, select, type, group) --
  **must require 2+, not 1+**: an earlier version matched a single word
  alone and wrongly stripped standalone "Name" labels (an extremely common,
  unrelated form field on other sites), causing a real false-positive
  regression across dozens of orchestras on 2026-09-22/23. See the
  "any denylist change requires a full re-baseline" rule below -- that
  regression is exactly why the rule exists.

**When a flag turns out to be noise during review**: add the specific pattern
that caused it to this list and to the script's `NOISE_PATTERNS`, mark the
flag `noise_dismissed`, and re-run a spot check to confirm it no longer fires.
This directive should grow this list over time -- that's the self-annealing
loop for this system specifically.

## Review / Investigation Trigger (future automation)
Once detection is proven reliable on a real batch:
1. `detect_url_changes.py` runs daily via a real scheduler (local machine or
   equivalent -- Hostinger shared hosting cannot run a Python job reliably,
   same constraint documented for the expiry-purge system).
2. A second scheduled pass (offset by ~1 hour) wakes an investigation agent
   whose job is: read all `url_change_flags` rows where `status='unreviewed'`,
   read each `diff_summary`, and for each one either:
   - Judge it real → **independently re-fetch and re-read the live page
     first** (a fresh agent call given only the URL, not the prior diff or
     summary) before writing anything to `auditions` -- a diff-based read is
     a hypothesis about what changed, not a verified fact about current
     reality, and this step has already caught real interpretation errors
     in production (see below). Only after independent confirmation, hand
     off to the existing 3-agent `AUDITION_CAPTURE.md` workflow to actually
     capture/update the listing, then mark `status='confirmed_real'`.
   - Judge it noise → mark `status='noise_dismissed'` and propose an addition
     to the Noise Denylist above for human sign-off
3. This keeps AI investigation scoped to only the handful of flagged sites per
   day, not all ~400 -- the deterministic diff step does the expensive part.

**Why the independent re-check step is mandatory, not optional** (confirmed
2026-09-23): a diff-based read correctly flagged Erie Philharmonic and
Nashville Civic Orchestra as changed, but the initial interpretation
undersold both -- Erie's page had actually rotated to 3 completely different
positions with zero overlap with the prior DB state (not just "some fields
changed"), and Nashville's entire principal/section-leader audition track
had closed in favor of unpaid rolling section auditions (a categorically
different situation, not a minor update). A second, independent agent given
only the URLs -- no prior diff or analysis -- caught both correctly. This is
now the standing rule for every `confirmed_real` flag headed toward a
database write.

## Edge Cases
- Orchestra with a placeholder row (no live auditions) whose page later posts
  a real audition: this is exactly the case this system exists to catch --
  the diff will show the new listing text appearing.
- A site that blocks bot User-Agents (returns a CAPTCHA/challenge page
  instead of real content): will likely hash-flip constantly if the
  challenge page itself varies (e.g. includes a nonce). If a given orchestra
  flags on every single run with diffs that look like challenge-page noise,
  that's a signal to mark it `noise_dismissed` and consider excluding that
  orchestra from automated diffing entirely (needs manual periodic checks
  instead) -- track this as a known-limitation list if it comes up.
- **Known limitation -- session/SSO-redirect pages**: Cincinnati Symphony's
  `/careers` URL routes through a real 302 redirect to
  `secure.cincinnatisymphony.org/.../sharedsession...` before landing on
  final content (confirmed on the first full scan). A bare HTTP fetch through
  this kind of auth/session handshake can land on different intermediate
  content between runs, causing spurious flags unrelated to any real
  audition-listing change. If a specific orchestra's flags consistently look
  like this (a "Redirecting..." interstitial, session-token noise, wildly
  different page structure each time), exclude it from automated diffing and
  note it here -- it needs periodic manual checks instead.
- **Confirmed real-but-irrelevant category -- rotating concert calendars**:
  the first full scan correctly flagged real content changes on The
  Orchestra Now (Bard College), Columbus Symphony, and North Carolina
  Symphony that turned out to be their "upcoming concerts" widget rotating
  to the next program (e.g. "Opening Night: Rachmaninoff & Bartók, September
  18" -> "Dvořák & Brahms, October 2") -- not an audition posting. This is
  NOT a tool bug or noise to strip; it's exactly what the human/agent review
  step exists to filter. Expect a steady background rate of these on any
  orchestra whose site embeds a concert calendar near the audition content.
- First-ever run across all orchestras will create ~400 baseline snapshots
  and should NOT produce any flags (nothing to diff against yet). Do not
  mistake "0 flags on day 1" for the tool being broken -- it's expected.
