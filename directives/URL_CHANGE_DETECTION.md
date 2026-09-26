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
- `url_change_snapshots_c4a` table: same idea, used only by the Crawl4AI
  detector, plus `final_url` (where the page actually landed after redirects)
  and `last_status`. Kept separate on purpose -- the two detectors clean
  pages differently, so comparing one's snapshot against the other's would
  flag every site as changed.
- `url_change_flags` table (one row per detected change or failure):
  - `orchestra_id`, `detected_at`, `diff_summary` (unified diff, or the
    failure detail for manual-check flags), `status`, `reviewed_at`,
    `reviewer_notes`
  - `status`: `unreviewed` / `confirmed_real` / `noise_dismissed` for content
    changes; `needs_manual_check` / `manual_check_done` for crawl failures
  - `detector`: `bs4` (legacy) or `c4a` (Crawl4AI)
  - `failure_reason`: `blocked` / `dead_link` / `moved` / `unreachable`
    (manual-check flags only)
  - `suggested_url`: for `moved` flags, where the old URL redirects to

## Tool (current): Crawl4AI detector on the VPS

`execution/detect_url_changes_c4a.py`, run nightly on the Hostinger KVM 2 VPS
(`srv997890.hstgr.cloud`, 72.60.123.209) inside the `ac-crawler` Docker image
(the official `unclecode/crawl4ai` image plus the MySQL connector). Cron:
`/opt/audition-collective/run_detector.sh` at 07:00 UTC. Logs:
`/opt/audition-collective/logs/detector-YYYY-MM-DD.log`, kept 30 days.

**Why it replaced the BeautifulSoup detector** (evaluation, 2026-09-24): the
old detector used plain HTTP requests and could not read 87 of 408 orchestra
pages. Crawl4AI drives a real headless browser and read 70 of those 87:
56 of 67 bot-blocked (403/406) sites, 12 of 17 "404" sites (7 of them had
simply moved and the browser followed the redirect), and both SSL/timeout
failures. It reproduced 6 of 6 hand-verified orchestras exactly (every fact
checked against a separate independent read). About 6 seconds per page, so a
full 408-page run takes roughly 11 minutes at 4 pages in parallel.

**Every orchestra lands in exactly one bucket per run:**
| Crawl result | Action |
|---|---|
| Read OK, unchanged | Nothing |
| Read OK, changed in only one of two reads | Nothing (counted as `flaky`) |
| Read OK, changed in both reads | Flag `unreviewed` with a diff of the stable changes -> independent live re-check before any DB write (see rule below) |
| Blocked (Cloudflare, 401/403/406/429, or a bot-challenge page) | Flag `needs_manual_check`, reason `blocked` |
| Page gone (404/410, or loads with under 200 characters of content) | Flag `needs_manual_check`, reason `dead_link` -> find the orchestra's new audition page |
| Redirected within the same site | Flag `needs_manual_check`, reason `moved_same_site`, with `suggested_url` (low priority); content still diffed |
| Redirected to a different domain | Flag `needs_manual_check`, reason `moved_offsite`, with `suggested_url` (check soon -- can mean a hijacked or expired domain); content still diffed |
| Unreachable after one retry, or hung past 120 s | Flag `needs_manual_check`, reason `unreachable` |

