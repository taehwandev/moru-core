//! owner: MemoryUpkeep; allowed imports: std collections, serde_json, MemoryTerms, MemoryRecord;
//! forbidden imports: IO, process, store, writes, providers, clock, authority;
//! callers/tests: MemoryProcess and memory_upkeep_tests; verification: source parity.
use crate::{memory_record::MemoryRecord, memory_terms::MemoryTerms};
use serde_json::{json, Value};
use std::{
    borrow::Cow,
    collections::{HashMap, HashSet},
};

pub(crate) struct MemoryUpkeep;
impl MemoryUpkeep {
    pub(crate) fn evaluate(operation: &str, payload: &Value) -> Option<Value> {
        let object = payload.as_object()?;
        if object.get("unicode")?.as_str()? != MemoryTerms::version() {
            return None;
        }
        let render = match object.get("render") {
            None => false,
            Some(Value::Bool(true)) => true,
            _ => return None,
        };
        let records = object.get("records")?.as_array()?;
        match operation {
            "upkeep-live" if object.len() == 3 => Self::live(records, object.get("statuses")?),
            "upkeep-replacements" if object.len() == 2 => Self::replacements(records),
            "upkeep-startup-text" if object.len() == 4 + usize::from(render) => {
                let mut result = Self::startup(
                    records,
                    object.get("today")?,
                    true,
                    true,
                    Some(object.get("statuses")?),
                )?;
                if render {
                    let counts = result.get("counts")?;
                    let names = ["expired", "exact_duplicates", "shared_source", "unfinished"];
                    let values = names
                        .iter()
                        .map(|name| counts.get(name)?.as_u64())
                        .collect::<Option<Vec<_>>>()?;
                    result["text"] = json!(if values.iter().all(|&n| n == 0) {
                        String::new()
                    } else {
                        let fields = names
                            .iter()
                            .zip(values)
                            .map(|(name, n)| format!("{name}={n}"))
                            .collect::<Vec<_>>()
                            .join(" ");
                        format!("Project memory upkeep: {fields}")
                    });
                }
                Some(result)
            }
            "upkeep-startup" | "upkeep-startup-dates" | "upkeep-startup-text"
                if object.len() == 3 =>
            {
                Self::startup(
                    records,
                    object.get("today")?,
                    operation != "upkeep-startup",
                    operation == "upkeep-startup-text",
                    None,
                )
            }
            _ => None,
        }
    }

    fn live(records: &[Value], statuses: &Value) -> Option<Value> {
        let allowed = statuses
            .as_array()?
            .iter()
            .map(Value::as_str)
            .collect::<Option<HashSet<_>>>()?;
        let mut ids = Vec::with_capacity(records.len());
        let mut indices = Vec::new();
        for (index, item) in records.iter().enumerate() {
            let row = item.as_object()?;
            if row.len() != 2 {
                return None;
            }
            ids.push(row.get("id")?.as_str()?);
            if allowed.contains(row.get("status")?.as_str()?) {
                indices.push(index);
            }
        }
        indices.sort_by_key(|&index| ids[index]);
        Some(json!({"indices": indices}))
    }

    fn replacements(records: &[Value]) -> Option<Value> {
        let mut ids = Vec::with_capacity(records.len());
        let mut links: HashMap<&str, Vec<usize>> = HashMap::new();
        for (index, item) in records.iter().enumerate() {
            let row = item.as_object()?;
            if row.len() != 2 {
                return None;
            }
            ids.push(row.get("id")?.as_str()?);
            if let Some(target) = Self::link(row.get("replaces")?)? {
                if !target.is_empty() {
                    links.entry(target).or_default().push(index);
                }
            }
        }
        let mut findings = Vec::new();
        for (index, id) in ids.iter().enumerate() {
            if let Some(members) = links.get(*id) {
                let mut ordered = members.clone();
                ordered.sort_by_key(|&member| ids[member]);
                findings.push(json!({"index":index,"replacements":ordered}));
            }
        }
        Some(json!({"findings":findings}))
    }

    fn startup(
        records: &[Value],
        today: &Value,
        iso: bool,
        normalize: bool,
        statuses: Option<&Value>,
    ) -> Option<Value> {
        let today = Self::date_key(today, iso)?;
        let statuses = match statuses {
            Some(value) => Some(
                value
                    .as_array()?
                    .iter()
                    .map(Value::as_str)
                    .collect::<Option<HashSet<_>>>()?,
            ),
            None => None,
        };
        let mut bodies: HashMap<Cow<'_, str>, HashMap<&str, usize>> = HashMap::new();
        let mut sources: HashMap<Cow<'_, str>, usize> = HashMap::new();
        let mut replaced = HashSet::new();
        let mut ids = Vec::with_capacity(records.len());
        let mut expired = 0;
        for item in records {
            let row = item.as_object()?;
            if row.len() != 6 + usize::from(statuses.is_some()) {
                return None;
            }
            if let Some(statuses) = &statuses {
                let status = row.get("status")?.as_str()?;
                if ["id", "body", "scope", "source", "review", "replaces"]
                    .iter()
                    .any(|key| !row.contains_key(*key))
                {
                    return None;
                }
                if !statuses.contains(status) {
                    continue;
                }
            }
            ids.push(row.get("id")?.as_str()?);
            let body = Self::text_key(row.get("body")?.as_str()?, normalize);
            let scope = row.get("scope")?.as_str()?;
            if !body.is_empty() {
                *bodies.entry(body).or_default().entry(scope).or_default() += 1;
            }
            *sources
                .entry(Self::text_key(row.get("source")?.as_str()?, normalize))
                .or_default() += 1;
            if let Some(target) = Self::link(row.get("replaces")?)? {
                replaced.insert(target);
            }
            let review = Self::date_key(row.get("review")?, iso)?;
            expired += usize::from(review <= today);
        }
        let exact_duplicates: usize = bodies
            .values()
            .map(|counts| {
                if counts.contains_key("all") {
                    usize::from(counts.values().sum::<usize>() > 1)
                } else {
                    counts.values().filter(|&&count| count > 1).count()
                }
            })
            .sum();
        Some(json!({"counts": {
            "expired":expired,"exact_duplicates":exact_duplicates,
            "shared_source":sources.values().filter(|&&count| count > 1).count(),
            "unfinished":ids.iter().filter(|id| replaced.contains(**id)).count()
        }}))
    }

    fn text_key(text: &str, normalize: bool) -> Cow<'_, str> {
        if normalize {
            Cow::Owned(MemoryTerms::normalize(text))
        } else {
            Cow::Borrowed(text)
        }
    }

    fn date_key(value: &Value, iso: bool) -> Option<i64> {
        if iso {
            let text = value.as_str()?;
            return MemoryRecord::date(text).then(|| text.replace('-', "").parse().ok())?;
        }
        value.as_i64().filter(|day| (1..=3652059).contains(day))
    }

    fn link(value: &Value) -> Option<Option<&str>> {
        match value {
            Value::Null => Some(None),
            Value::String(text) => Some(Some(text)),
            _ => None,
        }
    }
}

#[cfg(test)]
#[path = "memory_upkeep_tests.rs"]
mod tests;
