use super::{CardTransaction, SCHEMA};
use rusqlite::{Connection, OpenFlags};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

fn unique() -> String {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    format!(
        "moru-card-transaction-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, Ordering::Relaxed)
    )
}
fn memory() -> (Connection, Connection) {
    let uri = format!("file:{}?mode=memory&cache=shared", unique());
    let flags = OpenFlags::SQLITE_OPEN_READ_WRITE
        | OpenFlags::SQLITE_OPEN_CREATE
        | OpenFlags::SQLITE_OPEN_URI;
    let writer = Connection::open_with_flags(&uri, flags).unwrap();
    writer.execute_batch(SCHEMA).unwrap();
    let observer = Connection::open_with_flags(&uri, flags).unwrap();
    (writer, observer)
}
struct Database(PathBuf);
impl Database {
    fn new(schema: &str) -> Self {
        let root = std::env::temp_dir().join(unique());
        fs::create_dir(&root).unwrap();
        let path = root.canonicalize().unwrap().join("cards.sqlite3");
        let connection = Connection::open(&path).unwrap();
        connection.execute_batch("PRAGMA journal_mode=WAL").unwrap();
        connection.execute_batch(schema).unwrap();
        connection.execute_batch("PRAGMA user_version=3").unwrap();
        Self(path)
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(self.0.parent().unwrap());
    }
}
fn values() -> [String; 10] {
    [
        "repo",
        "work",
        "new-summary",
        "feature",
        "synthetic-project",
        "new-created",
        "2026-03-01",
        "run",
        "codex",
        "session",
    ]
    .map(str::to_owned)
}
fn seed(connection: &Connection, repo: &str, work: &str, state: &str, stamp: &str) {
    connection
        .execute(
            "INSERT INTO cards(repo,work_id,summary,command,project,state,created_at,updated_at)
        VALUES (?1,?2,'old-summary','old-command','old-project',?3,'original-created',?4)",
            [repo, work, state, stamp],
        )
        .unwrap();
}
fn row(connection: &Connection, repo: &str, work: &str) -> Vec<String> {
    connection
        .query_row(
            "SELECT summary,command,project,state,created_at,updated_at,run_id,runtime,session_id
        FROM cards WHERE repo=?1 AND work_id=?2",
            [repo, work],
            |row| (0..9).map(|index| row.get(index)).collect(),
        )
        .unwrap()
}

