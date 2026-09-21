<?php
/**
 * Plugin Name: Audition Collective - Email Verification
 * Description: Sends a confirmation email after signup with a one-click verify link. Tracks verified status in user meta for future subscriber notifications.
 */

define( 'AC_VERIFY_QUERY_VAR', 'ac_verify' );

// Generate a token, mark the user unverified, and send the confirmation email right after checkout.
add_action( 'pmpro_after_checkout', function ( $user_id ) {
	$user = get_userdata( $user_id );
	if ( ! $user ) {
		return;
	}

	$token = wp_generate_password( 32, false );
	update_user_meta( $user_id, 'ac_email_verified', 0 );
	update_user_meta( $user_id, 'ac_email_verify_token', $token );

	$verify_url = add_query_arg(
		array(
			AC_VERIFY_QUERY_VAR => $token,
			'uid'                => $user_id,
		),
		home_url( '/' )
	);

	$subject = 'Confirm your email - AuditionCollective';
	$message  = "Hi {$user->user_login},\n\n";
	$message .= "Thanks for joining AuditionCollective! Please confirm your email address by clicking the link below:\n\n";
	$message .= $verify_url . "\n\n";
	$message .= "If you didn't create this account, you can ignore this email.\n";

	wp_mail( $user->user_email, $subject, $message );
}, 20, 1 );

// Handle the verification link click.
add_action( 'template_redirect', function () {
	if ( empty( $_GET[ AC_VERIFY_QUERY_VAR ] ) || empty( $_GET['uid'] ) ) {
		return;
	}

	$user_id = absint( $_GET['uid'] );
	$token   = sanitize_text_field( wp_unslash( $_GET[ AC_VERIFY_QUERY_VAR ] ) );
	$stored  = get_user_meta( $user_id, 'ac_email_verify_token', true );

	if ( empty( $stored ) || ! hash_equals( $stored, $token ) ) {
		wp_die( 'This verification link is invalid or has already been used. <a href="' . esc_url( home_url( '/' ) ) . '">Return home</a>.', 'Verification failed', array( 'response' => 200 ) );
	}

	update_user_meta( $user_id, 'ac_email_verified', 1 );
	delete_user_meta( $user_id, 'ac_email_verify_token' );

	// Log the user in automatically once verified, then send them to the audition board.
	$user = get_userdata( $user_id );
	if ( $user ) {
		wp_set_current_user( $user_id );
		wp_set_auth_cookie( $user_id );
	}

	wp_safe_redirect( add_query_arg( 'verified', '1', home_url( '/audition-board/' ) ) );
	exit;
} );

// Simple banner on the audition board confirming verification succeeded.
add_action( 'wp_head', function () {
	if ( ! empty( $_GET['verified'] ) && is_page( 'audition-board' ) ) {
		echo '<style>.ac-verified-banner{background:#1f5c3a;color:#fff;padding:12px 20px;text-align:center;font-weight:600;}</style>';
	}
} );
add_action( 'wp_body_open', function () {
	if ( ! empty( $_GET['verified'] ) && is_page( 'audition-board' ) ) {
		echo '<div class="ac-verified-banner">Your email is confirmed! Welcome to AuditionCollective.</div>';
	}
} );
