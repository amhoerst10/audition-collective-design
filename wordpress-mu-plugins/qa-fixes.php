<?php
/**
 * Plugin Name: Audition Collective - QA Fixes (2026-09-16/17 passes)
 * Description: Fixes from the site-wide QA pass, plus a follow-up restyle/rename pass:
 * the PMPro checkout/login/levels pages rendered on the plugin's own default white
 * card template -- the only part of the site not built to match the dark/gold theme.
 * This restyles those cards dark, and swaps PMPro's default "Membership" wording
 * (built around paid tiers) for language that fits a free, single-tier product.
 *
 * ============================================================================
 * LOCKED DESIGN DECISIONS -- read this before changing anything below.
 * These were explicitly approved by the PM after several rounds of iteration.
 * Do not revert to an earlier version of any of these without being asked:
 * ============================================================================
 *
 * 1. Page titles: "Membership Checkout" -> "Create Your Account" (post 71),
 *    "Membership Levels" -> "Your Plan" (post 74). No "Membership" wording
 *    anywhere user-facing on these pages (headings, button, body copy, or the
 *    browser tab <title>).
 * 2. Create Account page has NO plan/price summary card -- there is no
 *    checkout at this stage of the product (a donation pipeline is planned
 *    separately, later). The page goes straight from the H1 to the
 *    email/password fields.
 * 3. Primary buttons ("Create Account", "Log In"): solid gold gradient
 *    (#e8c565 -> #d4af37), dark text, FULL WIDTH of their container, with a
 *    hover-lift + brighten transition. Not PMPro's default navy, not a
 *    compact/pill shape -- full width was explicitly requested after a
 *    compact version was tried and rejected.
 * 4. "Create Account" button + "Already have an account? Log in here" live
 *    INSIDE the Account Information card (in .pmpro_card_actions), stacked
 *    vertically, both centered -- not floating outside the card below it.
 * 5. Nav / heading text uses a white-to-gold diagonal gradient clipped to the
 *    text (135deg, #fff -> #d4af37, background-clip:text). This is the site\'s
 *    one consistent "emphasis" text treatment -- use it (not a flat gold
 *    color, not plain white) for: page headings, the site logo, EVERY nav
 *    item (all five links, not just the current-page one), and the
 *    "Log in here" link. This has been corrected back to the gradient twice
 *    already (once from invisible-text-bug white, once from flat gold used
 *    only on the current page) -- don\'t narrow it back down without being
 *    asked. Nav hover state is a plain brighter gold (#f0d375), no gradient.
 * 6. "Show Password" toggle is a plain inline gold text control (not a
 *    button) -- reset PMPro\'s default button chrome entirely rather than
 *    styling it as a second primary action.
 * 7. Audition Board (page slug "audition-board") and Your Plan (post 74) are
 *    both fully gated: template_redirect sends logged-out visitors to /login/
 *    before the page renders at all, not just its data.
 * 8. login_redirect sends EVERY successfully-logged-in user (including
 *    administrators) to /audition-board/, unless an explicit redirect_to was
 *    requested. This was deliberately widened from "non-admins only" -- the
 *    PM wants this for all accounts, including their own.
 *
 * *** FINALIZED, 2026-09-17: Create Account page (/membership-checkout/) ***
 * The PM explicitly signed off on this page as-is -- layout, copy, colors,
 * button width/placement, and the nav/logo/"Log in here" gradient treatment
 * are all done. Field order: Email Address, then Password (fixed post-signoff
 * -- was Password-then-Email, which read backwards). Do not restyle or rework
 * this page without being asked again.
 *
 * Before editing a CSS rule in this file, check whether it touches one of the
 * above -- if so, preserve the decision, don\'t just fix the new bug in
 * isolation. When you land a new locked decision, add it to this list.
 * ============================================================================
 */

