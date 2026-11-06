//! Owner: one existing canonical work-card store's close transaction.
//! Allowed: rusqlite, std and CardStore's path validation. Forbidden: creation,
//! migrations, triggers, liveness, resume, retries or fallback after DML.
//! Callers/tests: CardsProcess; test_native_card_settlement and bundle smoke.
use crate::cards_store::CardStore;
use rusqlite::{Connection, OpenFlags};
use std::{path::Path, time::Duration};

// Frozen eligibility signature, not a schema creator. Compare the complete
// stored definition so unknown constraints/defaults cannot enter the writer.
const SCHEMA: &str = "CREATE TABLE cards (
    repo TEXT NOT NULL,
    work_id TEXT NOT NULL,
    summary TEXT NOT NULL,
    command TEXT NOT NULL,
    project TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('active', 'done', 'cancelled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    run_id TEXT NOT NULL DEFAULT '',
    runtime TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (repo, work_id)
)";

pub(crate) struct CardSettlement(Connection);

impl CardSettlement {
    pub(crate) fn open(path: &Path) -> Option<Self> {
        let path = CardStore::path(path)??;
        let connection = Connection::open_with_flags(
            path,
            OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .ok()?;
        connection.busy_timeout(Duration::ZERO).ok()?;
        // Reserve the writer before inspecting schema, blocking concurrent DDL
        // and competing writers. Closing on decline releases this transaction.
        connection.execute_batch("BEGIN IMMEDIATE").ok()?;
        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .ok()?;
        let mode: String = connection
            .query_row("PRAGMA journal_mode", [], |r| r.get(0))
            .ok()?;
        if version != 3 || mode != "wal" {
            return None;
        }
        let sql: String = connection
            .query_row(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='cards'",
                [],
                |r| r.get(0),
            )
            .ok()?;
        if sql.split_whitespace().ne(SCHEMA.split_whitespace()) {
            return None;
        }
        let custom: i64 = connection
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' OR \
             (type='index' AND tbl_name='cards' AND sql IS NOT NULL)",
                [],
                |r| r.get(0),
            )
            .ok()?;
        (custom == 0).then_some(Self(connection))
    }

    pub(crate) fn settle(
        self,
        repo: &str,
        work: &str,
        state: &str,
        stamp: &str,
    ) -> Result<bool, String> {
        // Once UPDATE is attempted, return success/error without Python retry.
        // SQLite rolls back on connection close if UPDATE/COMMIT fails.
        let changed = self
            .0
            .execute(
                "UPDATE cards SET state = ?1, updated_at = ?2 \
             WHERE repo = ?3 AND work_id = ?4 AND state = 'active'",
                [state, stamp, repo, work],
            )
            .map_err(message)?;
        self.0.execute_batch("COMMIT").map_err(message)?;
        Ok(changed != 0)
    }
}

fn message(error: rusqlite::Error) -> String {
    match error {
        rusqlite::Error::SqliteFailure(_, Some(message)) => message,
        other => other.to_string(),
    }
}
