# Rebuild Guide

Step-by-step reconstruction of the live system from nothing but this repo. Written 2026-09-21 to close a real gap: until this date, the actual live site logic (login gating, security fix, both cron automations) existed only on the Hostinger server itself, with no durable copy anywhere.

## 1. Hosting + WordPress

1. Hostinger shared hosting plan, domain pointed at it.
2. Install WordPress via hPanel.
3. Install and activate plugins: **Paid Memberships Pro** (PMPro) and **WP Data Access** (WPDA).

## 2. Databases

1. WordPress's own DB is created automatically by the WP install -- nothing special needed there beyond what PMPro/WPDA create on activation.
2. Create a **separate** MySQL database for the orchestras/auditions data (the live one is named `u715111901_OrchAudRepo` -- the `orchestras`/`auditions` prefix pattern comes from the Hostinger account, not something meaningful to preserve exactly). Run the table definitions in `architecture/database-schema.md` (`orchestras`, `auditions`, `url_change_snapshots`, `url_change_flags`).
3. Populate `orchestras` and `auditions` -- this is the actual product data, built up over the state-by-state capture process documented in `directives/AUDITION_CAPTURE.md`. Not something this repo reconstructs automatically; re-running that directive's workflow (state by state, 3-agent process) is the only path if the data itself is lost. **If you still have DB access, back this up separately and regularly -- this repo captures code/config, not the data.**

## 3. WPDA app configuration (security-critical)

Set up a WPDA "App" (App Builder) exposing `orchestras`/`auditions` as a queryable table for the frontend. Once created, confirm its REST API authorization is **`restricted`**, not `anonymous`:

```sql
SELECT app_settings FROM wp_wpda_app WHERE app_id = <your app id>;
```

Should show `"rest_api":{"authorization":"restricted","authorized_roles":["subscriber","administrator"], ...}`. See `architecture/database-schema.md` for why this matters -- `anonymous` was a real, confirmed paywall-bypass vulnerability in this project's history.

## 4. Deploy the custom mu-plugins

Copy all 4 files from [`wordpress-mu-plugins/`](wordpress-mu-plugins/) into the target site's `wp-content/mu-plugins/` directory:

- `qa-fixes.php` -- the bulk of site styling/behavior: login gating (Audition Board + "Your Plan" pages require login), full-page restyle of the PMPro checkout flow, page title renames, nav gradient-text treatment. Has a `LOCKED DESIGN DECISIONS` block documenting choices that were explicitly signed off by the project owner -- read it before changing any of that styling.
- `automated-expiry-purge.php` -- see `automation-design/expiry-purge-system.md`.
- `email-verification.php` -- post-signup email confirmation flow.
- `simplify-signup.php` -- reduces the PMPro checkout form to just email + password.

mu-plugins load automatically once present in that directory -- no activation step needed. (Hostinger also auto-installs its own `hostinger-auto-updates.php` in the same directory; that one is platform-managed, not part of this project, and doesn't need to be recreated.)

## 5. Restore WordPress page content

Two pieces of content exist only in the database, not as files, unless captured like this:

- [`wordpress-page-content/audition-board-page-content.html`](wordpress-page-content/audition-board-page-content.html) -- the Audition Board page's content (post ID 150 on the live site). **Read `automation-design/wp-data-access-filter-workaround.md` before touching this** -- it explains why the inline `<script>` in this content is written the way it is (avoiding literal `&&` and mixed quote styles, both of which WordPress's render-time content filters silently corrupt) and why it includes an `X-WP-Nonce` header (without it, even a logged-in user's requests are treated as anonymous by the REST API -- this was the actual root-cause bug that made the Audition Board never work for real users until fixed).
- [`wordpress-page-content/additional-css.css`](wordpress-page-content/additional-css.css) -- site-wide Additional CSS (the `custom_css` post type, post ID 57).

Apply via `wp post update <id> <file>` (WP-CLI) rather than pasting through the editor UI, to match how these were actually authored and avoid re-triggering `wptexturize()`-style quote mangling on save.

## 6. Set up the two cron jobs

Both run via Hostinger's native Cron Jobs feature (hPanel -> Advanced -> Cron Jobs on the target site), **not** WordPress's own cron page and **not** any contributor's local machine (see `architecture/README.md` for why).

| Job | Schedule | Command |
|---|---|---|
| Expiry purge backstop | `0 0 * * *` | `/usr/bin/php /home/<user>/domains/<domain>/public_html/wp-cron.php` |
| URL change detection | `0 2 * * *` | `/usr/bin/python3 /home/<user>/detect_url_changes.py >> /home/<user>/url_change_full_run.log 2>&1` |

The expiry-purge logic itself is a WP-Cron scheduled event (`ac_daily_expiry_purge`) registered by `automated-expiry-purge.php`; the hPanel job just guarantees WP-Cron actually fires daily even with zero site visitors.

The URL-change-detection job needs Python 3 + a few packages on the server -- see the "Deploying to the server" section of `automation-design/url-change-detection-system.md` for the exact bootstrap commands (the server's Python is an old 3.6, which needs a pinned older `mysql-connector-python`).

## 7. Local/operational environment

1. Copy `.env.example` to `.env`, fill in real values.
2. `directives/` and `execution/` in this repo mirror the standing tools from the main project directory -- `execution/` here is a curated subset (the reusable, standing tools), not every one-off state-extraction script from the original build-out. If reconstructing the full historical toolset, the original project directory's `execution/` folder has ~150 more scripts, most of them disposable/one-off per the project's own "Deliverables vs Intermediates" convention.
3. Read `directives/AUDITION_CAPTURE.md`, `directives/URL_CHANGE_DETECTION.md`, and `directives/SCALABILITY_AUTOMATION.md` before doing any further work -- they're the actual operating instructions for an AI agent (or a person) continuing this project, and they get updated as the project learns things. Keep them that way.

## Known environmental gotchas (don't re-debug these)

- **Home-network DNS flakiness**: if running anything from a contributor's home machine, expect intermittent `getaddrinfo` failures at any real request volume, confirmed unrelated to actual site health (via `nslookup` succeeding when Python's resolver was failing). Root cause: the router, not the code. This is exactly why both cron systems now run server-side instead.
- **Hostinger MySQL host-based grants**: `localhost` for same-server connections, the public IP for external ones. Using the wrong one produces an Access Denied error that looks like a credentials problem but isn't.
- **WordPress content-filter mangling of inline `<script>` content**: applies at *render* time, not just save time -- even content inserted via direct SQL gets mangled when the page is viewed. See `automation-design/wp-data-access-filter-workaround.md` section 2 for the full diagnosis process and fix.
- **Deploy safety**: this project caused two live-site outages early on from unvetted mu-plugin changes (an unescaped apostrophe in a PHP string; a gettext filter missing its `accepted_args` parameter). The process that followed -- stage under a different filename, `php -l`, `wp eval-file`, a plain `wp eval` health check, then `mv` into place -- is now standard for any mu-plugin change. Follow it.