add_action( 'wp_head', function () {
	if ( ! is_page() ) {
		return;
	}
	echo '<style>
		/* The PMPro checkout/login/levels pages use the plugin\'s own default white
		   card template -- the only part of the site not built in the dark/gold
		   theme. Restyle the card itself, then everything inside it, to match. */
		.pmpro_card {
			background: #0d0d0d !important;
			border: 1px solid rgba(212,175,55,0.25) !important;
			color: rgba(255,255,255,0.9) !important;
		}
		.pmpro_card p,
		.pmpro_card label,
		.pmpro_card span:not(.pmpro_btn *),
		.pmpro_card li,
		.pmpro_form_legend {
			color: rgba(255,255,255,0.85) !important;
		}
		.pmpro_card strong {
			color: #fff !important;
		}
		.pmpro_card_title,
		.pmpro_form_heading {
			/* Headings use a white-to-gold gradient clipped to the text -- this was
			   designed for the site\'s dark pages and reads fine now that the card
			   itself is dark too; no override needed here beyond letting it show. */
			opacity: 1 !important;
		}

		/* Inputs: dark field, visible border, readable typed text + placeholder. */
		.pmpro_card input[type="text"],
		.pmpro_card input[type="email"],
		.pmpro_card input[type="password"],
		.pmpro_card select,
		body.pmpro-login input#user_login,
		body.pmpro-login input#user_pass {
			background-color: #1a1a1a !important;
			color: #fff !important;
			border: 1px solid rgba(255,255,255,0.3) !important;
		}
		.pmpro_card input::placeholder,
		body.pmpro-login input::placeholder {
			color: rgba(255,255,255,0.4) !important;
		}
		.pmpro_card input:focus,
		.pmpro_card select:focus,
		body.pmpro-login input#user_login:focus,
		body.pmpro-login input#user_pass:focus {
			border-color: #d4af37 !important;
			outline: none;
			box-shadow: 0 0 0 2px rgba(212,175,55,0.35);
		}

		/* Checkout submit button: align to the bottom-right of the form instead of
		   the default left edge. Its container is a flex row, so text-align has no
		   effect -- justify-content is the correct property here. */
		body.pmpro-checkout .pmpro_form_submit {
			/* This flex row also contains a visibility:hidden #pmpro_processing_message
			   sibling that still reserves its own width, which threw off
			   justify-content centering (it centered the pair, not just the button).
			   Switch to block + text-align so the button centers on its own. */
			display: block !important;
			text-align: center !important;
		}
		body.pmpro-checkout .pmpro_form_submit #pmpro_processing_message {
			display: block;
			margin-top: 8px;
		}

		/* PMPro\'s buttons and the "Show Password" toggle were never themed --
		   they render in the plugin\'s factory-default navy (rgb(12,61,84)) and
		   Arial, which is why they read as unstyled/generic against the rest of
		   the site. Restyle as a solid gold primary action in the site\'s own
		   font, with a real hover/active state instead of a flat color swap. */
		.pmpro_card input[type="submit"],
		.pmpro_card .pmpro_btn:not(.pmpro_btn-plain),
		body.pmpro-login input#wp-submit {
			background: linear-gradient(135deg, #e8c565 0%, #d4af37 100%) !important;
			color: #0d0d0d !important;
			border: none !important;
			border-radius: 10px !important;
			font-family: "Inter", -apple-system, sans-serif !important;
			font-weight: 700 !important;
			font-size: 0.95rem !important;
			letter-spacing: 0.01em;
			padding: 14px 28px !important;
			cursor: pointer;
			box-shadow: 0 2px 10px rgba(212,175,55,0.25);
			transition: transform 0.15s ease, box-shadow 0.15s ease, background 0.15s ease;
		}
		.pmpro_card input[type="submit"]:hover,
		.pmpro_card .pmpro_btn:not(.pmpro_btn-plain):hover,
		body.pmpro-login input#wp-submit:hover {
			background: linear-gradient(135deg, #f0d375 0%, #ddc047 100%) !important;
			transform: translateY(-1px);
			box-shadow: 0 4px 16px rgba(212,175,55,0.4);
		}
		.pmpro_card input[type="submit"]:active,
		.pmpro_card .pmpro_btn:not(.pmpro_btn-plain):active,
		body.pmpro-login input#wp-submit:active {
			transform: translateY(0);
			box-shadow: 0 2px 8px rgba(212,175,55,0.3);
		}
		.pmpro_card input[type="submit"]:focus-visible,
		.pmpro_card .pmpro_btn:not(.pmpro_btn-plain):focus-visible,
		body.pmpro-login input#wp-submit:focus-visible {
			outline: 2px solid #fff;
			outline-offset: 2px;
		}

		/* "Show Password" toggle: a plain inline text control, not a button --
		   reset the plugin\'s default button chrome (navy bg, border, padding)
		   entirely rather than styling it as a second primary action. */
		.pmpro_card button.pmpro_btn-plain {
			background: transparent !important;
			border: none !important;
			box-shadow: none !important;
			padding: 4px !important;
		}
		.pmpro_card .pmpro_form_field-password-toggle-state,
		.pmpro_card button.pmpro_btn-plain {
			color: #d4af37 !important;
			font-family: "Inter", -apple-system, sans-serif !important;
			font-weight: 600;
		}
		.pmpro_card button.pmpro_btn-plain:hover {
			color: #e8c565 !important;
		}

		/* Secondary links ("Log in here", "Lost Password?") -- gold on hover
		   instead of the default browser blue/underline-only treatment. */
		.pmpro_card a,
		body.pmpro-login a {
			color: rgba(255,255,255,0.85);
			font-family: "Inter", -apple-system, sans-serif;
			transition: color 0.15s ease;
		}
		.pmpro_card a:hover,
		body.pmpro-login a:hover {
			color: #d4af37;
		}

		/* Email should come first -- it\'s the primary identifier a visitor expects
		   to enter first, and it\'s unconventional (and was flagged) to ask for a
		   password before the account it belongs to. The parent .pmpro_form_fields
		   is already a flex column, so `order` reliably swaps them without
		   touching the underlying DOM/field markup or submission behavior. */
		.pmpro_card .pmpro_form_field-bemail {
			order: -1;
		}

		/* On narrow screens the Password label and "Show Password" toggle share one
		   tight grid row and the toggle wraps awkwardly. Stack them instead. */
		@media (max-width: 480px) {
			.pmpro_card .pmpro_form_field-password {
				grid-template-columns: 1fr !important;
				row-gap: 6px;
			}
			.pmpro_card .pmpro_form_field-password-toggle {
				justify-self: start !important;
			}
		}

		/* Membership Levels table: same dark treatment for its cells. */
		.pmpro_table th,
		.pmpro_table td {
			background-color: #0d0d0d !important;
			color: rgba(255,255,255,0.9) !important;
			border-color: rgba(255,255,255,0.1) !important;
		}
	</style>';
}, 20 );

