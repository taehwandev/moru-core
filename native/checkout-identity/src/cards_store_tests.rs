use super::CardStore;
use rusqlite::{params, types::ValueRef, Connection};
use serde_json::{json, Value};
use std::collections::BTreeMap;

fn store(schema: &str) -> CardStore {
    let db = Connection::open_in_memory().unwrap();
    db.execute_batch(schema).unwrap();
    CardStore(db)
}

fn names(card: &Value) -> Vec<&str> {
    card.as_array()
        .unwrap()
        .iter()
        .map(|pair| pair[0].as_str().unwrap())
        .collect()
}

#[test]
fn snapshot_keeps_sqlite_types_original_column_order_and_existing_defaults() {
    let store = store(
        "CREATE TABLE cards(repo,state,updated_at,nullable,number,real_value,label,bytes,run_id)",
    );
    store
        .0
        .execute(
            "INSERT INTO cards VALUES (?1,'active','now',NULL,?2,?3,?4,?5,NULL)",
            params![
                "repository",
                i64::MIN,
                1.25,
                "한😀",
                &[0u8, 15, 16, 255][..]
            ],
        )
        .unwrap();
    let value = store.snapshot("repository", false).unwrap();
    assert_eq!(
        names(&value[0]),
        vec![
            "state",
            "updated_at",
            "nullable",
            "number",
            "real_value",
            "label",
            "bytes",
            "run_id",
            "runtime",
            "session_id"
        ]
    );
    assert_eq!(
        value,
        json!([[
            ["state", ["text", "active"]],
            ["updated_at", ["text", "now"]],
            ["nullable", ["null"]],
            ["number", ["integer", i64::MIN]],
            ["real_value", ["real", "1.25"]],
            ["label", ["text", "한😀"]],
            ["bytes", ["blob", "000f10ff"]],
            ["run_id", ["null"]],
            ["runtime", ["text", ""]],
            ["session_id", ["text", ""]]
        ]])
    );
    assert!(
        store.list("repository", false).is_none(),
        "CLI must still defer real/blob rows"
    );
}

#[test]
fn snapshot_legacy_defaults_append_only_absent_fields_in_contract_order() {
    let store = store(
        "CREATE TABLE cards(runtime,repo,state,updated_at,session_id);
        INSERT INTO cards VALUES ('existing','r','active','now',NULL)",
    );
    let value = store.snapshot("r", true).unwrap();
    assert_eq!(
        names(&value[0]),
        vec!["runtime", "state", "updated_at", "session_id", "run_id"]
    );
    assert_eq!(value[0][0], json!(["runtime", ["text", "existing"]]));
    assert_eq!(value[0][3], json!(["session_id", ["null"]]));
    assert_eq!(value[0][4], json!(["run_id", ["text", ""]]));
}

#[test]
fn snapshot_preserves_repository_state_filter_and_descending_sql_order() {
    let store = store(
        "CREATE TABLE cards(repo,title,state,updated_at);
        INSERT INTO cards VALUES ('r','first','active','2'),('r','done','done','3'),
          ('r','second','active','2'),('r','cancelled','cancelled','1'),
          ('other','foreign','active','9'),('r','unknown','unknown','9')",
    );
    let titles = |all| {
        store
            .snapshot("r", all)
            .unwrap()
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row[0][1][1].as_str().unwrap().to_owned())
            .collect::<Vec<_>>()
    };
    assert_eq!(titles(false), vec!["first", "second"]);
    assert_eq!(titles(true), vec!["done", "first", "second", "cancelled"]);
    assert_eq!(store.snapshot("missing", true), Some(json!([])));
}