**A crawl failure is a trigger, not a silent skip.** Blocked or dead pages
are exactly where a listing can go stale unnoticed, so each one goes to a
manual-check queue for a person or an agent. Because Crawl4AI reads most
sites, that queue should stay small (roughly 15-20 orchestras, versus 87 the
old detector couldn't read at all).

**De-duplication**: no new manual-check flag if the same orchestra and reason
already has an open one, or had one in the last 7 days. Without this the
~11 permanently Cloudflare-blocked sites would re-queue every night; with it
they effectively come up for a manual check about once a week.

**Known hard limit -- 11 Cloudflare-protected sites**: Minnesota Orchestra,
National Symphony, Lyric Opera of Chicago, Grant Park Music Festival,
Vermont Symphony, Orlando Symphony, Savannah Philharmonic, Akron Symphony,
Auburn Symphony, Springfield (MO) Symphony, Monterey Symphony. These block the
VPS's data-center IP address outright; Crawl4AI's stealth and "undetected
browser" modes both failed. The only automated fix is a paid
residential-proxy service, not worth it for 11 sites. They stay on the weekly
manual-check cycle.

**Cleaning differences from the legacy detector**: Crawl4AI returns markdown,
so the cleaner strips image tags and link targets (link URLs often carry
rotating tracking parameters), then applies the same noise denylist and
honeypot rule, plus widget/countdown patterns found in the Crawl4AI noise
test (cart and account widgets, "skip to main content", cookie banners,
accessibility toolbars, countdown timers). Only `<nav>`, `<footer>`,
`<script>`, `<style>`, `<noscript>` and `<svg>` are excluded.

**Do NOT exclude `<form>` or `<header>`** (learned on the first full run,
2026-09-24): some sites wrap the entire page in a `<form>` (Seattle Opera
kept 1 character of 5,825; Grand Rapids 167 of 2,651), and some WordPress
themes put page content inside `<header>` (Berkeley, Toledo, Dallas Winds).
Excluding them turned 35 working pages into false "dead link" flags.

**Confirm-before-flag**: when a page's cleaned text differs from its
snapshot, the detector immediately reads the page a second time and keeps
only the lines that changed in BOTH reads. Widgets that render on one load
and not the next (menus, carts, chat boxes) drop out; real listing changes
survive. A change that doesn't survive the second read is counted as
`flaky` and nothing is flagged.

**Challenge-page detection**: some bot protections return a normal-looking
status code with a "please wait" page (Virginia Symphony returns HTTP 202
with "Checking the site connection security... requires cookies"). Pages
under 3,000 characters matching known challenge wording are classified
`blocked`, not `dead_link`. **Correction to the evaluation numbers above**:
the evaluation counted any page over 300 characters as a success, and about a
dozen of these ~305-character challenge pages slipped through as
"successes." Real blocked coverage is lower than 56 of 67; see the
production run results for the corrected figure.

**Hard per-site timeout (120 s)**: on the first full run Phoenix Symphony's
page hung the browser for over 2 hours (Crawl4AI's own `page_timeout` didn't
stop it), which blocked the whole run from finishing. Each orchestra is now
capped at 120 seconds, a hung site goes to the manual queue as
`unreachable`, and `run_detector.sh` also kills any run that passes 60
minutes.

**MySQL connection cap -- use ONE connection per run** (learned 2026-09-24):
the Hostinger MySQL user `u715111901_Admin` is limited to **500 new
connections per hour for remote connections** (error 1226,
`max_connections_per_hour`). A version of the detector that opened a fresh
connection for every read/write used 2-3 per orchestra, hit the cap
mid-run, and lost ~135 orchestras' results. The cap is counted per
user@host: WordPress itself connects via `localhost`, which has its own
budget, so the live site was unaffected. But every remote client shares
the remote budget -- the VPS detector AND any ad-hoc queries from a
contributor's laptop. Rules: the detector reuses one connection and
reconnects only if it drops; avoid bursts of ad-hoc laptop queries around
the 07:00 UTC run; if you see error 1226, stop making remote queries and
wait up to an hour for the window to clear.

**`moved` is split**: `moved_same_site` (the orchestra reorganized its own
site -- low priority, one-time URL housekeeping) vs `moved_offsite` (the URL
now lands on a different domain -- check soon). The first run found about 50
genuine redirects, mostly same-site reorganizations. One `moved_offsite` was
a real problem: Arkansas Philharmonic's youth-audition URL
(`arphil.org/apyoauditions/`) now redirects to an unrelated Indonesian
gambling site, a sign of an expired or hijacked page. Per the project
owner's instruction, stored URLs are NOT auto-updated from redirects; each
is confirmed by hand first.

**Parallel run and cutover**: the legacy detector (below) keeps running on the
shared hosting server until the Crawl4AI detector has run cleanly for a
couple of nights. Flags from each are distinguishable by the `detector`
column. At cutover, delete the legacy hPanel cron job; `url_change_snapshots`
can then be dropped.

**Structured AI extraction (deferred)**: Crawl4AI can also hand each page to
an AI model to return the audition listings as structured data, which would
eliminate text-diff noise at the root. Deliberately not adopted yet: the
clean markdown alone already reproduced every hand-verified fact, and it adds
a per-page API cost. Revisit only if the text-diff approach proves inaccurate.

## Nightly data-integrity check (added 2026-09-26)

`execution/check_data_integrity.py` runs right after the Crawl4AI detector in
`run_detector.sh`. It doesn't look at websites; it scans every `auditions`
row for patterns that usually mean a capture error, and queues each affected
orchestra (`status='needs_manual_check'`, `failure_reason='data_integrity'`,
`detector='integrity'`, issues listed in `diff_summary`, 7-day dedupe).

**Why it exists:** the project owner kept spotting these by eye on the live
board ("how can you have a Section Second Violin position without an
application deadline, but it has a prelim and a final?"). The owner's
standard: the system, not a human skimming the board, should catch these.

| Check | Rationale |
|---|---|
| Preliminary date but no final | A single audition date stored in the wrong column (Waterloo-Cedar Falls) |
| Final within 120 days but no deadline | Deadlines are normally posted by then. NOT flagged further out -- Atlanta's 2027 auditions legitimately say "Not yet accepting applications" |
| Deadline after prelim/final, or prelim after final | Typo or swapped columns |
| Final more than 18 months out | Likely year typo |
| No final and no reason suffix | Breaks the capture rule; never expires |
| Final passed more than a day ago, row still present | Purge missed it (the WP-Cron purge fires ~15:45 UTC, hence the one-day grace) |
| Duplicate listings / duplicate placeholders / placeholder beside real rows | Leftover or double entry |
| Orchestra with no rows at all | Invisible on the board. The first run found 13 (Indianapolis, Louisville, San Diego, Utah Symphony, SF Opera, ...), a gap predating this system |
| Instrumentation not allowed, or contradicting the position name | Misfiled instrument |

A hit means "look at this," not "this is wrong." Work each through the same
research -> independent verification -> write process as other queue items.
When a reviewer confirms a flagged set of issues is actually correct (e.g. an
orchestra that genuinely publishes no deadline), store that exact issue text
in the `manual_check_done` flag's `diff_summary`: the check stays quiet for
that orchestra until its issues change, so the queue doesn't refill weekly
with known-good cases. First run results (2026-09-26): 13 orchestras had no
rows; 4 of them had open auditions (Indianapolis 4, San Diego 5, Tucson 2, SF
Opera 1) that were invisible on the board.

## Nightly job-board cross-check (added 2026-09-26)

`execution/check_job_boards.py` runs after the integrity check. It reads
musicalchairs.info's ~20 per-instrument job pages (~20 polite requests),
keeps US postings, drops obvious out-of-scope ones (apprenticeship, academy,
student, youth, fellowship, military bands, cancelled), fuzzy-matches the
organization to our `orchestras` table, and queues any posting for an
instrument we have no listing for (`failure_reason='jobboard_mismatch'`,
`detector='jobboard'`, posting details + link in `diff_summary`, 7-day
dedupe). US organizations we don't track are printed to the log as
discovery leads.

**Why:** ~40 orchestras block the VPS crawler (Cloudflare scores its
data-center IP), but musicalchairs doesn't block us -- a QA pass had
already confirmed Lyric Opera of Chicago's opening there when lyricopera.org
refused every automated request. It also catches openings we missed on
readable sites. A mismatch is a lead, not a verdict: postings go stale
(Alabama's past September auditions still show "closing n/a") and our
scope rules still apply at review. First run queued 6 (Colorado Symphony
2nd Trumpet, New Haven violins, Met Opera Principal Cello, Johnstown viola,
Nashville Civic principal bass, Alabama's stale posts).

**Polite crawling (same date):** the main detector now runs 2 pages at a
time (was 4), pauses a random 2-6 s per site, and shuffles its order each
night; a full run takes ~30 min (run backstop raised to 90 min). After a
burst of test crawls, Cloudflare challenges on the VPS IP rose from 9 to ~48
and fell back to 11 once crawling returned to once a night -- the footprint
matters. Escalation path if blocking stays high: Firecrawl free tier for
the blocked set, a weekly real-browser check, then a residential proxy
(project owner: proxy last).

## Legacy tool: BeautifulSoup detector (running in parallel until cutover)
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

- **Crawl4AI-only noise** (found in two noise tests, 2026-09-24/25 -- runs
  minutes or hours apart where nothing real could have changed). These
  apply only to `detect_url_changes_c4a.py`, because a real browser renders
  widgets that plain HTTP fetches never saw:
  - Accessibility overlays whose wording depends on the browser's apparent
    OS ("Press Option+1 for screen-reader mode" vs "Alt+1"; "Accessibility
    Preferences (⌘ + Shift + A)") -- Marin, Opera Colorado, Fort Wayne,
    Omaha, Hawai'i
  - Cookie-consent banners with ticking counts ("We and our 1738 partners",
    "Number of Vendors seeking consent: 847") -- Atlanta Symphony
  - Countdown timers ("23d 15:59:15", "18 hours", lone digits). Markdown
    bold (`18** hours`) defeated the first countdown rule, so emphasis
    markers are now stripped before matching -- San Bernardino, Kamuela
  - Newsletter sign-up boxes that load on some reads and not others
    ("Subscribe", "Type your email", "Join our mailing list") -- Boston
    Symphony, Chautauqua
  - Cart/account/chat widgets, "Skip to main content" links, cookie banners
  - Concert-picker dropdown options ("Mendelssohn Violin Concerto | WED, SEP
    23 at 7:30PM") -- NC Symphony's accommodation form, visible now that
    forms aren't excluded
  - Content of a page that has moved to a *different domain* is not diffed
    at all (Arkansas Phil's hijacked URL serves a gambling site with live
    numbers); the `moved_offsite` flag is the signal.

  Before adopting any new pattern, dry-run it against every stored snapshot
  and list the lines it would remove -- confirm none are real audition text
  (done for this batch: nothing audition-related was removed apart from the
  intended concert-picker options).

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
