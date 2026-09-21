# Architecture

## The 3-layer system

This project separates concerns because LLMs are probabilistic and most of the actual business logic isn't:

- **Layer 1 -- Directives** (`directives/`): SOPs in Markdown. Define goals, inputs, tools to use, edge cases. The instruction set.
- **Layer 2 -- Orchestration**: an AI agent reads directives, calls the right execution tools in order, handles errors, updates directives with learnings.
- **Layer 3 -- Execution** (`execution/`): deterministic Python scripts. API calls, DB writes, file processing. Reliable and testable.

See the root `CLAUDE.md` / `AGENTS.md` / `GEMINI.md` in the main project directory for the full statement of this pattern -- it applies to any AI environment working on this project, not just one specific tool.

## The stack

- **Frontend**: WordPress (Hostinger shared hosting) with Paid Memberships Pro (PMPro) for the membership gate and WP Data Access (WPDA) for the live Audition Board's data grid.
- **Data**: a separate MySQL database (`u715111901_OrchAudRepo`) holding orchestras + auditions, independent of WordPress's own DB. Full schema: [`database-schema.md`](database-schema.md).
- **Automation, server-side**: two daily cron jobs running directly on the Hostinger server (not on any contributor's local machine -- see below for why). Details: [`../automation-design/`](../automation-design/).
- **Automation, human/agent-side**: state-by-state audition data capture via the 3-agent directive workflow (`directives/AUDITION_CAPTURE.md`).

## Why server-side cron, not a local machine

Two automation systems (expiry purge, URL change detection) need to run unattended every day. Early attempts ran them from a contributor's home machine and hit two real, recurring failures:

1. **Router-level DNS flakiness** -- the home network's router intermittently fails `getaddrinfo` under sustained request volume (confirmed via `nslookup` succeeding on domains that `requests.get()` was failing to resolve moments later). Not fixable in code beyond retry logic, and retries alone weren't enough at ~400-request volume.
2. **No reliable local "always on" trigger** -- a laptop that sleeps, reboots, or is simply off can't run a 2am cron job.

Both automations were moved to run directly on the Hostinger server via its native Cron Jobs feature (hPanel -> Advanced -> Cron Jobs), which sidesteps both problems entirely: same-datacenter network (essentially zero DNS flakiness) and always-on hosting.

## Live source-of-truth documents

Some of what runs in production has no file anywhere except the live server/database -- these are pulled and committed here specifically so a rebuild is possible without SSH access to the original server:

- [`../wordpress-mu-plugins/`](../wordpress-mu-plugins/) -- the 4 custom PHP files controlling site behavior (paywall/login gating, signup flow, email verification, styling overrides, the expiry-purge cron job). Pulled directly from `wp-content/mu-plugins/` on the live server.
- [`../wordpress-page-content/`](../wordpress-page-content/) -- the Audition Board page's raw HTML/JS (`wp_posts.post_content` for post ID 150) and the site-wide Additional CSS (post ID 57, `custom_css` post type). These are WordPress *content*, not files on disk, so they don't exist anywhere except the database unless captured like this.

**If you edit either of the above, edit the copy in this repo first, then deploy it** (see `REBUILD.md` for the deploy process) -- don't edit directly on the live server and let this repo go stale again. That's exactly the gap this update closed: prior to 2026-09-21, none of this had a durable copy anywhere outside the live Hostinger server.
