//! owner: oversized structural block diagnostics from current and baseline facts.
//! allowed imports: JSON, collections and string formatting.
//! forbidden imports: filesystem, Git invocations and approval decisions.
//! callers/tests: file diagnostic batch and structural parity fixtures.
//! verification: baseline label matching, initial builds and message order.
use super::structure_block_spans::StructureBlockSpans;
use serde_json::Value;
use std::collections::HashMap;

pub(super) struct StructureBlockFindings;

impl StructureBlockFindings {
    pub(super) fn append(
        path: &str,
        facts: &Value,
        failures: &mut Vec<String>,
        warnings: &mut Vec<String>,
    ) -> Option<()> {
        let limit = facts.get("limit")?.as_i64()?;
        let initial = facts.get("initial")?.as_bool()?;
        let current = facts.get("current")?.as_array()?;
        let baseline;
        let previous_blocks = if let Some(prepared) = facts.get("previous_spans") {
            baseline = StructureBlockSpans::records(prepared)?;
            &baseline
        } else {
            facts.get("previous")?.as_array()?
        };
        let mut previous = HashMap::new();
        for block in previous_blocks {
            previous.insert(block.get("label")?.as_str()?, block.get("span")?.as_u64()?);
        }
        for block in current {
            let label = block.get("label")?.as_str()?;
            let span = block.get("span")?.as_u64()?;
            let line = block.get("line")?.as_u64()?;
            if initial {
                warnings.push(format!(
                    "{path}:{line} block `{label}` spans {span} lines \
                     in an initial full-build workspace (no Git HEAD commit); limit is {limit}; \
                     structure-review evidence is required, and cohesive private helpers should be extracted \
                     before incremental commits"
                ));
            } else if let Some(old) = previous.get(label).filter(|old| span <= **old) {
                warnings.push(format!(
                    "{path}:{line} block `{label}` is a pre-existing \
                     oversized unit spanning {span} lines (previously {old}); \
                     limit is {limit}; structure-review evidence is required, but this \
                     does not block the current scoped change unless the diff grows the unit or adds \
                     a new responsibility"
                ));
            } else {
                failures.push(format!(
                    "{path}:{line} block `{label}` spans {span} lines; \
                     limit is {limit}; extract a cohesive private step with a focused check \
                     until the block is within the limit, or use an explicitly reviewed \
                     project-specific max-function-lines limit; \
                     structure-review prose alone does not bypass this hard gate"
                ));
            }
        }
        Some(())
    }
}
