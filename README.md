# Audition Collective

Design, architecture, and live-source-of-truth documentation for the Audition Collective platform -- a nationwide orchestra audition tracker (WordPress frontend + a custom MySQL data repository, hosted on Hostinger).

**If you need to rebuild this from scratch, start with [`REBUILD.md`](REBUILD.md).**

## What's in here

- [`architecture/`](architecture/) -- system design, database schema, why things are built the way they are
- [`automation-design/`](automation-design/) -- the two daily cron-based automation systems and the WP Data Access filtering workaround
- [`wordpress-mu-plugins/`](wordpress-mu-plugins/) -- the actual PHP running on the live site (pulled from the server -- this is the real source of truth, not a design sketch)
- [`wordpress-page-content/`](wordpress-page-content/) -- WordPress page content that exists only in the database otherwise (the Audition Board page, site-wide Additional CSS)
- [`directives/`](directives/) -- the operating instructions for the AI-agent-driven parts of this project (data capture workflow, URL change detection logic, scalability notes)
- [`vps/`](vps/) -- setup for the VPS that runs the nightly Crawl4AI change detector (Dockerfile, cron wrapper, rebuild steps)
- [`execution/`](execution/) -- the standing, reusable Python tools (a curated subset of a much larger one-off script collection in the main project directory)
- [`wireframes/`](wireframes/) -- design mockups and proposals
- [`branding/`](branding/) -- brand assets and guidelines

## Status

As of 2026-09-25: live site is running with the PMPro paywall gate fixed and verified secure, an automated daily expiry-purge system, and an automated nightly URL-change-detection system running on Crawl4AI on a VPS (352 of 408 orchestra pages readable; the rest feed a manual-check queue; flagged changes are independently re-verified before any database write). See `automation-design/url-change-detection-system.md` for the review workflow's current state.
