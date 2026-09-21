<?php
/**
 * Plugin Name: Audition Collective - Automated Expiry Purge
 * Description: Daily job (via WP-Cron) that purges audition records whose relevant
 * dates have all passed, and backfills the standard placeholder for any orchestra
 * left with zero real records afterward. This is the automated version of what
 * execution/find_expired_auditions.py did manually -- same staleness rule from
 * AUDITION_CAPTURE.md: a record is a purge candidate once final_audition (or
 * preliminary_audition, if no final date exists) is in the past.
 *
 * Runs against the orchestras/auditions database (a separate MySQL database from
 * WordPress's own -- same host, different DB name/credentials from wp-config.php's
 * constants below) via a direct mysqli connection, same credentials pattern used
 * by the WP Data Access app that powers the live Audition Board.
 *
 * Every run logs a summary to the `ac_expiry_purge_log` option (last 30 runs kept)
 * so results are auditable from wp-admin without needing SSH.
 */

if ( ! defined( 'AC_ORCH_DB_HOST' ) ) {
	define( 'AC_ORCH_DB_HOST', 'localhost' );
	define( 'AC_ORCH_DB_USER', 'u715111901_Admin' );
	define( 'AC_ORCH_DB_PASS', 'Ballstate00!' );
	define( 'AC_ORCH_DB_NAME', 'u715111901_OrchAudRepo' );
}

// Register the daily schedule on plugin load if not already scheduled.
add_action( 'init', function () {
	if ( ! wp_next_scheduled( 'ac_daily_expiry_purge' ) ) {
		wp_schedule_event( time(), 'daily', 'ac_daily_expiry_purge' );
	}
} );

add_action( 'ac_daily_expiry_purge', 'ac_run_expiry_purge' );

function ac_run_expiry_purge() {
	$mysqli = mysqli_init();
	if ( ! $mysqli || ! @$mysqli->real_connect( AC_ORCH_DB_HOST, AC_ORCH_DB_USER, AC_ORCH_DB_PASS, AC_ORCH_DB_NAME ) ) {
		ac_log_purge_run( array( 'error' => 'DB connection failed: ' . mysqli_connect_error() ) );
		return;
	}

	$purged      = array();
	$placeholders = array();

	// 1. Find expired real records (placeholder rows never match this -- their
	// dates are always NULL). Purge trigger is the FINAL audition date only --
	// a passed preliminary audition date or application deadline never causes
	// a purge on its own, even if final_audition is NULL (no known final date
	// means we can't confirm the audition process is actually over).
	$result = $mysqli->query(
		"SELECT a.id, o.id AS orchestra_id, o.name, a.position, a.final_audition, a.preliminary_audition
		 FROM auditions a
		 JOIN orchestras o ON o.id = a.orchestra_id
		 WHERE a.final_audition IS NOT NULL AND a.final_audition < CURDATE()"
	);

	if ( ! $result ) {
		ac_log_purge_run( array( 'error' => 'Query failed: ' . $mysqli->error ) );
		$mysqli->close();
		return;
	}

	$expired_ids       = array();
	$affected_orchestras = array();
	while ( $row = $result->fetch_assoc() ) {
		$expired_ids[]        = (int) $row['id'];
		$affected_orchestras[ (int) $row['orchestra_id'] ] = $row['name'];
		$purged[] = $row['name'] . ' -- ' . $row['position'] . ' (final: ' . ( $row['final_audition'] ?: $row['preliminary_audition'] ) . ')';
	}

	// 2. Purge them, all at once.
	if ( ! empty( $expired_ids ) ) {
		$ids_sql = implode( ',', $expired_ids );
		$mysqli->query( "DELETE FROM auditions WHERE id IN ($ids_sql)" );
	}

	// 3. For each affected orchestra, check whether it now has zero real records
	// left -- if so, backfill the standard placeholder.
	foreach ( $affected_orchestras as $orchestra_id => $orchestra_name ) {
		$check = $mysqli->query( "SELECT COUNT(*) AS c FROM auditions WHERE orchestra_id = " . (int) $orchestra_id );
		$row   = $check ? $check->fetch_assoc() : array( 'c' => 1 );
		if ( 0 === (int) $row['c'] ) {
			$mysqli->query(
				"INSERT INTO auditions (orchestra_id, position, instrumentation, application_deadline, preliminary_audition, final_audition, last_verified_at)
				 VALUES ($orchestra_id, 'No auditions reported at this time', 'N/A', NULL, NULL, NULL, NOW())"
			);
			$placeholders[] = $orchestra_name;
		}
	}

	$mysqli->close();

	ac_log_purge_run( array(
		'purged_count'       => count( $purged ),
		'purged'             => $purged,
		'placeholders_added' => $placeholders,
	) );
}

function ac_log_purge_run( $summary ) {
	$log   = get_option( 'ac_expiry_purge_log', array() );
	$entry = array_merge( array( 'run_at' => current_time( 'mysql' ) ), $summary );
	array_unshift( $log, $entry );
	$log = array_slice( $log, 0, 30 ); // keep the last 30 runs
	update_option( 'ac_expiry_purge_log', $log, false );
}

// WP-CLI command for manual testing/verification without waiting for the schedule.
if ( defined( 'WP_CLI' ) && WP_CLI ) {
	WP_CLI::add_command( 'ac-purge-expired', function () {
		ac_run_expiry_purge();
		$log = get_option( 'ac_expiry_purge_log', array() );
		WP_CLI::success( 'Run complete. ' . print_r( $log[0] ?? array(), true ) );
	} );
}
