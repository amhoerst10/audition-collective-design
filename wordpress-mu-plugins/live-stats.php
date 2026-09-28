<?php
/**
 * Plugin Name: Audition Collective - Live Homepage Stats
 * Description: [ac_stat type="orchestras|open|states"] shortcode that shows live
 * counts from the orchestras/auditions tables, cached for one hour. Replaces
 * hardcoded homepage numbers that had drifted (the homepage said 347 open
 * listings when the database held 240, 2026-09-28).
 *
 * WordPress runs on the same database as the audition data, so this uses $wpdb:
 * no extra MySQL connection (the remote user is capped at 500 connections/hour).
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

function ac_live_stats() {
	$stats = get_transient( 'ac_live_stats' );
	if ( is_array( $stats ) ) {
		return $stats;
	}
	global $wpdb;
	$placeholder = 'No auditions reported at this time';
	$stats       = array(
		'orchestras' => (int) $wpdb->get_var( 'SELECT COUNT(*) FROM orchestras' ),
		'open'       => (int) $wpdb->get_var( $wpdb->prepare( 'SELECT COUNT(*) FROM auditions WHERE position <> %s', $placeholder ) ),
		'states'     => (int) $wpdb->get_var( "SELECT COUNT(DISTINCT state) FROM orchestras WHERE state IS NOT NULL AND state <> ''" ),
	);
	// Don't cache a failed query as zeros; show the last good numbers instead.
	if ( $stats['orchestras'] > 0 ) {
		set_transient( 'ac_live_stats', $stats, HOUR_IN_SECONDS );
		update_option( 'ac_live_stats_last_good', $stats, false );
	} else {
		$last = get_option( 'ac_live_stats_last_good' );
		if ( is_array( $last ) ) {
			$stats = $last;
		}
	}
	return $stats;
}

add_shortcode( 'ac_stat', function ( $atts ) {
	$atts  = shortcode_atts( array( 'type' => 'open' ), $atts, 'ac_stat' );
	$stats = ac_live_stats();
	$key   = sanitize_key( $atts['type'] );
	return isset( $stats[ $key ] ) ? esc_html( number_format_i18n( $stats[ $key ] ) ) : '';
} );

// Refresh right after the daily purge changes the counts. LiteSpeed's page
// cache stores the rendered homepage, so purge that too or the numbers freeze.
add_action( 'ac_daily_expiry_purge', function () {
	delete_transient( 'ac_live_stats' );
	do_action( 'litespeed_purge_url', home_url( '/' ) );
}, 99 );
