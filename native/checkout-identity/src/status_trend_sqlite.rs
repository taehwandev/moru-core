//! Owner: read-only status trend SQLite input and bounded projections.
//! Allowed: std, bundled rusqlite and serde_json. Forbidden: writes, network,
//! arbitrary queries and report policy. Callers: the private completion probe.
use rusqlite::{types::ValueRef, Connection, OpenFlags};
use serde_json::{json, Value};
use std::{collections::HashSet, fs, io, path::Path, time::Duration};

#[path = "status_trend_codex_db.rs"]
mod codex;
use super::status_trend_stamp as stamp;

pub(super) struct TrendSqlite;

impl TrendSqlite {
    pub(super) fn read(request: &Value) -> Option<Value> {
        let query = match request.get("dataset")?.as_str()? {
            "codex" => codex::read,
            "spill" => Self::spill,
            _ => return None,
        };
        let wanted = request
            .get("ids")?
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<HashSet<_>>>()?;
        let connection = Self::open(request.get("path")?.as_str()?)?;
        query(&connection, &wanted)
    }

    fn open(raw: &str) -> Option<Connection> {
        // The reference interpolates this path into a SQLite URI.
        if raw.contains(['?', '#', '%', '\0']) {
            return None;
        }
        let path = Path::new(raw).canonicalize().ok()?;
        if !fs::metadata(&path).ok()?.is_file() {
            return None;
        }
        let name = path.file_name()?.to_str()?;
        for suffix in ["-wal", "-shm", "-journal"] {
            match fs::symlink_metadata(path.with_file_name(format!("{name}{suffix}"))) {
                Ok(metadata) if metadata.is_file() => {}
                Err(error) if error.kind() == io::ErrorKind::NotFound => {}
                _ => return None,
            }
        }
        let connection = Connection::open_with_flags(
            path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .ok()?;
        connection.busy_timeout(Duration::ZERO).ok()?;
        Some(connection)
    }

    fn spill(connection: &Connection, wanted: &HashSet<&str>) -> Option<Value> {
        // Keep exactly the reference query and row order. Equal event timestamps
        // are stable-sorted by the caller, so scan order affects the final model.
        let mut statement = connection
            .prepare(
                "SELECT run_id, created_at, COALESCE(model, ''), \
                 (COALESCE(accounting_uncached_input_tokens, 0)*1.0 + COALESCE(accounting_cache_creation_input_tokens, 0)*1.25 + \
                 COALESCE(accounting_cache_read_input_tokens, 0)*0.1 + COALESCE(output_tokens, 0)*1.0), \
                 COALESCE(total_tokens, 0), COALESCE(accounting_reasoning_output_tokens, 0) \
                 FROM token_usage_events WHERE run_id IS NOT NULL",
            )
            .ok()?;
        let mut query = statement.query([]).ok()?;
        let mut rows = Vec::new();
        let mut budget = 0;
        while let Some(row) = query.next().ok()? {
            let id = text(row.get_ref(0).ok()?)?;
            let stamp = text(row.get_ref(1).ok()?)?;
            let model = text(row.get_ref(2).ok()?)?;
            // Python fetchall decodes TEXT even in unselected events.
            for index in 3..6 {
                if let ValueRef::Text(bytes) = row.get_ref(index).ok()? {
                    std::str::from_utf8(bytes).ok()?;
                }
            }
            if !wanted.contains(id) {
                continue;
            }
            let weighted = row.get::<_, Option<f64>>(3).ok()?.unwrap_or(0.0);
            let total: i64 = row.get(4).ok()?;
            let reasoning: i64 = row.get(5).ok()?;
            if !weighted.is_finite() {
                return None;
            }
            let stamp = stamp::utc(stamp)?;
            push_row(
                &mut rows,
                &mut budget,
                json!([id, stamp, model, weighted, total, reasoning]),
            )?;
        }
        Some(json!({"rows": rows}))
    }
}

fn text(cell: ValueRef<'_>) -> Option<&str> {
    match cell {
        ValueRef::Null => Some(""),
        ValueRef::Text(bytes) if bytes.len() <= MAX_ROW_BYTES => std::str::from_utf8(bytes).ok(),
        _ => None,
    }
}

const MAX_ROW_BYTES: usize = 512 * 1024;

fn push_row(rows: &mut Vec<Value>, budget: &mut usize, row: Value) -> Option<()> {
    *budget = budget.checked_add(serde_json::to_vec(&row).ok()?.len() + 1)?;
    if *budget > MAX_ROW_BYTES {
        return None;
    }
    rows.push(row);
    Some(())
}
