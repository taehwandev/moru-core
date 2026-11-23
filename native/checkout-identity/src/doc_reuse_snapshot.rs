//! owner: required and project-route document snapshot schema;
//! allowed imports: JSON; forbidden imports: filesystem I/O, session and proof policy;
//! callers/tests: current input and prior snapshot matching conformance;
//! verification: ordered raw records with exact hash and integer size validation.
use serde_json::Value;

pub(super) struct ReuseSnapshot<'a>(&'a [Value]);

impl<'a> ReuseSnapshot<'a> {
    pub(super) fn from_preflight(preflight: &'a Value, project_docs: bool) -> Option<Self> {
        let records = if project_docs {
            preflight.get("project_route_docs")
        } else {
            match preflight.get("execution_snapshot") {
                Some(Value::Object(snapshot)) => snapshot.get("required_docs"),
                None | Some(Value::Null) => None,
                _ => return None,
            }
        };
        match records {
            None | Some(Value::Null) => Some(Self(&[])),
            Some(value) => Some(Self(value.as_array()?.as_slice())),
        }
    }

    pub(super) fn records(&self) -> impl Iterator<Item = Option<(&'a str, &'a str, u64)>> {
        self.0.iter().map(|record| {
            let path = record.get("path")?.as_str()?;
            let hash = record.get("sha256")?.as_str()?;
            let size = record.get("size_bytes")?.as_u64()?;
            (hash.len() == 64
                && hash
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)))
            .then_some((path, hash, size))
        })
    }
}
