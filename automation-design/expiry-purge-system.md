# Automated Expiry Purge

**Source**: [`../wordpress-mu-plugins/automated-expiry-purge.php`](../wordpress-mu-plugins/automated-expiry-purge.php)
**Runs**: Hostinger hPanel Cron Job, daily at `0 0 * * *` (midnight), directly on the server via PHP (WP-Cron backstop, not the sole trigger -- see below)

## What it does

Purges `auditions` rows whose audition process is genuinely over, and backfills the standard "no auditions" placeholder for any orchestra left with zero real rows afterward.

**Purge trigger is the FINAL audition date only.** A passed preliminary-audition date or application deadline never causes a purge, even if `final_audition` is NULL -- this was an explicit correction mid-project (2026-09-17): the original logic fell back to the preliminary date when no final date existed, which wrongly deleted live listings that only had a preliminary date scheduled. Confirmed via a real query after the fix: 4 real records with a passed preliminary date and no final date correctly survived a purge run.

Sibling auditions for the same orchestra are untouched when only one expires -- the delete targets specific row IDs, not the whole orchestra. Placeholder backfill only fires when an orchestra's remaining real-row count hits exactly zero.

## Why PHP / WP-Cron instead of a separate script

This runs as a WordPress mu-plugin (`wp_schedule_event` + `add_action`) rather than a standalone script because it needs no external dependencies and WP already has cron scaffolding. The catch: **WP-Cron only fires on a page load** -- a low-traffic site could go a day without anyone visiting, silently skipping the scheduled run. The Hostinger Cron Job (`php ... wp-cron.php?doing_wp_cron`, or in practice a direct call) is the reliability backstop that guarantees the WP-Cron hook actually fires every day regardless of traffic.

## DB connection gotcha

The plugin connects to the *separate* orchestras/auditions database (not WordPress's own DB) via raw `mysqli`. It MUST use `DB_HOST = 'localhost'`, not the server's public IP -- the public IP works fine for external connections but gets an Access Denied error when the WordPress server connects to itself using it (Hostinger's Remote MySQL allow-list is for external IPs only; same-server connections need the `localhost` grant instead). This cost real debugging time -- confirmed via a raw `mysqli_connect("localhost", ...)` test through `wp eval` before fixing the constant.

## Deploy-safety process used

Any change to this file should go through the same process that avoided two earlier self-inflicted outages on unrelated files:

1. Stage the file under a different filename on the server (`scp` it up as `*-staged.php`)
2. `php -l staged-file.php` -- syntax lint
3. `wp eval-file staged-file.php` -- actually executes it in a real WP context, catching runtime errors lint can't. A "Cannot redeclare function" error here is expected/harmless if the named functions are already active in `mu-plugins/` from a prior deploy -- each `eval-file` run is its own separate PHP process; it doesn't affect the live site.
4. `wp eval 'echo "OK";'` -- confirm the live site is still healthy
5. Only then `mv` the staged file into `wp-content/mu-plugins/`

## Manual verification

```
wp ac-purge-expired
```
(a registered WP-CLI command in the plugin) runs the purge immediately and prints a summary, without waiting for the schedule. `wp cron event list` confirms `ac_daily_expiry_purge` is registered and shows its next run time. Every run's summary (purged count, purged listing names, placeholders added) is logged to the `ac_expiry_purge_log` WordPress option, keeping the last 30 runs -- auditable from `wp-admin` without SSH.