#[test]
fn cell_tags_cover_infinities_signed_zero_empty_blob_and_invalid_utf8() {
    for (number, expected) in [
        (f64::INFINITY, "inf"),
        (f64::NEG_INFINITY, "-inf"),
        (-0.0, "-0.0"),
        (0.0, "0.0"),
    ] {
        assert_eq!(
            CardStore::cell(ValueRef::Real(number)),
            Some(json!(["real", expected]))
        );
    }
    assert_eq!(
        CardStore::cell(ValueRef::Integer(i64::MAX)),
        Some(json!(["integer", i64::MAX]))
    );
    assert_eq!(
        CardStore::cell(ValueRef::Blob(&[])),
        Some(json!(["blob", ""]))
    );
    assert!(CardStore::cell(ValueRef::Text(&[0xff])).is_none());
}

#[test]
fn sqlite_text_conversion_and_query_errors_decline_the_whole_snapshot() {
    let store = store(
        "CREATE TABLE cards(repo,state,updated_at,label);
        INSERT INTO cards VALUES ('r','active','2','valid'),('r','active','1',CAST(x'80' AS TEXT))",
    );
    assert!(store.snapshot("r", false).is_none());
    store.0.execute_batch("DROP TABLE cards").unwrap();
    assert!(store.snapshot("r", false).is_none());
}

#[test]
fn generated_columns_keep_their_select_star_position_and_values() {
    let store = store(
        "CREATE TABLE cards(repo,title,state,generated AS (title || '!'),updated_at);
        INSERT INTO cards(repo,title,state,updated_at) VALUES ('r','name','active','now')",
    );
    let value = store.snapshot("r", false).unwrap();
    assert_eq!(
        names(&value[0]),
        vec![
            "title",
            "state",
            "generated",
            "updated_at",
            "run_id",
            "runtime",
            "session_id"
        ]
    );
    assert_eq!(value[0][2], json!(["generated", ["text", "name!"]]));
}

#[test]
fn invalid_utf8_schema_column_names_decline_without_panicking_even_when_empty() {
    let db = Connection::open_in_memory().unwrap();
    let mut sql = b"CREATE TABLE cards(repo,state,updated_at,\"".to_vec();
    sql.extend([0xff]);
    sql.extend(b"\")");
    let sql = std::ffi::CString::new(sql).unwrap();
    // Test-only raw SQLite input permits a column name Rust strings cannot represent.
    let result = unsafe {
        rusqlite::ffi::sqlite3_exec(
            db.handle(),
            sql.as_ptr(),
            None,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    assert_eq!(result, rusqlite::ffi::SQLITE_OK);
    db.execute(
        "INSERT INTO cards(repo,state,updated_at) VALUES ('r','active','now')",
        [],
    )
    .unwrap();
    let store = CardStore(db);
    assert!(store.snapshot("r", false).is_none());
    assert!(store.snapshot("empty", false).is_none());
}

#[test]
fn snapshots_and_cli_lists_match_without_changing_a_query_only_store() {
    let store = store(
        "CREATE TABLE cards(repo,title,state,updated_at,run_id);
        INSERT INTO cards VALUES ('r','one','active','1',NULL),('r','two','done','2','run');
        PRAGMA query_only = ON",
    );
    let before = store.0.total_changes();
    for all in [false, true] {
        let cards = store.snapshot("r", all).unwrap();
        let decoded = cards
            .as_array()
            .unwrap()
            .iter()
            .map(|card| {
                card.as_array()
                    .unwrap()
                    .iter()
                    .map(|pair| {
                        let cell = pair[1].as_array().unwrap();
                        let value = if cell[0] == "null" {
                            Value::Null
                        } else {
                            cell[1].clone()
                        };
                        (pair[0].as_str().unwrap().to_owned(), value)
                    })
                    .collect::<BTreeMap<_, _>>()
            })
            .collect::<Vec<_>>();
        assert_eq!(decoded, store.list("r", all).unwrap());
    }
    assert_eq!(before, store.0.total_changes());
    assert_eq!(
        store
            .0
            .query_row("PRAGMA query_only", [], |row| row.get::<_, i64>(0))
            .unwrap(),
        1
    );
}
