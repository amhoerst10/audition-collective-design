# Directive: Scalability & Intelligent Change Detection

## 1. Vision
To transition the Audition Collective from an "Agent-Led Manual Audit" model to an "Autonomous Intelligent Watchtower" model. The goal is to reduce human intervention by 90% while maintaining 100% data integrity.

## 2. The Core Challenge: Semantic Change Detection
A robust system must distinguish between "Noisy Changes" (layout tweaks, font changes, header updates) and "Critical Vacancy Changes" (new dates, new positions, cancellations).

### Intelligent Comparison Logic
The system will operate on a **Triple-Check** logic:

1.  **Structured Extraction (Live)**: Use Firecrawl to extract current auditions into a JSON schema (Position, Instrumentation, Deadline, Prelim, Final).
2.  **Database Context (Stored)**: Retrieve all existing records for the specific `orchestra_id` from the SQL database.
3.  **Semantic Reconciliation (The "Brain")**:
    *   **LLM Analysis**: Pass both the *Live JSON* and the *DB JSON* to an LLM.
    *   **Instruction**: "Compare these two sets of data. Are there new vacancies? Have existing dates changed? Has a previously listed position disappeared? Ignore formatting changes."
    *   **Output**: A structured "Delta Report" with a high-confidence action:
        *   `ACTION_UPDATE`: Date or status change detected for an existing entry.
        *   `ACTION_INSERT`: Entirely new position discovered.
        *   `ACTION_PURGE`: Position exists in DB but is missing from Live (and date has passed).
        *   `ACTION_STABLE`: Data matches perfectly.

## 3. Scalable Architecture

### A. The Nightly Orchestrator
*   **Trigger**: A GitHub Action or n8n workflow runs at 3:00 AM.
*   **Batching**: Processes orchestras in batches of 50 to avoid API rate limits.
*   **Persistence**: Results are logged to a `wp_audit_logs` table in the database.

### B. The "Human-in-the-Loop" Exception Queue
*   Instead of a manual sweep, the system generates an **Alert Dashboard**.
*   **Red Flags**: Only items marked as `PURGE_REQUIRED` or `AMBIGUOUS` (Low Confidence) appear for manual agent review.
*   **Green Flags**: `STABLE` or `INSERT` (High Confidence) can be set to auto-sync, or wait for a single "Approve All" click.

## 4. Implementation Roadmap

### Phase 1: The Audit Engine (Current)
*   Standardize all `orchestras` URLs to be generic (e.g., `/auditions` rather than specific seasons).
*   Finalize the SQL schema to include a `last_verified_at` timestamp on every audition.

### Phase 2: Headless Comparison Script
*   Create `execution/autonomous_audit.py`.
*   This script will loop through the DB, hit the Firecrawl API, perform the JSON comparison, and output a CSV of "Proposed Changes."

### Phase 3: Dashboard Integration
*   Eliminate the Excel checklist as the primary control.
*   Expose the `wp_audit_logs` through a private WordPress page where the user can see:
    *   Total sites checked today.
    *   Sites requiring manual review.
    *   New vacancies discovered.

## 5. Security & Stability
*   **Conflict Resolution**: In the event of a mismatch between "Last Audit Date" and "Current Date," the system will default to the most conservative (Live) data.
*   **Safety Lock**: No "Purge" action will ever be taken automatically without a `Confidence > 95%` score or manual override.
