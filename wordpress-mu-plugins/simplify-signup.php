<?php
/**
 * Plugin Name: Audition Collective - Simplify Signup
 * Description: Auto-generates the PMPro username from the submitted email address and removes the duplicate Confirm Password / Confirm Email fields, so signup only asks for email + password.
 */

// Remove the "Confirm Password" and "Confirm Email" duplicate fields at checkout.
add_filter( 'pmpro_checkout_confirm_password', '__return_false' );
add_filter( 'pmpro_checkout_confirm_email', '__return_false' );

// Hide the Username field visually and strip its "required" attribute (a hidden required field silently blocks
// HTML5 form submission in every browser, with no visible error), then auto-fill it from the email field on submit.
add_action( 'wp_footer', function () {
	if ( function_exists( 'is_page' ) && is_page( 'membership-checkout' ) ) {
		echo '<style>.pmpro_form_field-username{display:none !important;}</style>';
		echo '<script>
			document.addEventListener("DOMContentLoaded", function () {
				var uf = document.getElementById("username");
				if (uf) { uf.removeAttribute("required"); }
				var form = document.querySelector("#pmpro_form, form.pmpro_form, form#pmForm");
				if (form) {
					form.addEventListener("submit", function () {
						var email = document.getElementById("bemail");
						if (uf && email && email.value) {
							uf.value = email.value.split("@")[0];
						}
					});
				}
			});
		</script>';
	}
} );

// Auto-fill the username from the email address before PMPro validates the checkout submission.
add_action( 'init', function () {
	if ( empty( $_REQUEST['username'] ) && ! empty( $_REQUEST['bemail'] ) && is_email( $_REQUEST['bemail'] ) ) {
		if ( function_exists( 'pmpro_generateUsername' ) ) {
			$_REQUEST['username'] = pmpro_generateUsername( '', '', sanitize_email( $_REQUEST['bemail'] ) );
			$_POST['username']    = $_REQUEST['username'];
		}
	}
}, 5 );
