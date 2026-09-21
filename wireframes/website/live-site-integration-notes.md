# Live-Site Integration Notes (v1 → v2)

Reviewed the live site directly in-browser at https://auditioncollective.com on 2026-09-07.

## What's actually live (not what was assumed)

1. **Not a plain unstyled stock theme.** Twenty Twenty-Five is the active theme (confirmed via `wp-content/themes/twentytwentyfive/style.css`), but it's already been customized: black background (`#000`), white text, a gold accent (`rgb(212,175,55)` / `#d4af37`), and **Inter** as the font-family everywhere (headings and body) — not the theme's default system font stack, and not a serif at all.
2. **Header/nav is off-canvas, not a flat top bar.** The header is a single black bar with the site name on the left and a hamburger icon on the right (standard Twenty Twenty-Five pattern). Clicking it opens a full-screen overlay menu. There is no visible multi-item horizontal nav.
3. **Current menu items** (from the live off-canvas menu): Log In, Membership Account, Membership Checkout, Membership Levels, Orchestra Directory. No "Home," "About," or "Resources" items exist yet.
4. **An "Orchestra Directory" page already exists and is PMPro-gated** — visiting it as a logged-out visitor shows a lock icon and "Membership Required / You must be a member to access this content," with a button to View Membership Levels. This is a live precedent for gated content on the site.
5. **Membership Levels page** lists two tiers: "Community Tier — Free" and "Monthly Member — $5.00/month." Important: even the free Community Tier currently requires selecting a level / having an account — it is not the same as "open to anonymous visitors," which is what this task explicitly requires for the audition board.
6. Footer is minimal: a single centered copyright line, no multi-column footer.

## What changed from v1 to v2

- **Palette/type swapped entirely**: v1 used navy/cream/serif (Georgia) styling loosely modeled on generic "orchestra job board" conventions. v2 uses the site's real black/gold/Inter system so the mockup reads as "this page already belongs to auditioncollective.com."
- **Nav restructured**: v1 showed a flat 4-item top nav (Auditions/Orchestras/Resources/About) with separate Log In / Join Free buttons. v2 instead shows the real hamburger + off-canvas menu, with a new "Audition Board" item added to the existing 5 real menu items (flagged "New") — so the deliverable shows exactly how the new page slots into current site architecture rather than inventing a nav that doesn't exist.
- **Removed all paid-tier UI**: v1 included "Members Only" locked cells, a lock-tag badge style, and an "Upgrade — $6/mo" banner driven by PMPro column visibility. Per current direction, the board is free-tier only and fully open — v2 strips every gating element and adds an explicit "Fully open, free tier" note instead, calling out that paid concepts (alerts, saved searches, contact/salary unlocks) are out of scope for this pass.
- **Called out the access-model conflict**: because the site's existing "free" tier still sits behind account creation (see Orchestra Directory above), v2's copy/badge ("Free & open to all visitors — no login required") is a deliberate design decision that differs from how the rest of the site currently gates content — flagged here so it's a conscious choice, not an oversight, when this goes into PMPro/WPDataTables config.
- Footer simplified to match the live site's single-line copyright instead of v1's four-column footer.

## Files
- Updated mockup: `wireframes/website/audition-board-mockup-v2.html`
- Original for comparison: `wireframes/website/audition-board-mockup.html`

## What changed from v2 to v3 (2026-09-07)

- **Reversed the access model back to gated, per resolved decision**: v2's "free & open to all, no login required" framing was explicitly a flagged deliberate deviation from the live site. That's now been overruled — v3 puts the audition board behind the SAME free-account (PMPro "Community Tier — Free") wall as the existing Orchestra Directory. Hero badge, gate note, and results-bar copy all updated to "free account required" language instead of "no login required." Nothing about the existing PMPro gate is loosened.
- **Added a landing-page mission statement section** (`.mission` block, sits right below the hero): plain-language explanation of what Audition Collective does (tracks live orchestra/opera audition openings nationwide so musicians don't have to check hundreds of individual orchestra sites), who it's for (students, freelancers, section/principal players), and an explicit line that full access is free with a free account. Written in the site's existing plain/professional register — no marketing fluff — using the same black/gold/Inter panel styling as the rest of the page.
- **Added a product-updates opt-in to the signup flow**: new mockup section at the bottom (`.signup-demo`) showing a free-account creation form (name/email/password, Community Tier — Free) with a checkbox: "Would you like to subscribe to updates about new features as they release?" Explicitly labeled in the mockup as a general, low-frequency product-announcement subscription, unrelated to and out of scope from any future paid-tier audition-alert emails. Defaulted to checked but easy to uncheck; note says it can be changed later in Membership Account.
- Kept everything else from v2 unchanged: real black/gold/Inter palette, real off-canvas hamburger nav with the same 5 existing menu items plus "Audition Board," filters/table/pagination UI, minimal single-line footer.

## Files (v3)
- Updated mockup: `wireframes/website/audition-board-mockup-v3.html`
- Supersedes v2's "no login required" framing — v2 kept for comparison, but its access-model framing is no longer the intended direction.
