//! owner: collection of read-only project facts for doctor.
//! allowed imports: existing doctor and status readers, JSON.
//! forbidden imports: writes, installers, providers, permission grants.
//! callers/tests: completion probe and doctor report parity fixtures.
//! verification: fully supported results and fallback on a declined read.
use super::{doctor_permission_count::DoctorPermissionCount, doctor_project::DoctorProject};
use crate::status_process::StatusProcess;
use serde_json::{json, Value};

pub(super) struct DoctorProjectFacts;

impl DoctorProjectFacts {
    pub(super) fn collect(payload: &Value) -> Option<Value> {
        let project = DoctorProject::project(payload)?;
        let files = DoctorProject::inspect_path(project)?;
        let permissions = DoctorPermissionCount::count(project)?;
        let runs = StatusProcess::active_runs(payload)?;
        Some(json!({
            "files": files,
            "permissions": permissions,
            "active_runs": runs.get("active_runs")?,
        }))
    }
}
