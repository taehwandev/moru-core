//! Owner: bounded HQ report replacement under an existing project.
//! Allowed imports: descriptor-relative atomic file primitives, JSON, and local entropy.
//! Forbidden imports: providers, arbitrary destinations and lifecycle policy.
//! Callers/tests: HQ finish and decision report delivery tests.
use super::hq_report_run_id::HqReportRunId;
use crate::atomic_sibling::AtomicSibling;
use serde_json::{json, Value};
use std::{
    ffi::{CStr, CString},
    fs::File,
    io::{self, Read},
    os::fd::AsRawFd,
    path::Path,
};

const TEXT_FIELDS: &[&str] = &[
    "runId",
    "projectId",
    "taskId",
    "operatorLabel",
    "status",
    "result",
    "evidence",
    "decisionNeeded",
];

fn valid_report(run: &str, encoded: &str) -> Option<()> {
    if encoded.len() > 500 {
        return None;
    }
    let report: Value = serde_json::from_str(encoded).ok()?;
    let fields = report.as_object()?;
    let decision = match fields.get("status")?.as_str()? {
        "finished" => false,
        "decision_needed" => true,
        _ => return None,
    };
    if fields.len() != TEXT_FIELDS.len() + 2 + usize::from(decision)
        || fields.get("schema")?.as_u64()? != 1
        || fields.get("runId")?.as_str()? != run
        || fields.get("finishedAt")?.as_i64().is_none()
        || !TEXT_FIELDS
            .iter()
            .all(|key| fields.get(*key).is_some_and(Value::is_string))
        || serde_json::to_string(&report).ok()? != encoded
    {
        return None;
    }
    if decision {
        let options = fields.get("decisionOptions")?.as_array()?;
        if options.len() > 3
            || !options
                .iter()
                .all(|v| v.as_str().is_some_and(|s| s.chars().count() <= 60))
        {
            return None;
        }
    }
    Some(())
}

fn reject_symlink(dir: &File, name: &CStr) -> io::Result<()> {
    let mut stat = std::mem::MaybeUninit::<libc::stat>::uninit();
    if unsafe {
        libc::fstatat(
            dir.as_raw_fd(),
            name.as_ptr(),
            stat.as_mut_ptr(),
            libc::AT_SYMLINK_NOFOLLOW,
        )
    } != 0
    {
        let error = io::Error::last_os_error();
        return if error.kind() == io::ErrorKind::NotFound {
            Ok(())
        } else {
            Err(error)
        };
    }
    if unsafe { stat.assume_init() }.st_mode & libc::S_IFMT == libc::S_IFLNK {
        return Err(io::ErrorKind::InvalidInput.into());
    }
    Ok(())
}

fn write(mut dir: File, run: &str, encoded: &str) -> io::Result<Value> {
    let target = CString::new(format!("{run}.json"))?;
    let mut nonce = [0u8; 16];
    File::open("/dev/urandom")?.read_exact(&mut nonce)?;
    let temporary = CString::new(format!(
        "{run}.json.{:032x}.tmp",
        u128::from_be_bytes(nonce)
    ))?;
    for name in [c".moru", c"hq", c"reports"] {
        dir = AtomicSibling::ensure_directory(&dir, name).ok_or_else(io::Error::last_os_error)?;
    }
    reject_symlink(&dir, &target)?;
    AtomicSibling::Private.replace(&dir, &temporary, &target, encoded.as_bytes())?;
    Ok(json!({"written": true}))
}

pub(super) fn replace(request: &Value) -> Option<io::Result<Value>> {
    let fields = request.as_object()?;
    let run = fields.get("run_id")?.as_str()?;
    if fields.len() != 3 || !HqReportRunId::valid(run) {
        return None;
    }
    let project = Path::new(fields.get("project")?.as_str()?);
    let encoded = fields.get("encoded")?.as_str()?;
    valid_report(run, encoded)?;
    if !project.is_absolute() || project.canonicalize().ok()?.as_os_str() != project.as_os_str() {
        return None;
    }
    let directory = AtomicSibling::open_directory_result(project).ok()?;
    // After this point even partial directory creation must never trigger replay.
    Some(write(directory, run, encoded))
}
