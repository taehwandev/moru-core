//! Owner: existing work-card database reads and legacy row projection.
//! Allowed: std, rusqlite, serde_json, existing filesystem resolver.
//! Forbidden: CREATE/migrations/card writes, immutable/no-lock reads or effects.
//! Callers/tests: cards_process; test_native_work_cards and consumer smoke.
use crate::discovery_fs::DiscoveryFs;
use rusqlite::{types::ValueRef, Connection, OpenFlags};
use serde_json::{json, Value};
use std::{collections::BTreeMap, fs, io, path::Path, time::Duration};

pub(crate) struct CardStore(Connection);

impl CardStore {
    pub(crate) fn open(path: &Path) -> Option<Option<Self>> {
        let parent = path.parent()?;
        match fs::symlink_metadata(parent) {
            Ok(meta) if meta.is_symlink() => return Some(None),
            Err(e) if e.kind() == io::ErrorKind::NotFound => return Some(None),
            Err(_) => return None,
            _ => {}
        }
        match fs::metadata(path) {
            Ok(meta) if meta.is_file() => {}
            Ok(_) => return Some(None),
            Err(e)
                if matches!(
                    e.raw_os_error(),
                    Some(libc::ENOENT | libc::ENOTDIR | libc::ELOOP)
                ) =>
            {
                return Some(None)
            }
            Err(_) => return None,
        }
        let path = DiscoveryFs::resolve(path)?;
        for suffix in ["-wal", "-shm", "-journal"] {
            let sidecar = path.with_file_name(format!("{}{suffix}", path.file_name()?.to_str()?));
            if fs::symlink_metadata(sidecar).is_ok_and(|m| m.is_symlink()) {
                return None;
            }
        }
        let connection = Connection::open_with_flags(
            &path,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .ok()?;
        // Native uncertainty defers immediately; Python retains its original
        // two-second busy wait instead of adding a second wait here.
        connection.busy_timeout(Duration::ZERO).ok()?;
        let version: i64 = connection
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .ok()?;
        if !(0..=3).contains(&version) {
            return None;
        }
        let exists: bool = connection
            .query_row(
                "SELECT EXISTS(SELECT 1 FROM sqlite_master WHERE type='table' AND name='cards')",
                [],
                |r| r.get(0),
            )
            .ok()?;
        if !exists {
            return Some(None);
        }
        // Unknown indexes may choose a different order for equal timestamps.
        let indexes: i64 = connection.query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND tbl_name='cards' AND sql IS NOT NULL",
            [], |r| r.get(0)).ok()?;
        if indexes != 0 {
            return None;
        }
        Some(Some(Self(connection)))
    }

    pub(crate) fn list(&self, repo: &str, all: bool) -> Option<Vec<BTreeMap<String, Value>>> {
        let sql = if all {
            "SELECT * FROM cards WHERE repo = ?1 AND state IN ('active','done','cancelled') ORDER BY updated_at DESC"
        } else {
            "SELECT * FROM cards WHERE repo = ?1 AND state IN ('active') ORDER BY updated_at DESC"
        };
        let mut statement = self.0.prepare(sql).ok()?;
        let names: Vec<String> = statement
            .column_names()
            .into_iter()
            .map(str::to_owned)
            .collect();
        let mut rows = statement.query([repo]).ok()?;
        let mut cards = Vec::new();
        while let Some(row) = rows.next().ok()? {
            let mut card = BTreeMap::new();
            for (index, name) in names.iter().enumerate() {
                if name == "repo" {
                    continue;
                }
                let value = match row.get_ref(index).ok()? {
                    ValueRef::Null => Value::Null,
                    ValueRef::Integer(n) => json!(n),
                    ValueRef::Text(raw) => Value::String(std::str::from_utf8(raw).ok()?.to_owned()),
                    _ => return None, // Python owns blobs, floats and conversion errors.
                };
                card.insert(name.clone(), value);
            }
            for name in ["run_id", "runtime", "session_id"] {
                card.entry(name.into()).or_insert(json!(""));
            }
            cards.push(card);
        }
        Some(cards)
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn bundled_sqlite_includes_the_wal_reset_fix() {
        assert!(rusqlite::version_number() >= 3_051_003);
    }
}
