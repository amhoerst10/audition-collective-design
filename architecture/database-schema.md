# Database Schema

Two logically separate MySQL concerns live on the same Hostinger MySQL server:

1. **WordPress's own database** (`wp_*` tables) -- standard WP + PMPro + WP Data Access tables. Not reproduced here; a fresh WordPress install creates these. The one row that matters operationally is documented in [Security-Critical Configuration](#security-critical-configuration) below.
2. **The orchestras/auditions repository** -- a separate custom database (`u715111901_OrchAudRepo` on the live site), holding the actual audition data and the URL-change-detection state. This is the schema below.

## Connection notes

- **From an external machine** (your laptop, a CI runner): connect via the server's **public IP**. Hostinger's Remote MySQL feature allow-lists specific external IPs.
- **From a script running ON the Hostinger server itself** (a cron job, WP-CLI): connect via **`localhost`** instead. The public IP does NOT work for same-server connections under Hostinger's host-based MySQL grants -- this cost real debugging time during the automated-expiry-purge build (see `automation-design/expiry-purge-system.md`).

## `orchestras`

```sql
CREATE TABLE `orchestras` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(255) NOT NULL,
  `city` varchar(100) DEFAULT NULL,
  `state` varchar(100) DEFAULT NULL,
  `url` varchar(500) NOT NULL,
  `scrape_flags` varchar(255) DEFAULT NULL,
  `scrape_notes` text DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

`url` MUST include the scheme (`https://...`) -- a bare domain broke `detect_url_changes.py` in production once (Desert Symphony Orchestra, fixed 2026-09-18). `scrape_flags`/`scrape_notes` are free-form internal notes, not currently used by any automation.

## `auditions`

```sql
CREATE TABLE `auditions` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `orchestra_id` int(11) NOT NULL,
  `position` varchar(255) NOT NULL,
  `instrumentation` varchar(100) NOT NULL,
  `application_deadline` date DEFAULT NULL,
  `preliminary_audition` date DEFAULT NULL,
  `final_audition` date DEFAULT NULL,
  `last_verified_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `orchestra_id` (`orchestra_id`),
  CONSTRAINT `auditions_ibfk_1` FOREIGN KEY (`orchestra_id`) REFERENCES `orchestras` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**An orchestra with zero real auditions still gets exactly one row** -- the standard placeholder:

```sql
INSERT INTO auditions (orchestra_id, position, instrumentation, application_deadline, preliminary_audition, final_audition, last_verified_at)
VALUES (<id>, 'No auditions reported at this time', 'N/A', NULL, NULL, NULL, NOW());
```

This is not optional decoration -- the frontend and the automated purge logic both depend on every orchestra having at least one row.

**Current clean `instrumentation` dropdown values** (no ambiguous/out-of-scope entries -- "Conductor" and similar podium roles are explicitly out of scope per `directives/AUDITION_CAPTURE.md`, and "French Horn"/"Double Bass" were merged into "Horn"/"Bass"):

```
Bass, Bass Clarinet, Bass Trombone, Bassoon, Cello, Clarinet, Contrabassoon,
Flute, Guitar, Harp, Horn, Keyboard, N/A, Oboe, Percussion, Piano,
Piano & Celeste, Saxophone, Timpani, Trombone, Trumpet, Tuba, Viola, Violin
```

## `url_change_snapshots`

Added 2026-09-18 for the URL-change-detection system (see `directives/URL_CHANGE_DETECTION.md` and `automation-design/url-change-detection-system.md`). One row per orchestra holding the last-seen cleaned page text.

```sql
CREATE TABLE `url_change_snapshots` (
  `orchestra_id` int(11) NOT NULL,
  `clean_text` longtext DEFAULT NULL,
  `content_hash` char(64) DEFAULT NULL,
  `last_checked_at` datetime DEFAULT NULL,
  `last_changed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`orchestra_id`),
  CONSTRAINT `url_change_snapshots_ibfk_1` FOREIGN KEY (`orchestra_id`) REFERENCES `orchestras` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

## `url_change_flags`

One row per detected content change, awaiting human/agent review.

```sql
CREATE TABLE `url_change_flags` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `orchestra_id` int(11) NOT NULL,
  `detected_at` datetime NOT NULL,
  `diff_summary` text DEFAULT NULL,
  `status` enum('unreviewed','confirmed_real','noise_dismissed') NOT NULL DEFAULT 'unreviewed',
  `reviewed_at` datetime DEFAULT NULL,
  `reviewer_notes` text DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `orchestra_id` (`orchestra_id`),
  CONSTRAINT `url_change_flags_ibfk_1` FOREIGN KEY (`orchestra_id`) REFERENCES `orchestras` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

## Security-critical configuration

The WP Data Access "app" (`app_id=6`, powers the live Audition Board's REST endpoint) MUST have `rest_api.authorization` set to `restricted`, not `anonymous`. This was a real paywall-bypass vulnerability discovered and fixed during this project (2026-09-17) -- with `anonymous` authorization, anyone could query the full audition dataset via `POST /wp-json/wpda/app/select` without logging in or paying, completely bypassing the PMPro membership gate.

Correct state (verify with `wp db query "SELECT app_settings FROM wp_wpda_app WHERE app_id=6"`):

```json
{"rest_api":{"authorization":"restricted","authorized_roles":["subscriber","administrator"],"authorized_users":[]}, ...}
```

If rebuilding the WPDA app from scratch, set this explicitly -- do not trust the plugin's default.
