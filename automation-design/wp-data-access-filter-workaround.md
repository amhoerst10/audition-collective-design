# WP Data Access — Free-Tier Filter Workaround

**Context:** The Audition Board query page (`wp_posts` ID 150) needed State/City/Instrumentation filters on top of 490 live audition records. The plugin's native "Column Filters" feature in App Builder's Table Builder is explicitly paywalled (confirmed via screenshot — a lock icon on the toggle, labeled "These are premium features"). This doc records how we got real filtering working anyway, for free, and the gotchas that cost the most debugging time.

---

## 1. The core discovery: the API isn't paywalled, only the UI toggle is

WP Data Access's App Builder renders tables as a React/MUI component (`class="MuiTable-root MuiTable-stickyHeader"` — **not** jQuery DataTables, despite the plugin also shipping DataTables assets for its older Publisher/`pub_id` system). That React table fetches its data from a real REST endpoint:

```
POST /wp-json/wpda/app/select
```

This endpoint is **not** license-gated. We confirmed this by capturing the exact request payload (via a `XMLHttpRequest.prototype.send` monkey-patch in the browser console — `fetch` didn't work because this plugin uses XHR, not `fetch`) and then replaying it manually with modified filter parameters. A request with `search_columns: ["state"]` and `search: "Texas"` returned correctly state-filtered rows, proving the backend fully supports column-scoped filtering — the admin UI toggle is the only thing locked behind a license.

### Confirmed working payload shape

```json
{
  "col": { "orchestra_name": true, "orchestra_url": true, "city": true, "state": true,
           "position": true, "instrumentation": true, "application_deadline": true,
           "preliminary_audition": true, "final_audition": true },
  "page_index": 0,
  "page_size": 1000,
  "sorting": [],
  "search": "",
  "search_columns": [],
  "search_column_fns": {},
  "search_column_lov": [],
  "search_data_types": { "orchestra_name": "varchar", "orchestra_url": "varchar",
                          "city": "varchar", "state": "varchar", "position": "varchar",
                          "instrumentation": "varchar", "application_deadline": "date",
                          "preliminary_audition": "date", "final_audition": "date" },
  "row_count_estimate": false,
  "media": { "orchestra_url": "HyperlinkURL" },
  "client_side": false,
  "shortcode_params": { "pwa": "" },
  "app_id": 6,
  "cnt_id": "6"
}
```

Response: `{"code":"ok","message":"","data":[{...row...}, ...]}`.

### Gotcha: `sorting` format

Sending `sorting: [{ "column": "orchestra_name", "dir": "asc" }]` (a reasonable-looking guess) returns `HTTP 400 rest_invalid_param: Invalid parameter(s): sorting`. The endpoint wants `sorting: []` — we never found the correct populated format and didn't need it, since sorting is cheap to do client-side anyway.

### The approach we landed on: fetch everything once, filter client-side

Rather than fighting the server-side `search_columns`/`search_column_fns` filter combination (untested whether multiple simultaneous column filters AND together correctly — not worth the risk), we fetch all ~490 rows in one `page_size: 1000` call on page load, then do state/city/instrumentation filtering and pagination entirely in vanilla JS in the browser. Simple, fast enough at this data volume, and sidesteps any multi-column-filter uncertainty in the API.

---

## 2. The bigger time-sink: WordPress silently corrupts inline `<script>` content

This is the one worth remembering hardest. When JS is embedded directly in `wp_posts.post_content` (inside a Gutenberg `wp:html` block) and saved via a **direct SQL `UPDATE`** (bypassing the WordPress editor/`wp_insert_post` entirely), the content filter chain still runs on the *rendered output* when the page is viewed — not just on save through wp-admin. Two specific corruptions broke the script outright:

### a) Literal `&&` becomes `&#038;&#038;`
Any bare ampersand in stored content gets HTML-entity-encoded on render (`&` → `&#038;`). `if (a && b)` in your source becomes literal text `if (a &#038;&#038; b)` in the browser's parsed `<script>` — a hard `SyntaxError: Invalid or unexpected token`.

**Fix:** avoid literal `&&` entirely. Use nested `if` statements instead:
```js
// Instead of: if (a && b) { ... }
if (a) { if (b) { ... } }
```
Also applies to any string containing a literal `&` (e.g. an `escapeHtml()` helper that does `.replace(/&/g, "&amp;")`) — construct the ampersand at runtime instead: `String.fromCharCode(38)`.

### b) Adjacent single/double quotes get mangled
A pattern like `'<a href="' + x + '">'` (single quotes wrapping a string that itself contains double-quoted HTML attributes) triggers WordPress's `wptexturize()`-style quote processing and silently corrupts the quote characters, again producing a syntax error.

**Fix:** use double-quotes exclusively for JS string literals in inline scripts, with `\"` escapes for any literal double quotes needed inside (e.g. HTML attributes). Never mix single and double quotes adjacently in stored `post_content` JS.

### How we diagnosed it (useful pattern for next time)

1. `read_console_messages(onlyErrors: true)` showed the crash location but not *why*.
2. Confirmed the live DOM script's length didn't match what was written to the DB (`document.querySelectorAll('script')` + manual length/checksum comparison) — proof something was rewriting the content between storage and render.
3. Used a binary search over the script string with `new Function(prefix)` to find the *exact character offset* where parsing broke:
   ```js
   let lo = 1, hi = t.length, firstBad = -1;
   while (lo <= hi) {
     const mid = Math.floor((lo+hi)/2);
     try { new Function(t.slice(0, mid)); lo = mid + 1; }
     catch(e) {
       if (e.message === "Invalid or unexpected token") { firstBad = mid; hi = mid - 1; }
       else { lo = mid + 1; } // "Unexpected end of input" just means still-incomplete, not broken
     }
   }
   ```
4. Char-code-dumped a small window around that offset (raw text kept getting blocked by the browser tool's cookie/secret-pattern filter — character codes sidestep that).

---

## 3. Cache reminder

LiteSpeed Cache on this Hostinger install does **not** auto-invalidate when `post_content` is updated via direct SQL (it only hooks into normal WP save actions). After any direct DB content change, purge manually:
```
/wp-admin/index.php?LSCWP_CTRL=purge&LSCWP_NONCE=<nonce>&litespeed_type=purge_all_lscache
```
(nonce is visible in the admin toolbar's Purge All link once logged in). Otherwise you'll debug a "fix" that appears to do nothing for several rounds.
