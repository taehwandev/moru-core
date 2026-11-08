use super::CardBootstrap;
use crate::cards_schema::CardSchema;
use rusqlite::{ffi, Connection};
use std::{
    ffi::CString,
    fs,
    os::unix::{ffi::OsStringExt, fs::symlink},
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

struct Database {
    root: PathBuf,
    path: PathBuf,
}
impl Database {
    fn new(schema: Option<&str>, version: Option<i64>) -> Self {
        static NEXT: AtomicU64 = AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "moru-card-bootstrap-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let root = root.canonicalize().unwrap();
        let path = root.join("cards.sqlite3");
        fs::write(&path, []).unwrap();
        if schema.is_some() || version.is_some() {
            let connection = Connection::open(&path).unwrap();
            if let Some(schema) = schema {
                connection.execute_batch(schema).unwrap();
            }
            if let Some(version) = version {
                connection
                    .pragma_update(None, "user_version", version)
                    .unwrap();
            }
        }
        Self { root, path }
    }
    fn connect(&self) -> Connection {
        Connection::open(&self.path).unwrap()
    }
}
impl Drop for Database {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}
fn legacy(mask: u8) -> String {
    let mut sql = CardSchema::SIGNATURE.to_owned();
    for (index, name) in ["run_id", "runtime", "session_id"].iter().enumerate() {
        if mask & (1 << index) == 0 {
            sql = sql.replace(&format!("    {name} TEXT NOT NULL DEFAULT '',\n"), "");
        }
    }
    sql
}
fn names(connection: &Connection) -> Vec<String> {
    let mut statement = connection.prepare("PRAGMA table_info(cards)").unwrap();
    let rows = statement.query_map([], |row| row.get(1)).unwrap();
    rows.collect::<Result<_, _>>().unwrap()
}
fn version(connection: &Connection) -> i64 {
    connection
        .query_row("PRAGMA user_version", [], |row| row.get(0))
        .unwrap()
}
fn mode(connection: &Connection) -> String {
    connection
        .query_row("PRAGMA journal_mode", [], |row| row.get(0))
        .unwrap()
}
fn schema(connection: &Connection) -> String {
    connection
        .query_row(
            "SELECT sql FROM sqlite_master WHERE name='cards'",
            [],
            |row| row.get(0),
        )
        .unwrap()
}
fn raw_execute(connection: &Connection, sql: &[u8]) {
    let sql = CString::new(sql).unwrap();
    let result = unsafe {
        ffi::sqlite3_exec(
            connection.handle(),
            sql.as_ptr(),
            None,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    assert_eq!(result, ffi::SQLITE_OK);
}

#[test]
fn all_bootstrap_masks_and_supported_versions_preserve_rows_and_sqlite_column_order() {
    for mask in 0..8 {
        for original in 0..=3 {
            let database = Database::new(Some(&legacy(mask)), Some(original));
            {
                let connection = database.connect();
                connection.execute_batch("INSERT INTO cards(repo,work_id,summary,command,project,state,created_at,updated_at)
                    VALUES ('repo','work','kept','command','project','active','created','updated')").unwrap();
                for (index, name) in ["run_id", "runtime", "session_id"].iter().enumerate() {
                    if mask & (1 << index) != 0 {
                        connection
                            .execute(
                                &format!("UPDATE cards SET {name}=?1"),
                                [format!("existing-{name}")],
                            )
                            .unwrap();
                    }
                }
            }
            let before = fs::read(&database.path).unwrap();
            let bootstrap = CardBootstrap::open(&database.path, false).unwrap();
            assert_eq!(
                fs::read(&database.path).unwrap(),
                before,
                "constructor mutated mask{mask}/v{original}"
            );
            assert_eq!(bootstrap.initialize().unwrap(), None);
            let connection = database.connect();
            let mut expected = [
                "repo",
                "work_id",
                "summary",
                "command",
                "project",
                "state",
                "created_at",
                "updated_at",
            ]
            .map(str::to_owned)
            .to_vec();
            for present in [true, false] {
                for (index, name) in ["run_id", "runtime", "session_id"].iter().enumerate() {
                    if (mask & (1 << index) != 0) == present {
                        expected.push((*name).to_owned());
                    }
                }
            }
            assert_eq!(names(&connection), expected, "mask{mask}/v{original}");
            assert_eq!(version(&connection), 3);
            assert_eq!(mode(&connection), "wal");
            assert_eq!(
                connection
                    .query_row("SELECT summary FROM cards", [], |row| row
                        .get::<_, String>(0))
                    .unwrap(),
                "kept"
            );
            let metadata: Vec<String> = connection
                .query_row("SELECT run_id,runtime,session_id FROM cards", [], |row| {
                    (0..3).map(|index| row.get(index)).collect()
                })
                .unwrap();
            for (index, name) in ["run_id", "runtime", "session_id"].iter().enumerate() {
                assert_eq!(
                    metadata[index],
                    if mask & (1 << index) != 0 {
                        format!("existing-{name}")
                    } else {
                        String::new()
                    }
                );
            }
        }
    }
}

#[test]
fn original_idle_parent_and_zero_length_store_are_initialized_without_reopening_admission_creation()
{
    let database = Database::new(None, None);
    let parent = database.connect();
    assert!(parent.is_autocommit());
    assert_eq!(fs::metadata(&database.path).unwrap().len(), 0);
    let bootstrap = CardBootstrap::open(&database.path, false).unwrap();
    assert_eq!(
        fs::metadata(&database.path).unwrap().len(),
        0,
        "read lookahead created a header"
    );
    assert!(bootstrap.0.is_autocommit());
    assert_eq!(bootstrap.initialize().unwrap(), None);
    assert_eq!(version(&parent), 3);
    assert_eq!(schema(&parent), CardSchema::SIGNATURE);
    assert_eq!(mode(&parent), "wal");
}

#[test]
fn unsupported_versions_change_wal_first_but_never_add_columns_or_change_version() {
    for original in [-1, 4, 99] {
        let database = Database::new(Some(&legacy(0)), Some(original));
        let before = schema(&database.connect());
        assert_eq!(mode(&database.connect()), "delete");
        assert_eq!(
            CardBootstrap::open(&database.path, false)
                .unwrap()
                .initialize()
                .unwrap(),
            Some(original)
        );
        let connection = database.connect();
        assert_eq!(mode(&connection), "wal");
        assert_eq!(version(&connection), original);
        assert_eq!(schema(&connection), before);
        assert_eq!(names(&connection).len(), 8);
    }
    let database = Database::new(None, Some(99));
    assert_eq!(
        CardBootstrap::open(&database.path, false)
            .unwrap()
            .initialize()
            .unwrap(),
        Some(99)
    );
    assert_eq!(
        database
            .connect()
            .query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='cards'",
                [],
                |row| row.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
}

#[test]
fn generated_runtime_failure_preserves_the_earlier_committed_run_id_alter() {
    let original = legacy(0).replace(
        "    PRIMARY KEY",
        "    runtime TEXT GENERATED ALWAYS AS (command) VIRTUAL,\n    PRIMARY KEY",
    );
    let database = Database::new(Some(&original), Some(1));
    database
        .connect()
        .execute_batch(
            "INSERT INTO cards(repo,work_id,summary,command,project,state,created_at,updated_at)
        VALUES ('r','w','kept','command','project','active','created','updated')",
        )
        .unwrap();
    assert!(!names(&database.connect())
        .iter()
        .any(|name| name == "runtime"));
    let error = CardBootstrap::open(&database.path, false)
        .unwrap()
        .initialize()
        .unwrap_err();
    assert!(
        error.to_string().contains("duplicate column name: runtime"),
        "{error}"
    );
    let connection = database.connect();
    assert_eq!(version(&connection), 1);
    assert_eq!(mode(&connection), "wal");
    let columns = names(&connection);
    assert!(columns.iter().any(|name| name == "run_id"));
    assert!(!columns.iter().any(|name| name == "session_id"));
    assert_eq!(
        connection
            .query_row("SELECT summary,run_id,runtime FROM cards", [], |row| Ok((
                row.get::<_, String>(0)?,
                row.get::<_, String>(1)?,
                row.get::<_, String>(2)?
            )))
            .unwrap(),
        ("kept".to_owned(), String::new(), "command".to_owned())
    );
}

#[test]
fn view_failure_is_an_error_after_wal_without_a_hidden_transaction_or_version_upgrade() {
    let database = Database::new(Some("CREATE VIEW cards AS SELECT 1 AS work_id"), Some(2));
    let before = schema(&database.connect());
    let bootstrap = CardBootstrap::open(&database.path, false).unwrap();
    assert!(bootstrap.0.is_autocommit());
    assert!(bootstrap.initialize().is_err());
    let connection = database.connect();
    assert_eq!(mode(&connection), "wal");
    assert_eq!(version(&connection), 2);
    assert_eq!(schema(&connection), before);
}

#[test]
fn malformed_utf8_names_types_and_defaults_decline_before_wal_even_for_future_version() {
    for raw in [
        b"CREATE TABLE cards(\"bad\xff\" TEXT)".as_slice(),
        b"CREATE TABLE cards(name \"bad\xff\")",
        b"CREATE TABLE cards(name TEXT DEFAULT 'bad\xff')",
    ] {
        let database = Database::new(None, Some(99));
        raw_execute(&database.connect(), raw);
        let before = fs::read(&database.path).unwrap();
        assert!(CardBootstrap::open(&database.path, false).is_none());
        assert_eq!(before, fs::read(&database.path).unwrap());
        assert_eq!(mode(&database.connect()), "delete");
        assert_eq!(version(&database.connect()), 99);
    }
}

#[test]
fn admission_never_creates_missing_paths_and_preserves_path_guards() {
    let database = Database::new(None, None);
    let missing = database.root.join("missing.sqlite3");
    assert!(CardBootstrap::open(&missing, false).is_none());
    assert!(!missing.exists());
    let missing_parent = database.root.join("absent/cards.sqlite3");
    assert!(CardBootstrap::open(&missing_parent, false).is_none());
    assert!(!missing_parent.parent().unwrap().exists());
    let alias = database.root.join("alias");
    symlink(&database.root, &alias).unwrap();
    assert!(CardBootstrap::open(&alias.join("cards.sqlite3"), false).is_none());
    let sidecar = database.root.join("cards.sqlite3-wal");
    symlink(&database.path, &sidecar).unwrap();
    assert!(CardBootstrap::open(&database.path, false).is_none());
    fs::remove_file(sidecar).unwrap();
    let invalid = database
        .root
        .join(std::ffi::OsString::from_vec(b"bad\xff.sqlite3".to_vec()));
    match fs::write(&invalid, []) {
        Ok(()) => {
            assert!(CardBootstrap::open(&invalid, false).is_none());
            assert_eq!(fs::metadata(&invalid).unwrap().len(), 0);
        }
        Err(error) if cfg!(target_os = "macos") && error.raw_os_error() == Some(libc::EPERM) => {
            assert!(!invalid.exists());
            assert!(CardBootstrap::open(&invalid, false).is_none());
            assert!(!invalid.exists(), "admission created the rejected filename");
        }
        Err(error) => panic!("unexpected invalid-UTF8 fixture creation error: {error}"),
    }
    assert_eq!(fs::metadata(&database.path).unwrap().len(), 0);
}

#[test]
fn admitted_connection_uses_parent_fk_mode_two_second_busy_bound_and_autocommit() {
    for enabled in [false, true] {
        let database = Database::new(Some(CardSchema::SIGNATURE), Some(2));
        let before = fs::read(&database.path).unwrap();
        let bootstrap = CardBootstrap::open(&database.path, enabled).unwrap();
        assert_eq!(
            bootstrap
                .0
                .query_row("PRAGMA foreign_keys", [], |row| row.get::<_, bool>(0))
                .unwrap(),
            enabled
        );
        assert_eq!(
            bootstrap
                .0
                .query_row("PRAGMA busy_timeout", [], |row| row.get::<_, i64>(0))
                .unwrap(),
            2000
        );
        assert!(bootstrap.0.is_autocommit());
        assert_eq!(mode(&bootstrap.0), "delete");
        assert_eq!(version(&bootstrap.0), 2);
        drop(bootstrap);
        assert_eq!(before, fs::read(&database.path).unwrap());
    }
}
