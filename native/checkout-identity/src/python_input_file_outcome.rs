//! owner: FileRead; allowed imports: standard owned byte/text containers;
//! forbidden imports: IO, process, validation; callers/tests: PythonInputFile and JSON CLIs;
//! verification: file diagnostic and successful validation process parity.
pub(crate) enum FileRead {
    Bytes(Vec<u8>),
    Error(String),
    TooLarge,
}
