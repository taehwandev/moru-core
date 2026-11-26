//! Owner: the Codex thread metadata projection for status trends.
//! Allowed imports: rusqlite, serde_json, std collections and the shared response budget.
//! Forbidden imports: database writes, opening databases and external providers.
//! Callers/tests: status_trend_sqlite and the observability SQLite parity fixture.
use rusqlite::Connection;
use serde_json::{json, Value};
use std::collections::HashSet;

pub(super) fn read(connection: &Connection, wanted: &HashSet<&str>) -> Option<Value> {
    let mut statement = connection
        .prepare("SELECT id, COALESCE(model, ''), COALESCE(reasoning_effort, '') FROM threads")
        .ok()?;
    let mut rows = statement.query([]).ok()?;
    let mut selected = Vec::new();
    let mut budget = 0;
    while let Some(row) = rows.next().ok()? {
        let id = super::text(row.get_ref(0).ok()?)?;
        // The reference decodes every fetched row before discarding unused IDs.
        let model = super::text(row.get_ref(1).ok()?)?;
        let effort = super::text(row.get_ref(2).ok()?)?;
        if !id.is_empty() && wanted.contains(id) {
            super::push_row(&mut selected, &mut budget, json!([id, model, effort]))?;
        }
    }
    Some(json!({ "rows": selected }))
}
