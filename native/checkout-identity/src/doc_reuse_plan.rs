//! owner: ordered completed-run reuse decisions for one checkout;
//! allowed imports: registry candidates, snapshot matcher and takeaway credit;
//! forbidden imports: root discovery, evidence writes, delivery and providers;
//! callers/tests: private reuse-plan probe and document reuse conformance;
//! verification: both proof modes, coverage order, display cap and fallback.
use super::{doc_reuse_matches::ReuseSearch, DocTranscript};
use serde_json::{json, Value};

impl DocTranscript {
    pub(crate) fn reuse_plan(payload: &Value) -> Option<Value> {
        let search = ReuseSearch::prepare(payload)?;
        let current = payload.get("current")?.as_str()?;
        let require_takeaway = payload.get("require_takeaway")?.as_bool()?;
        let [limit, slots, chars] = payload.get("limits")?.as_array()?.as_slice() else {
            return None;
        };
        let limit = usize::try_from(limit.as_u64()?).ok()?;
        let slots = usize::try_from(slots.as_u64()?).ok()?;
        let chars = usize::try_from(chars.as_u64()?).ok()?;
        let mut takeaways = payload
            .get("takeaways")?
            .as_array()?
            .iter()
            .map(|value| value.as_str().map(str::to_owned))
            .collect::<Option<Vec<_>>>()?;
        let initial_takeaways = takeaways.len();
        if slots > 3 || chars > 400 || initial_takeaways > slots {
            return None;
        }

        let mut covered = vec![false; search.wanted_len()];
        for value in payload.get("covered")?.as_array()? {
            let index = usize::try_from(value.as_u64()?).ok()?;
            *covered.get_mut(index)? = true;
        }
        let mut remaining = covered.iter().filter(|seen| !**seen).count();
        let mut added = Vec::new();
        for id in Self::reuse_ids(search.root, current, limit)? {
            if remaining == 0 {
                break;
            }
            let run = search.run_dir(&id)?;
            let indices = search.matching_indices(&run, &id)?;
            if indices.iter().all(|&index| covered[index]) {
                continue;
            }
            let existing: Vec<_> = takeaways.iter().map(String::as_str).collect();
            let (credited, takeaway) = Self::credit_reuse_run(&run, &existing, slots, chars)?;
            if require_takeaway && !credited {
                continue;
            }
            takeaways.extend(takeaway);
            for index in indices {
                if !covered[index] {
                    covered[index] = true;
                    added.push(index);
                    remaining -= 1;
                }
            }
        }
        Some(json!([added, &takeaways[initial_takeaways..]]))
    }
}
