# Automation Design

Two automated systems run daily on the Hostinger server (not any contributor's machine -- see `../architecture/README.md`):

- [`expiry-purge-system.md`](expiry-purge-system.md) -- purges audition listings once their final audition date has passed, backfills the "no auditions" placeholder when an orchestra hits zero real listings. Built first ("item 1" of the automation roadmap).
- [`url-change-detection-system.md`](url-change-detection-system.md) -- daily diff-based monitoring of every orchestra's audition page, flagging real content changes (new postings, removed listings) for review while filtering out known noise (rotating timestamps, form honeypots, concert-calendar widgets). Built second ("item 2"), designed to eventually trigger an automated review agent rather than requiring a manual check-in.
- [`wp-data-access-filter-workaround.md`](wp-data-access-filter-workaround.md) -- how the live Audition Board gets real column filtering without WPDA's paywalled UI feature, plus a hard-won WordPress content-filter gotcha (inline `<script>` content gets silently mangled on render, not just on save).

Both cron systems' actual running code lives in `../wordpress-mu-plugins/` (PHP) and `../execution/` (Python) -- these docs explain the *why*, the source files are the *what*.
