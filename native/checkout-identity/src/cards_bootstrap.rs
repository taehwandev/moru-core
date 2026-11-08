//! owner: CardBootstrap; allowed imports: rusqlite, CardStore path guard, CardSchema;
//! forbidden imports: directory/file creation, explicit transactions, DML, retry or fallback;
//! callers/tests: original idle Python connection bootstrap; schema/order/failure fixtures.
use crate::{cards_schema::CardSchema, cards_store::CardStore};
use rusqlite::{config::DbConfig, Connection, OpenFlags};
use std::{collections::HashSet, path::Path, time::Duration};

pub(crate) struct CardBootstrap(Connection);

impl CardBootstrap {
    pub(crate) fn open(path: &Path, foreign_keys: bool) -> Option<Self> {
        let path = CardStore::path(path)??;
        path.to_str()?;
        let connection = Connection::open_with_flags(
            path,
            OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .ok()?;
        connection.busy_timeout(Duration::ZERO).ok()?;
        // Configure only this connection before SQL; builder defaults can differ
        // from the original parent connection's foreign-key setting.
        if connection
            .set_db_config(DbConfig::SQLITE_DBCONFIG_ENABLE_FKEY, foreign_keys)
            .ok()?
            != foreign_keys
        {
            return None;
        }
        // A bounded zero-wait read lookahead refuses conversion errors before
        // WAL/DDL effects. The original path then retains its own error ordering.
        Self::columns(&connection).ok()?;
        connection.busy_timeout(Duration::from_secs(2)).ok()?;
        Some(Self(connection))
    }

    pub(crate) fn initialize(self) -> Result<Option<i64>, rusqlite::Error> {
        // No fallback from this point: even an unsupported version follows the
        // original WAL attempt, and successful DDL before a later error persists.
        self.0.execute_batch("PRAGMA journal_mode=WAL")?;
        let version: i64 = self
            .0
            .query_row("PRAGMA user_version", [], |row| row.get(0))?;
        if !(0..=3).contains(&version) {
            return Ok(Some(version));
        }
        self.0.execute_batch(&CardSchema::create())?;
        let columns = Self::columns(&self.0)?;
        for name in ["run_id", "runtime", "session_id"] {
            if !columns.contains(name) {
                self.0.execute_batch(&format!(
                    "ALTER TABLE cards ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
                ))?;
            }
        }
        self.0.execute_batch("PRAGMA user_version=3")?;
        Ok(None)
    }

    fn columns(connection: &Connection) -> Result<HashSet<String>, rusqlite::Error> {
        let mut statement = connection.prepare("PRAGMA table_info(cards)")?;
        let rows = statement.query_map([], |row| {
            // Python materializes the whole sqlite3.Row, including type/default
            // text; validating only name would overlook an invalid UTF-8 cell.
            let _: i64 = row.get(0)?;
            let name: String = row.get(1)?;
            let _: String = row.get(2)?;
            let _: i64 = row.get(3)?;
            let _: Option<String> = row.get(4)?;
            let _: i64 = row.get(5)?;
            Ok(name)
        })?;
        rows.collect()
    }
}

#[cfg(test)]
#[path = "cards_bootstrap_tests.rs"]
mod tests;