// The mobile hamburger menu opened onto a black overlay, but its nav links inherited
// the theme\'s default near-black text color (rgb(17,17,17)) -- invisible on the same
// black background. This is site-wide (every page has this nav), so it isn\'t scoped
// to is_page() like the PMPro-specific fixes above.
add_action( 'wp_head', function () {
	echo '<style>
		/* Every nav item (all five links) AND the "AuditionCollective" site title use
		   the same white-to-gold diagonal gradient clipped to the text as the page
		   headings -- this is the site\'s one consistent brand text treatment, not
		   just something for the current-page highlight. (First pass here only fixed
		   the mobile-menu invisible-text bug with flat white; second pass added the
		   gradient back for just the current page; PM asked for it on every nav item
		   and the logo too, for full consistency.) */
		.wp-block-navigation__responsive-container-content .wp-block-navigation-item__content,
		.wp-block-navigation__responsive-container-content .wp-block-navigation-item__label,
		.wp-block-site-title,
		.wp-block-site-title a,
		.pmpro_card a.ac-gradient-text {
			background: linear-gradient(135deg, #fff 0%, #d4af37 100%) !important;
			-webkit-background-clip: text !important;
			background-clip: text !important;
			-webkit-text-fill-color: transparent !important;
			color: #d4af37 !important; /* fallback for browsers without background-clip:text */
		}
		.wp-block-navigation__responsive-container-content .wp-block-navigation-item__content:hover,
		.wp-block-navigation__responsive-container-content .wp-block-navigation-item__content:hover .wp-block-navigation-item__label {
			background: none !important;
			-webkit-text-fill-color: #f0d375 !important;
			color: #f0d375 !important;
		}

		/* "Log in here" on the Create Account card, in the same gradient treatment. */
		.pmpro_card_actions a {
			background: linear-gradient(135deg, #fff 0%, #d4af37 100%) !important;
			-webkit-background-clip: text !important;
			background-clip: text !important;
			-webkit-text-fill-color: transparent !important;
			color: #d4af37 !important;
		}
	</style>';
}, 20 );

// Nav items that only make sense for one auth state: "Audition Board" was showing
// to logged-out visitors (who\'d just get redirected to /login/ on click), and
// "Sign Up"/"Log In" were still showing to already-logged-in members. Hide each
// per the viewer\'s actual state. Scoped to the nav\'s own responsive container so
// this can\'t hit unrelated same-URL links elsewhere on the page (e.g. "Log in
// here" inside the Create Account card, which should always stay visible there).
add_action( 'wp_head', function () {
	// Hide the whole <li> (.wp-block-navigation-item), not just the inner <a> --
	// the nav\'s flex container lays out the <li> elements, and hiding only the
	// link left an empty zero-width <li> that still consumed a gap on each side,
	// producing an uneven double-wide gap around the hidden item. :has() lets us
	// select the ancestor <li> from the link\'s href, so this stays a pure CSS fix.
	if ( is_user_logged_in() ) {
		echo '<style>
			.wp-block-navigation__responsive-container-content .wp-block-navigation-item:has(a[href*="/membership-checkout/"]),
			.wp-block-navigation__responsive-container-content .wp-block-navigation-item:has(a[href*="/login/"]) {
				display: none !important;
			}
		</style>';
	} else {
		echo '<style>
			.wp-block-navigation__responsive-container-content .wp-block-navigation-item:has(a[href*="/audition-board/"]) {
				display: none !important;
			}
		</style>';
	}
} );

// The default WordPress admin toolbar (Howdy, aaron / Edit Home Page / wp-admin
// links) was showing to regular member accounts -- confusing (implies edit access
// they don\'t have) and visually a totally unstyled gray bar clashing with the
// dark/gold site. Only real admins should see it.
add_filter( 'show_admin_bar', function ( $show ) {
	return current_user_can( 'manage_options' ) ? $show : false;
} );

// Rename PMPro's default page titles -- "Membership Checkout" / "Membership Levels"
// imply a paid-tiers product, which this isn\'t (one free tier, no payment).
add_filter( 'the_title', function ( $title, $post_id = null ) {
	if ( 71 === (int) $post_id ) {
		return 'Create Your Account';
	}
	if ( 74 === (int) $post_id ) {
		return 'Your Plan';
	}
	return $title;
}, 10, 2 );

// The browser tab <title> (bookmarks, history, search results) wasn\'t picking up the
// rename above -- `the_title` covers on-page headings, but the document title goes
// through a separate filter.
add_filter( 'document_title_parts', function ( $parts ) {
	if ( is_page( 71 ) ) {
		$parts['title'] = 'Create Your Account';
	} elseif ( is_page( 74 ) ) {
		$parts['title'] = 'Your Plan';
	}
	return $parts;
} );

// The Membership Levels page is a bare PMPro table with zero context -- reads like an
// unfinished pricing page rather than an intentional single-free-tier product. Add a
// short explanatory blurb above the table so it's clear this is deliberate.
add_action( 'wp_footer', function () {
	if ( function_exists( 'is_page' ) && is_page( 74 ) ) {
		echo '<script>
			document.addEventListener("DOMContentLoaded", function () {
				var table = document.querySelector(".pmpro_table, table.pmpro_levels");
				if (table && !document.getElementById("ac-levels-intro")) {
					var intro = document.createElement("p");
					intro.id = "ac-levels-intro";
					intro.style.cssText = "max-width:640px;margin:0 auto 24px;color:#fff;opacity:0.85;text-align:center;line-height:1.6;";
					intro.textContent = "AuditionCollective is free to join. Every listing on the Audition Board is available to any member at no cost — no paid tier required.";
					table.parentNode.insertBefore(intro, table);
				}
			});
		</script>';
	}
}, 30 );

// The Audition Board page itself was still fully viewable while logged out (only the
// underlying data query was locked down by the earlier wpda REST-auth fix) -- an
// anonymous visitor would see the filters and an "unable to load" message rather
// than being kept off the page entirely. Require login for the page itself now.
// After signing in, the login_redirect filter below sends them right back here.
add_action( 'template_redirect', function () {
	if ( function_exists( 'is_page' ) && is_page( 'audition-board' ) && ! is_user_logged_in() ) {
		wp_safe_redirect( home_url( '/login/' ) );
		exit;
	}
} );

// Same issue on "Your Plan" (membership-levels): a logged-out visitor could see a
// "Plan: Community Tier / Price: Free / Select" card as if they already had an
// account -- logically inconsistent for someone who hasn\'t signed up yet. Gate it.
add_action( 'template_redirect', function () {
	if ( function_exists( 'is_page' ) && is_page( 74 ) && ! is_user_logged_in() ) {
		wp_safe_redirect( home_url( '/login/' ) );
		exit;
	}
} );

// The [pmpro_login] shortcode's redirect_to="/audition-board/" attribute (set on the
// Login page) is silently ignored -- PMPro's shortcode_atts() whitelist for this
// shortcode doesn't include a redirect_to attribute at all, so it's dropped before
// the form is even built. Wire up the real WordPress post-login redirect instead.
// Admins are left alone (still land on wp-admin as expected).
add_filter( 'login_redirect', function ( $redirect_to, $requested_redirect_to, $user ) {
	if ( ! empty( $requested_redirect_to ) ) {
		return $requested_redirect_to; // respect an explicit ?redirect_to= if present
	}
	if ( is_a( $user, 'WP_User' ) ) {
		return home_url( '/audition-board/' );
	}
	return $redirect_to;
}, 10, 3 );

// Rebrand PMPro's default "membership" copy -- built around paid tiers -- for a
// free, single-tier product. Uses WP's own translation filter, so it's safe across
// plugin updates and doesn't touch plugin core files.
add_filter( 'gettext', function ( $translated, $original, $domain ) {
	// Scope to the front end only -- "Level" especially is generic enough that
	// renaming it inside wp-admin's own membership-level management screens would
	// confuse the site owner, not help a visitor.
	if ( 'paid-memberships-pro' !== $domain || is_admin() ) {
		return $translated;
	}
	$replacements = array(
		'Submit and Confirm'                          => 'Create Account',
		'Membership Information'                       => 'Your Free Account',
		'You have selected the %s membership level.'   => 'You\'ve selected the %s plan.',
		'The price for membership is <strong>%s</strong> now' => 'This plan is <strong>%s</strong>',
		'Level'                                        => 'Plan',
	);
	return $replacements[ $original ] ?? $translated;
}, 10, 3 );

// The Login page's "Username or Email Address" label is WordPress core's own default
// (wp_login_form() genuinely accepts either) -- but this site never shows anyone a
// username; it's auto-generated behind the scenes from their email at signup. Saying
// "Username" here implies there's one the visitor is supposed to know. Simplify to
// just "Email Address" for consistency with the Create Account form. Not scoped to
// is_admin() -- this should stay simplified on wp-login.php too if it's ever used.
add_filter( 'gettext', function ( $translated, $original ) {
	if ( 'Username or Email Address' === $original ) {
		return 'Email Address';
	}
	return $translated;
}, 10, 2 );

// Skip PMPro's default post-signup "Membership Confirmation" page entirely -- same
// "no checkout, seamless account creation" philosophy as the Create Account page
// itself (see the locked-decisions block at the top of this file). It repeats the
// "Membership"/"Community Tier" wording we\'ve deliberately removed everywhere else,
// and it\'s an unnecessary extra step: go straight to the Audition Board, exactly
// like a returning user landing there after login. Runs after the email-verification
// mu-plugin\'s own pmpro_after_checkout hook (priority 20) so that email still sends.
add_action( 'pmpro_after_checkout', function ( $user_id ) {
	wp_safe_redirect( home_url( '/audition-board/' ) );
	exit;
}, 30, 1 );

// Belt-and-suspenders: the hidden username field's wrapper is already display:none
// (which real screen readers already skip), but explicitly mark it aria-hidden and
// remove it from tab order too, so no assistive-tech edge case surfaces it.
//
// Also: there is no checkout at this stage of the product (a donation pipeline is
// planned for later, separately) -- so the plan/price summary card at the top of
// this page ("Your Free Account" / "This plan is $0.00") is removed entirely.
// Signing up should read as account creation, full stop, not a checkout flow with
// a $0 total. The account-fields card (email + password) is left untouched.
add_action( 'wp_footer', function () {
	if ( function_exists( 'is_page' ) && is_page( 'membership-checkout' ) ) {
		echo '<script>
			document.addEventListener("DOMContentLoaded", function () {
				var wrap = document.querySelector(".pmpro_form_field-username");
				if (wrap) {
					wrap.setAttribute("aria-hidden", "true");
				}
				var uf = document.getElementById("username");
				if (uf) {
					uf.setAttribute("tabindex", "-1");
					uf.setAttribute("aria-hidden", "true");
				}

				// cards[0] = plan/price card (hidden), cards[1] = Account Information
				// (kept -- this is the one we attach the button/login-link to). Billing
				// Address / Payment Information (cards 2/3) are already hidden upstream
				// via their fieldset\'s display:none, from the earlier signup-simplify fix.
				var cards = document.querySelectorAll(".pmpro_card");
				if (cards[0]) {
					cards[0].style.display = "none";
				}
				var accountCard = cards[1] || null;
				// The submit button lives outside the card entirely, and the
				// "Already have an account?" text already sits inside the card\'s
				// own .pmpro_card_actions container. Move the button into that same
				// container, ahead of the login text, so the card reads: fields,
				// then primary action (full-width button), then the secondary
				// login link beneath it -- matching the Login page\'s layout.
				var submitBtn = document.getElementById("pmpro_btn-submit");
				var submitWrap = submitBtn ? (submitBtn.closest(".pmpro_form_submit") || submitBtn.parentElement) : null;
				var actions = accountCard ? accountCard.querySelector(".pmpro_card_actions") : null;
				if (actions && submitWrap) {
					actions.style.display = "flex";
					actions.style.flexDirection = "column";
					actions.style.alignItems = "center";
					actions.style.gap = "16px";
					actions.insertBefore(submitWrap, actions.firstChild);
					submitWrap.style.width = "100%";
					submitWrap.style.order = "-1";
					if (submitBtn) {
						submitBtn.style.width = "100%";
					}
				}
			});
		</script>';
	}
}, 30 );
