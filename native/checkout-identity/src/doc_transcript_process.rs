//! owner: DocTranscriptProcess; allowed imports: source guard, file-scan owner,
//! std/JSON; forbidden imports: writes, providers, marker/evidence authority;
//! callers/tests: private native probe; actual file/source and transported tests.
use crate::{doc_transcript::DocTranscript, pretool_guard::CallbackGuard};
use serde_json::{json, Value};
use std::{
    ffi::OsString,
    io::{Read, Write},
    path::Path,
};

pub(crate) struct DocTranscriptProcess;
impl DocTranscriptProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2
            || !matches!(args[1].to_str(), Some("compacted" | "aligned" | "due"))
            || CallbackGuard::root(launcher, "doc-transcript-probe").is_none()
        {
            return 125;
        }
        let mut bytes = Vec::new();
        if std::io::stdin()
            .take(1024 * 1024 + 1)
            .read_to_end(&mut bytes)
            .is_err()
            || bytes.len() > 1024 * 1024
        {
            return 125;
        }
        let result = serde_json::from_slice::<Value>(&bytes)
            .ok()
            .and_then(|payload| {
                let object = payload.as_object()?;
                let path = Path::new(object.get("path")?.as_str()?);
                match args[1].to_str()? {
                    "compacted" if object.len() == 1 => {
                        DocTranscript::compacted(path).map(|v| json!(v))
                    }
                    "aligned" if object.len() == 2 => {
                        DocTranscript::aligned(path, object.get("fallback")?.as_i64()?)
                            .map(|v| json!(v))
                    }
                    "due" if object.len() == 4 => DocTranscript::due(
                        path,
                        object.get("offset")?.as_i64()?,
                        object.get("redeliveries")?.as_i64()?,
                        object.get("limit")?.as_i64()?,
                    )
                    .map(|v| json!(v)),
                    _ => None,
                }
            });
        let Some(value) = result else {
            return 125;
        };
        let Ok(mut out) = serde_json::to_vec(&json!({"schema_version":1,"result":{"value":value}}))
        else {
            return 125;
        };
        out.push(b'\n');
        if std::io::stdout().write_all(&out).is_ok() {
            0
        } else {
            1
        }
    }
}
