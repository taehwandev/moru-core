//! owner: Next.js adapter and TypeScript support declaration families.
//! allowed imports: declaration metadata JSON and local collections.
//! forbidden imports: source reads, Git invocations and workflow decisions.
//! callers/tests: structural owner facts and JavaScript/TypeScript parity fixtures.
//! verification: ordering, references, and baseline declaration identity.
use serde_json::{json, Value};
use std::collections::{HashMap, HashSet};

pub(super) struct StructureJsFamilies;

#[derive(Clone)]
struct Owner<'a> {
    name: &'a str,
    kind: &'a str,
    line: u64,
    private: bool,
    internal: bool,
    exported: bool,
    role: Option<&'a str>,
    default_page: bool,
    references: Vec<&'a str>,
}

impl<'a> Owner<'a> {
    fn parse(row: &'a Value) -> Option<Self> {
        let role = row.get("role")?;
        Some(Self {
            name: row.get("name")?.as_str()?,
            kind: row.get("kind")?.as_str()?,
            line: row.get("line")?.as_u64()?,
            private: row.get("private")?.as_bool()?,
            internal: row.get("internal")?.as_bool()?,
            exported: row.get("exported")?.as_bool()?,
            role: if role.is_null() {
                None
            } else {
                Some(role.as_str()?)
            },
            default_page: row.get("source")?.as_str()?.starts_with("export default "),
            references: row
                .get("references")?
                .as_array()?
                .iter()
                .map(Value::as_str)
                .collect::<Option<_>>()?,
        })
    }

    fn identity(&self) -> (&'a str, &'a str, bool, bool, bool) {
        (
            self.kind,
            self.name,
            self.private,
            self.internal,
            self.exported,
        )
    }

    fn support_type(&self) -> bool {
        matches!(self.kind, "type" | "interface")
    }

    fn visible_facts(&self) -> Value {
        json!({"name": self.name, "kind": self.kind, "line": self.line,
            "private": self.private, "internal": self.internal, "exported": self.exported,
            "role": self.role, "receiver": null})
    }
}

impl StructureJsFamilies {
    pub(super) fn prepare(input: &Value, policy: &Value) -> Option<(Value, Value)> {
        let parse = |key| {
            input
                .get(key)?
                .as_array()?
                .iter()
                .map(Owner::parse)
                .collect::<Option<Vec<_>>>()
        };
        let mut current = parse("declarations")?;
        let mut previous = parse("previous_declarations")?;
        Self::next_adapter(&mut current, policy)?;
        Self::next_adapter(&mut previous, policy)?;
        if policy.get("typescript")?.as_bool()? {
            let before = previous.iter().map(Owner::identity).collect::<HashSet<_>>();
            Self::support_types(&mut current);
            Self::support_types(&mut previous);
            let retained = previous.iter().map(Owner::identity).collect::<HashSet<_>>();
            current.retain(|owner| {
                !before.contains(&owner.identity()) || retained.contains(&owner.identity())
            });
        }
        let facts = |owners: Vec<Owner<'_>>| {
            Value::Array(owners.iter().map(Owner::visible_facts).collect())
        };
        Some((facts(current), facts(previous)))
    }

    fn next_adapter(rows: &mut Vec<Owner<'_>>, policy: &Value) -> Option<()> {
        let mode = policy.get("mode")?.as_str()?;
        if mode == "none" {
            return Some(());
        }
        let strings = |key| {
            policy
                .get(key)?
                .as_array()?
                .iter()
                .map(Value::as_str)
                .collect::<Option<HashSet<_>>>()
        };
        let segment = strings("segment")?;
        let methods = strings("methods")?;
        let hooks = strings("hooks")?;
        let mut selected = Vec::new();
        let mut reserved = Vec::new();
        let mut has_method = false;
        for (index, row) in rows.iter().enumerate() {
            if !matches!(row.kind, "function" | "const") {
                continue;
            }
            if mode == "page" && row.default_page {
                selected.push(index);
            }
            if row.exported {
                let method = mode == "route" && methods.contains(row.name);
                if method
                    || segment.contains(row.name)
                    || (mode == "page" && hooks.contains(row.name))
                {
                    reserved.push(index);
                    has_method |= method;
                }
            }
        }
        let name = match mode {
            "page" if !selected.is_empty() && !reserved.is_empty() => "NextPageAdapter",
            "route" if reserved.len() >= 2 && has_method => "NextRouteAdapter",
            "page" | "route" => return Some(()),
            _ => return None,
        };
        selected.extend(reserved);
        let first = *selected.iter().min_by_key(|&&index| rows[index].line)?;
        let mut family = rows[first].clone();
        family.name = name;
        family.kind = "framework_adapter";
        family.role = Some("contract");
        family.references = selected
            .iter()
            .flat_map(|&index| rows[index].references.iter().copied())
            .collect::<HashSet<_>>()
            .into_iter()
            .collect();
        let selected: HashSet<_> = selected.into_iter().collect();
        let mut index = 0;
        rows.retain(|_| {
            let keep = !selected.contains(&index);
            index += 1;
            keep
        });
        rows.push(family);
        Some(())
    }

    fn support_types(rows: &mut Vec<Owner<'_>>) {
        let types: HashMap<_, _> = rows
            .iter()
            .filter(|row| row.support_type())
            .map(|row| (row.name, row))
            .collect();
        let mut runtime: Vec<_> = rows
            .iter()
            .filter(|row| !row.support_type() && !row.private)
            .collect();
        if runtime.is_empty() && types.len() == rows.len() {
            let referenced: HashSet<_> = rows
                .iter()
                .flat_map(|row| {
                    row.references
                        .iter()
                        .copied()
                        .filter(|&name| name != row.name)
                })
                .collect();
            runtime.extend(rows.iter().filter(|row| !referenced.contains(row.name)));
        }
        let [root] = runtime.as_slice() else { return };
        let mut pending = root.references.clone();
        let mut support = HashSet::new();
        while let Some(name) = pending.pop() {
            if let Some(row) = types.get(name) {
                if name != root.name && support.insert(name) {
                    pending.extend(row.references.iter().copied());
                }
            }
        }
        rows.retain(|row| !support.contains(row.name));
    }
}
