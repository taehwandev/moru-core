//! owner: CardSchema; allowed imports: std; forbidden imports: I/O and SQL execution;
//! callers/tests: card bootstrap and transaction eligibility; verification: schema parity.
pub(crate) struct CardSchema;

impl CardSchema {
    pub(crate) const SIGNATURE: &'static str = "CREATE TABLE cards (
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

    pub(crate) fn create() -> String {
        Self::SIGNATURE.replacen("CREATE TABLE cards", "CREATE TABLE IF NOT EXISTS cards", 1)
    }
}
