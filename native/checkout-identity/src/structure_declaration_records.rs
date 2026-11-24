//! owner: final role, visibility and ownership rows from native declaration headers.
//! allowed imports: structural scanners, role rules, Python-compatible text and JSON.
//! forbidden imports: filesystem, Git execution and approval decisions.
//! callers/tests: structural review via the private completion probe and reference parity fixtures.
//! verification: language-specific owner filtering, modifier words and fallback.
use super::{
    structure_brace_declarations::StructureBraceDeclarations,
    structure_declaration_roles::StructureDeclarationRoles,
    structure_go_declarations::StructureGoDeclarations,
    structure_js_declarations::StructureJsDeclarations,
    structure_kotlin_declarations::StructureKotlinDeclarations,
    structure_python_blocks::StructurePythonBlocks,
    structure_rust_declarations::StructureRustDeclarations, structure_ts_text::StructureTsText,
};
use crate::{python_text::PythonText, text::Text};
use serde_json::{json, Value};

pub(super) struct StructureDeclarationRecords;

struct Header<'a> {
    index: usize,
    kind: &'a str,
    name: &'a str,
    modifiers: &'a str,
    receiver: &'a Value,
}

impl StructureDeclarationRecords {
    pub(super) fn scan(input: &Value) -> Option<Value> {
        let suffix = input.get("suffix")?.as_str()?;
        let typescript = matches!(suffix, ".ts" | ".tsx");
        let kotlin = matches!(suffix, ".kt" | ".kts");
        let scan = match suffix {
            ".ts" | ".tsx" => StructureTsText::process(input),
            ".js" | ".jsx" => StructureJsDeclarations::request(input),
            ".kt" | ".kts" => StructureKotlinDeclarations::scan(input),
            ".rs" => StructureRustDeclarations::scan(input),
            ".swift" | ".dart" => StructureBraceDeclarations::scan(input),
            ".py" => StructurePythonBlocks::top_level_classes(input),
            ".go" => StructureGoDeclarations::scan(input),
            _ => None,
        }?;
        let lines = if typescript {
            &scan["lines"]
        } else {
            input.get("lines")?
        }
        .as_array()?;
        let field = if suffix == ".py" {
            "classes"
        } else {
            "declarations"
        };
        let Some(declarations) = scan.get(field).and_then(Value::as_array) else {
            return typescript.then(|| json!({"lines": lines, "records": null}));
        };
        let headers = declarations
            .iter()
            .map(|row| {
                let (kind, name, modifiers) = match suffix {
                    ".py" => ("type", row.get(1)?.as_str()?, ""),
                    ".go" => (row.get(1)?.as_str()?, row.get(2)?.as_str()?, ""),
                    _ => (
                        row.get(1)?.as_str()?,
                        row.get(2)?.as_str()?,
                        row.get(3)?.as_str()?,
                    ),
                };
                Some(Header {
                    index: usize::try_from(row.get(0)?.as_u64()?).ok()?,
                    kind,
                    name,
                    modifiers,
                    receiver: if kotlin { row.get(4)? } else { &Value::Null },
                })
            })
            .collect::<Option<Vec<_>>>()?;
        let roles = StructureDeclarationRoles::classify_names(
            input,
            headers.iter().map(|header| (header.kind, header.name)),
        )?;
        let mut records = Vec::new();
        for (header, role) in headers.into_iter().zip(roles) {
            let source = lines.get(header.index)?.as_str()?;
            if let Some(row) = Self::record(header, role, source, suffix, kotlin) {
                records.push(row);
            }
        }
        let references = if typescript {
            Self::typescript_references(lines, &records)
        } else {
            None
        };
        Some(json!({"records": records, "lines": scan.get("lines"), "references": references}))
    }

    fn typescript_references(lines: &[Value], records: &[Value]) -> Option<Value> {
        let owners = records
            .iter()
            .map(|record| {
                // Ownership can still change when Python resolves a Unicode role.
                if !record.get("owner")?.as_bool()? {
                    return None;
                }
                Some((
                    usize::try_from(record.get("line")?.as_u64()?).ok()?,
                    record.get("name")?.as_str()?,
                ))
            })
            .collect::<Option<Vec<_>>>()?;
        let text = lines
            .iter()
            .map(Value::as_str)
            .collect::<Option<Vec<_>>>()?;
        Some(json!(StructureTsText::reference_sets(&text, &owners)))
    }

    fn record(
        header: Header<'_>,
        role: Value,
        source: &str,
        suffix: &str,
        kotlin: bool,
    ) -> Option<Value> {
        let swift = suffix == ".swift";
        let mut explicit_private = false;
        let mut internal = false;
        let mut exported = false;
        for word in header.modifiers.split(|ch| !PythonText::word(ch)) {
            match word {
                "private" | "fileprivate" => explicit_private = true,
                "internal" => internal = true,
                "package" if swift => internal = true,
                "export" | "public" | "pub" | "open" => exported = true,
                _ => {}
            }
        }
        let type_owner = matches!(
            header.kind,
            "actor"
                | "class"
                | "enum"
                | "interface"
                | "object"
                | "protocol"
                | "record"
                | "struct"
                | "trait"
                | "type"
                | "typealias"
        );
        let named_owner = header
            .name
            .as_bytes()
            .first()
            .is_some_and(u8::is_ascii_uppercase)
            || header
                .name
                .strip_prefix("use")
                .and_then(|tail| tail.as_bytes().first())
                .is_some_and(u8::is_ascii_uppercase);
        let owner = (kotlin && !explicit_private)
            || type_owner
            || named_owner
            || exported
            || internal
            || role.is_string();
        // A false role marker defers Unicode name classification to Python.
        if !owner && role.is_null() {
            return None;
        }
        let private = if suffix == ".rs" {
            !exported
        } else {
            explicit_private || header.name.starts_with('_')
        };
        Some(json!({
            "kind": header.kind, "name": header.name, "line": header.index + 1,
            "receiver": header.receiver, "role": role, "private": private,
            "internal": internal, "exported": exported, "owner": owner, "source": Text::py_strip(source),
        }))
    }
}
