//! owner: CardTransaction; one existing canonical work-card store's write transaction.
//! Allowed: rusqlite, std and CardStore's path validation. Forbidden: creation,
//! migrations, triggers, liveness, resume, retries or fallback after DML.
//! Callers/tests: CardsProcess, prepared card adapter; transaction atomicity tests.
use crate::cards_store::CardStore;
use rusqlite::{Connection, OpenFlags};
use std::{path::Path, time::Duration};

// Frozen eligibility signature, not a schema creator. Compare the complete
// stored definition so unknown constraints/defaults cannot enter the writer.
const SCHEMA: &str = crate::cards_schema::CardSchema::SIGNATURE;

pub(crate) struct CardTransaction(Connection);

impl CardTransaction {
    pub(crate) fn open(path: &Path) -> Option<Self> {
        Self::acquire(path, None)
    }

    pub(crate) fn prepared(path: &Path, foreign_keys: bool) -> Option<Self> {
        Self::acquire(path, Some(foreign_keys))
    }

    fn acquire(path: &Path, foreign_keys: Option<bool>) -> Option<Self> {
        let path = CardStore::path(path)??;
        let connection = Connection::open_with_flags(
            path,
            OpenFlags::SQLITE_OPEN_READ_WRITE | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .ok()?;
        connection.busy_timeout(Duration::ZERO).ok()?;
        if let Some(enabled) = foreign_keys {
            // The parent's Python connection chooses enforcement. SQLite build
            // defaults differ, and changing this pragma after BEGIN has no effect.
            connection
                .pragma_update(None, "foreign_keys", enabled)
                .ok()?;
            let actual: bool = connection
                .query_row("PRAGMA foreign_keys", [], |row| row.get(0))
                .ok()?;
            if actual != enabled {
                return None;
            }
        }
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
        if if foreign_keys.is_some() {
            !Self::prepared_schema(&sql)
        } else {
            sql.split_whitespace().ne(SCHEMA.split_whitespace())
        } {
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
        if custom != 0 || (foreign_keys.is_none() && Self::incoming_foreign_keys(&connection)?) {
            return None;
        }
        Some(Self(connection))
    }

    fn incoming_foreign_keys(connection: &Connection) -> Option<bool> {
        let mut tables = connection
            .prepare("SELECT name FROM sqlite_master WHERE type='table'")
            .ok()?;
        let names = tables
            .query_map([], |row| row.get::<_, String>(0))
            .ok()?
            .collect::<Result<Vec<_>, _>>()
            .ok()?;
        let mut keys = connection.prepare(
            "SELECT EXISTS(SELECT 1 FROM pragma_foreign_key_list(?1) WHERE \"table\" = ?2 COLLATE NOCASE)",
        ).ok()?;
        for name in names {
            if keys
                .query_row([name.as_str(), "cards"], |row| row.get::<_, bool>(0))
                .ok()?
            {
                return Some(true);
            }
        }
        Some(false)
    }

    pub(crate) fn settle(
        self,
        repo: &str,
        work: &str,
        state: &str,
        stamp: &str,
    ) -> Result<bool, rusqlite::Error> {
        // Once UPDATE is attempted, return success/error without Python retry.
        // SQLite rolls back on connection close if UPDATE/COMMIT fails.
        let changed = self.0.execute(
            "UPDATE cards SET state = ?1, updated_at = ?2 \
             WHERE repo = ?3 AND work_id = ?4 AND state = 'active'",
            [state, stamp, repo, work],
        )?;
        self.0.execute_batch("COMMIT")?;
        Ok(changed != 0)
    }

    pub(crate) fn upsert(
        self,
        values: &[String; 10],
        cutoff: &str,
    ) -> Result<bool, rusqlite::Error> {
        self.0.execute(
            "INSERT INTO cards (repo, work_id, summary, command, project, state, \
             created_at, updated_at, run_id, runtime, session_id) \
             VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?) \
             ON CONFLICT (repo, work_id) DO UPDATE SET summary = excluded.summary, \
             command = excluded.command, project = excluded.project, \
             state = 'active', updated_at = excluded.updated_at, run_id = excluded.run_id, \
             runtime = excluded.runtime, session_id = excluded.session_id",
            rusqlite::params_from_iter(values.iter()),
        )?;
        self.0
            .execute("DELETE FROM cards WHERE updated_at < ?", [cutoff])?;
        self.0.execute_batch("COMMIT")?;
        Ok(true)
    }

    pub(crate) fn message(error: rusqlite::Error) -> String {
        match error {
            rusqlite::Error::SqliteFailure(_, Some(message)) => message,
            other => other.to_string(),
        }
    }

    fn prepared_schema(sql: &str) -> bool {
        let Some(actual) = Self::tokens(sql) else {
            return false;
        };
        (0..8).any(|mask| {
            Self::tokens(&Self::schema_variant(mask)).is_some_and(|known| known == actual)
        })
    }

    fn schema_variant(mask: u8) -> String {
        let names = ["run_id", "runtime", "session_id"];
        let mut base = SCHEMA.to_owned();
        for name in names {
            base = base.replace(&format!("    {name} TEXT NOT NULL DEFAULT '',\n"), "");
        }
        let mut columns = String::new();
        // ALTER appends missing columns before the table PRIMARY KEY constraint.
        for present in [true, false] {
            for (index, name) in names.iter().enumerate() {
                if (mask & (1 << index) != 0) == present {
                    columns.push_str(&format!("{name} TEXT NOT NULL DEFAULT '', "));
                }
            }
        }
        base.replace("    PRIMARY KEY", &format!("    {columns}PRIMARY KEY"))
    }

    // Discard whitespace between SQL tokens, retaining literal/identifier bytes.
    // Quoted escapes stay in their token, so an unfamiliar default cannot collapse
    // into the empty-string defaults in one of our frozen schema signatures.
    fn tokens(sql: &str) -> Option<Vec<String>> {
        let mut chars = sql.chars().peekable();
        let mut tokens = Vec::new();
        while let Some(character) = chars.next() {
            if character.is_ascii_whitespace() {
                continue;
            }
            let mut token = character.to_string();
            if matches!(character, '\'' | '"' | '`' | '[') {
                let end = if character == '[' { ']' } else { character };
                loop {
                    let next = chars.next()?;
                    token.push(next);
                    if next == end {
                        if chars.peek() == Some(&end) {
                            token.push(chars.next()?);
                        } else {
                            break;
                        }
                    }
                }
            } else if character.is_ascii_alphanumeric() || character == '_' {
                while chars
                    .peek()
                    .is_some_and(|next| next.is_ascii_alphanumeric() || *next == '_')
                {
                    token.push(chars.next()?);
                }
            }
            tokens.push(token);
        }
        Some(tokens)
    }
}

#[cfg(test)]
#[path = "cards_transaction_tests.rs"]
mod tests;