#[test]
fn actual_sqlite_alter_layouts_are_prepared_and_old_cli_eligibility_is_unchanged() {
    for mask in 0..8 {
        let connection = Connection::open_in_memory().unwrap();
        let mut legacy = SCHEMA.to_owned();
        for (index, name) in ["run_id", "runtime", "session_id"].iter().enumerate() {
            if mask & (1 << index) == 0 {
                legacy = legacy.replace(&format!("    {name} TEXT NOT NULL DEFAULT '',\n"), "");
            }
        }
        connection.execute_batch(&legacy).unwrap();
        for (index, name) in ["run_id", "runtime", "session_id"].iter().enumerate() {
            if mask & (1 << index) == 0 {
                connection
                    .execute_batch(&format!(
                        "ALTER TABLE cards ADD COLUMN {name} TEXT NOT NULL DEFAULT ''"
                    ))
                    .unwrap();
            }
        }
        let sql: String = connection
            .query_row(
                "SELECT sql FROM sqlite_master WHERE name='cards'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert!(CardTransaction::prepared_schema(&sql), "mask {mask}: {sql}");
        let database = Database::new(&sql);
        assert!(
            CardTransaction::prepared(&database.0, false).is_some(),
            "prepared mask {mask}"
        );
        assert_eq!(
            CardTransaction::open(&database.0).is_some(),
            sql.split_whitespace().eq(SCHEMA.split_whitespace()),
            "CLI mask {mask}"
        );
        let after: String = Connection::open(&database.0)
            .unwrap()
            .query_row(
                "SELECT sql FROM sqlite_master WHERE name='cards'",
                [],
                |row| row.get(0),
            )
            .unwrap();
        assert_eq!(sql, after, "admission must not migrate the schema");
    }
}

#[test]
fn schema_tokens_keep_identifier_boundaries_and_quoted_literal_bytes() {
    assert!(CardTransaction::prepared_schema(&SCHEMA.replace(
        "PRIMARY KEY (repo, work_id)",
        "PRIMARY\tKEY(repo,work_id)"
    )));
    for sql in [
        SCHEMA.replace("TEXT NOT NULL", "TEXT NOTNULL"),
        SCHEMA.replace("DEFAULT ''", "DEFAULT ' '"),
        SCHEMA.replace("'active'", "'act ive'"),
        SCHEMA.replace("summary TEXT NOT NULL,", "summary TEXT NOT NULL UNIQUE,"),
        SCHEMA.replace("DEFAULT ''", "DEFAULT 'other'"),
        SCHEMA.replace("run_id TEXT", "other_id TEXT"),
    ] {
        assert!(!CardTransaction::prepared_schema(&sql), "{sql}");
    }
    assert!(CardTransaction::tokens("DEFAULT 'unfinished").is_none());
}

#[test]
fn unknown_schema_indexes_and_triggers_are_refused_before_writes() {
    for schema in [
        SCHEMA.replace("DEFAULT ''", "DEFAULT 'other'"),
        SCHEMA.replace(
            "summary TEXT NOT NULL,",
            "summary TEXT NOT NULL CHECK(length(summary)>0),",
        ),
    ] {
        let database = Database::new(&schema);
        assert!(CardTransaction::open(&database.0).is_none());
        assert!(CardTransaction::prepared(&database.0, false).is_none());
    }
    for extra in ["CREATE INDEX extra_index ON cards(summary)",
        "CREATE TABLE other(x); CREATE TRIGGER extra_trigger AFTER INSERT ON other BEGIN SELECT 1; END"] {
        let database = Database::new(SCHEMA);
        Connection::open(&database.0).unwrap().execute_batch(extra).unwrap();
        assert!(CardTransaction::open(&database.0).is_none());
        assert!(CardTransaction::prepared(&database.0, false).is_none());
    }
}

#[test]
fn version_wal_busy_and_missing_path_guards_are_retained() {
    let database = Database::new(SCHEMA);
    let connection = Connection::open(&database.0).unwrap();
    connection.execute_batch("PRAGMA user_version=2").unwrap();
    assert!(CardTransaction::prepared(&database.0, false).is_none());
    assert!(CardTransaction::open(&database.0).is_none());
    connection
        .execute_batch("PRAGMA user_version=3; BEGIN IMMEDIATE")
        .unwrap();
    assert!(CardTransaction::prepared(&database.0, false).is_none());
    assert!(CardTransaction::open(&database.0).is_none());
    assert!(!connection.is_autocommit());
    connection
        .execute_batch("ROLLBACK; PRAGMA journal_mode=DELETE")
        .unwrap();
    assert!(CardTransaction::prepared(&database.0, false).is_none());
    assert!(CardTransaction::open(&database.0).is_none());
    let missing = database.0.with_file_name("missing.sqlite3");
    assert!(CardTransaction::prepared(&missing, false).is_none());
    assert!(!missing.exists());
}

#[test]
fn upsert_reactivates_preserves_created_at_and_prunes_every_repo_and_state() {
    let (writer, observer) = memory();
    seed(&writer, "repo", "work", "done", "2026-01-01");
    for state in ["active", "done", "cancelled"] {
        seed(&writer, "other", state, state, "2026-01-01");
    }
    seed(&writer, "other", "equal", "cancelled", "2026-02-01");
    writer.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(CardTransaction(writer)
        .upsert(&values(), "2026-02-01")
        .unwrap());
    assert_eq!(
        row(&observer, "repo", "work"),
        [
            "new-summary",
            "feature",
            "synthetic-project",
            "active",
            "original-created",
            "2026-03-01",
            "run",
            "codex",
            "session"
        ]
    );
    assert_eq!(
        observer
            .query_row("SELECT COUNT(*) FROM cards", [], |row| row.get::<_, i64>(0))
            .unwrap(),
        2
    );
    assert_eq!(row(&observer, "other", "equal")[3], "cancelled");
}

#[test]
fn upsert_new_card_uses_the_supplied_created_timestamp() {
    let (writer, observer) = memory();
    writer.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(CardTransaction(writer)
        .upsert(&values(), "2026-02-01")
        .unwrap());
    assert_eq!(row(&observer, "repo", "work")[4], "new-created");
}

#[test]
fn failed_retention_delete_rolls_back_the_preceding_upsert() {
    let (writer, observer) = memory();
    seed(&writer, "repo", "work", "done", "2026-01-01");
    seed(&writer, "other", "stale", "active", "2026-01-01");
    writer.execute_batch("CREATE TRIGGER refuse_delete BEFORE DELETE ON cards BEGIN SELECT RAISE(ABORT,'delete refused'); END;
        BEGIN IMMEDIATE").unwrap();
    let error = CardTransaction(writer)
        .upsert(&values(), "2026-02-01")
        .unwrap_err();
    assert_eq!(CardTransaction::message(error), "delete refused");
    assert_eq!(row(&observer, "repo", "work")[0], "old-summary");
    assert_eq!(row(&observer, "repo", "work")[3], "done");
    assert_eq!(row(&observer, "other", "stale")[3], "active");
}

#[test]
fn failed_commit_rolls_back_both_upsert_and_retention_delete() {
    let (writer, observer) = memory();
    seed(&writer, "repo", "work", "done", "2026-01-01");
    seed(&writer, "other", "stale", "active", "2026-01-01");
    writer
        .execute_batch(
            "CREATE TABLE parent(id INTEGER PRIMARY KEY);
        CREATE TABLE pending(id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED);
        PRAGMA foreign_keys=ON; BEGIN IMMEDIATE; INSERT INTO pending VALUES(99)",
        )
        .unwrap();
    let error = CardTransaction(writer)
        .upsert(&values(), "2026-02-01")
        .unwrap_err();
    assert_eq!(
        CardTransaction::message(error),
        "FOREIGN KEY constraint failed"
    );
    assert_eq!(row(&observer, "repo", "work")[0], "old-summary");
    assert_eq!(row(&observer, "other", "stale")[3], "active");
    assert_eq!(
        observer
            .query_row("SELECT COUNT(*) FROM pending", [], |row| row
                .get::<_, i64>(0))
            .unwrap(),
        0
    );
}

#[test]
fn failed_settlement_update_rolls_back_and_success_only_changes_an_active_match() {
    let (writer, observer) = memory();
    seed(&writer, "repo", "work", "active", "2026-01-01");
    writer.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(CardTransaction(writer)
        .settle("repo", "work", "invalid", "2026-03-01")
        .is_err());
    assert_eq!(row(&observer, "repo", "work")[3], "active");
    assert_eq!(row(&observer, "repo", "work")[5], "2026-01-01");
    observer.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(CardTransaction(observer)
        .settle("repo", "work", "done", "2026-03-01")
        .unwrap());
    let (writer, observer) = memory();
    seed(&writer, "repo", "work", "done", "2026-01-01");
    writer.execute_batch("BEGIN IMMEDIATE").unwrap();
    assert!(!CardTransaction(writer)
        .settle("repo", "work", "cancelled", "2026-03-01")
        .unwrap());
    assert_eq!(row(&observer, "repo", "work")[3], "done");
    assert_eq!(row(&observer, "repo", "work")[5], "2026-01-01");
}

#[test]
fn prepared_retention_matches_the_parent_foreign_key_enforcement_flag() {
    for enabled in [false, true] {
        let database = Database::new(SCHEMA);
        let observer = Connection::open(&database.0).unwrap();
        seed(&observer, "repo", "work", "done", "2026-01-01");
        seed(&observer, "repo", "stale", "active", "2026-01-01");
        observer
            .execute_batch(
                "CREATE TABLE dependent(repo,work_id,payload,
            FOREIGN KEY(repo,work_id) REFERENCES CaRdS(repo,work_id) ON DELETE CASCADE);
            INSERT INTO dependent VALUES ('repo','stale','preserved child')",
            )
            .unwrap();
        assert!(CardTransaction::open(&database.0).is_none());
        let transaction = CardTransaction::prepared(&database.0, enabled).unwrap();
        assert_eq!(
            transaction
                .0
                .query_row("PRAGMA foreign_keys", [], |row| row.get::<_, bool>(0))
                .unwrap(),
            enabled
        );
        assert!(transaction.upsert(&values(), "2026-02-01").unwrap());
        assert_eq!(
            observer
                .query_row("SELECT COUNT(*) FROM dependent", [], |row| row
                    .get::<_, i64>(0))
                .unwrap(),
            if enabled { 0 } else { 1 }
        );
        if !enabled {
            assert_eq!(
                observer
                    .query_row("SELECT payload FROM dependent", [], |row| row
                        .get::<_, String>(0))
                    .unwrap(),
                "preserved child"
            );
        }
        assert_eq!(
            observer
                .query_row(
                    "SELECT COUNT(*) FROM cards WHERE work_id='stale'",
                    [],
                    |row| row.get::<_, i64>(0)
                )
                .unwrap(),
            0
        );
        assert_eq!(row(&observer, "repo", "work")[0], "new-summary");
    }
}

#[test]
fn prepared_restrict_failure_rolls_back_the_upsert_and_preserves_dependents() {
    let database = Database::new(SCHEMA);
    let observer = Connection::open(&database.0).unwrap();
    seed(&observer, "repo", "work", "done", "2026-01-01");
    seed(&observer, "repo", "stale", "active", "2026-01-01");
    observer
        .execute_batch(
            "CREATE TABLE dependent(repo,work_id,
        FOREIGN KEY(repo,work_id) REFERENCES cards(repo,work_id) ON DELETE RESTRICT);
        INSERT INTO dependent VALUES ('repo','stale')",
        )
        .unwrap();
    let error = CardTransaction::prepared(&database.0, true)
        .unwrap()
        .upsert(&values(), "2026-02-01")
        .unwrap_err();
    assert_eq!(
        CardTransaction::message(error),
        "FOREIGN KEY constraint failed"
    );
    assert_eq!(row(&observer, "repo", "work")[0], "old-summary");
    assert_eq!(row(&observer, "repo", "work")[3], "done");
    assert_eq!(row(&observer, "repo", "stale")[3], "active");
    assert_eq!(
        observer
            .query_row("SELECT COUNT(*) FROM dependent", [], |row| row
                .get::<_, i64>(0))
            .unwrap(),
        1
    );
}

#[test]
fn cli_declines_incoming_keys_with_quoted_names_but_keeps_unrelated_tables() {
    let database = Database::new(SCHEMA);
    let observer = Connection::open(&database.0).unwrap();
    observer
        .execute_batch("CREATE TABLE unrelated(payload TEXT)")
        .unwrap();
    assert_eq!(
        CardTransaction::incoming_foreign_keys(&observer),
        Some(false)
    );
    assert!(CardTransaction::open(&database.0).is_some());
    observer
        .execute_batch(
            "CREATE TABLE \"odd'child\"(repo,work_id,
        FOREIGN KEY(repo,work_id) REFERENCES \"CARDS\"(repo,work_id) ON DELETE CASCADE)",
        )
        .unwrap();
    assert_eq!(
        CardTransaction::incoming_foreign_keys(&observer),
        Some(true)
    );
    assert!(CardTransaction::open(&database.0).is_none());
    assert!(CardTransaction::prepared(&database.0, false).is_some());
    assert!(CardTransaction::prepared(&database.0, true).is_some());
}
