//! owner: FileRead; allowed imports: standard owned byte/text containers;
//! forbidden imports: IO, process, validation; callers/tests: FigmaFile and FigmaProcess;
//! verification: file diagnostic and successful validation process parity.
pub(in super::super) enum FileRead {
    Bytes(Vec<u8>),
    Error(String),
}
