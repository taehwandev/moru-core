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

#[path = "agy_doc_redelivery.rs"]
mod agy_doc_redelivery;
#[path = "agy_doc_request.rs"]
mod agy_doc_request;
#[path = "doc_delivery_marker.rs"]
mod delivery_marker;
#[path = "doc_delivery_text.rs"]
mod delivery_text;

pub(crate) struct DocTranscriptProcess;
impl DocTranscriptProcess {
    pub(crate) fn run(launcher: &OsString, args: &[OsString]) -> i32 {
        if args.len() != 2
            || !matches!(
                args[1].to_str(),
                Some(
                    "compacted"
                        | "aligned"
                        | "due"
                        | "agy-covered"
                        | "render"
                        | "read-docs"
                        | "read-delivery-manifest"
                        | "nearest-registry-project"
                        | "agy-delivery-request"
                        | "agy-redelivery"
                        | "delivery-plan"
                        | "write-marker"
                )
            )
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
                if args[1] == "agy-delivery-request" {
                    return agy_doc_request::decode(object);
                }
                if args[1] == "agy-redelivery" && object.len() == 6 {
                    return agy_doc_redelivery::deliver(&payload);
                }
                if args[1] == "write-marker" && object.len() == 5 {
                    return delivery_marker::write(&payload);
                }
                if args[1] == "render" {
                    return delivery_text::DocDeliveryText::render(&payload)
                        .map(|value| json!(value));
                }
                if args[1] == "read-docs" && object.len() == 2 {
                    let rules = Path::new(object.get("rules")?.as_str()?);
                    let docs = object
                        .get("docs")?
                        .as_array()?
                        .iter()
                        .map(Value::as_str)
                        .collect::<Option<Vec<_>>>()?;
                    return DocTranscript::read_documents(rules, &docs);
                }
                let path = Path::new(object.get("path")?.as_str()?);
                match args[1].to_str()? {
                    "nearest-registry-project" if object.len() == 1 => {
                        DocTranscript::nearest_registry_project(path)
                    }
                    "read-delivery-manifest" if object.len() == 1 => {
                        DocTranscript::read_delivery_manifest(path)
                    }
                    "delivery-plan" if object.len() == 3 => DocTranscript::delivery_plan(
                        Path::new(object.get("marker")?.as_str()?),
                        path,
                        object.get("limit")?.as_i64()?,
                    ),
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
                    "agy-covered" if object.len() == 3 => {
                        let rules = Path::new(object.get("rules")?.as_str()?);
                        let docs = object
                            .get("docs")?
                            .as_array()?
                            .iter()
                            .map(Value::as_str)
                            .collect::<Option<Vec<_>>>()?;
                        DocTranscript::agy_covered(path, rules, &docs).map(|v| json!(v))
                    }
                    _ => None,
                }
            });
        let Some(value) = result else {
            return 125;
        };
        let Ok(mut out) = serde_json::to_vec(&json!({"schema_version":1,"result":{"value":value}}))
        else {
            return match args[1].to_str() {
                Some("write-marker" | "agy-redelivery") => 1,
                _ => 125,
            };
        };
        if args[1] == "read-docs" && out.len() >= 1024 * 1024 {
            return 125;
        }
        out.push(b'\n');
        if std::io::stdout().write_all(&out).is_ok() {
            0
        } else {
            1
        }
    }
}
