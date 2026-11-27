//! Owner: observe local PNG headers and check frame scale in smoke-report order.
//! Allowed imports: bounded JSON and descriptor-relative, read-only filesystem access.
//! Forbidden imports: writes, arbitrary absolute frame paths, providers and image decoders.
//! Callers/tests: Figma smoke frame probe and offline bundle fixtures.
use crate::{atomic_sibling::AtomicSibling, python_input_file::PythonInputFile};
use serde_json::{json, Value};
use std::{
    ffi::CString,
    fs::File,
    io::Read,
    mem::MaybeUninit,
    os::{fd::AsRawFd, unix::fs::MetadataExt},
    path::Path,
};

const EXACT_LIMIT: f64 = (1_u64 << 52) as f64;

#[path = "figma_frame_directory.rs"]
mod directory;

fn size(root: &File, raw: &str) -> Option<Option<(u32, u32)>> {
    if !raw.ends_with(".png") {
        return None;
    }
    let parts: Vec<_> = raw.split('/').collect();
    if parts.len() > 32 || parts.iter().any(|p| matches!(*p, "" | "." | "..")) {
        return None;
    }
    let (leaf, parents) = parts.split_last()?;
    let mut directory = root.try_clone().ok()?;
    for part in parents {
        let name = CString::new(*part).ok()?;
        directory =
            AtomicSibling::open_relative(&directory, &name, libc::O_RDONLY | libc::O_DIRECTORY)?;
    }
    let name = CString::new(*leaf).ok()?;
    let mut before = MaybeUninit::<libc::stat>::uninit();
    if unsafe {
        libc::fstatat(
            directory.as_raw_fd(),
            name.as_ptr(),
            before.as_mut_ptr(),
            libc::AT_SYMLINK_NOFOLLOW,
        )
    } != 0
    {
        return None;
    }
    let before = unsafe { before.assume_init() };
    if before.st_mode & libc::S_IFMT != libc::S_IFREG || before.st_nlink != 1 {
        return None;
    }
    let file = AtomicSibling::open_relative(&directory, &name, libc::O_RDONLY | libc::O_NOCTTY)?;
    let opened = file.metadata().ok()?;
    if !opened.is_file()
        || opened.nlink() != 1
        || opened.ino() != before.st_ino as u64
        || opened.dev() != before.st_dev as u64
    {
        return None;
    }
    let mut head = Vec::with_capacity(24);
    file.take(24).read_to_end(&mut head).ok()?;
    if head.len() < 24 || !head.starts_with(b"\x89PNG\r\n\x1a\n") {
        return Some(None);
    }
    Some(Some((
        u32::from_be_bytes(head[16..20].try_into().ok()?),
        u32::from_be_bytes(head[20..24].try_into().ok()?),
    )))
}

fn expected(value: &Value, scale: f64) -> Option<i64> {
    let n = value.as_f64()?;
    let product = n * scale;
    (n.abs() <= EXACT_LIMIT && product.abs() <= EXACT_LIMIT)
        .then(|| product.round_ties_even() as i64)
}

fn check_scale(
    screen: &Value,
    bundle: &File,
    scale: f64,
    failures: &mut Vec<String>,
) -> Option<()> {
    let fields = screen.as_object()?;
    let path = match fields.get("imagePath") {
        None | Some(Value::Null) => return Some(()),
        Some(value) => value.as_str()?,
    };
    if !path.ends_with(".png") {
        return Some(());
    }
    let id = match fields.get("id") {
        None | Some(Value::Null) => "None",
        Some(id) => id.as_str()?,
    };
    let w = &screen["width"];
    let h = &screen["height"];
    if w.is_boolean() || h.is_boolean() {
        return None;
    }
    if !w.is_number() || !h.is_number() {
        failures.push(format!(
            "screen dimensions unavailable for scale check: {id}"
        ));
        return Some(());
    }
    let want = (expected(w, scale)?, expected(h, scale)?);
    let actual = size(bundle, path)?;
    if !actual.is_some_and(|(w, h)| {
        (i64::from(w) - want.0).abs() <= 1 && (i64::from(h) - want.1).abs() <= 1
    }) {
        let actual = actual.map_or_else(|| "None".into(), |(w, h)| format!("({w}, {h})"));
        failures.push(format!(
            "frame scale mismatch for {id}: actual={actual} expected=({}, {})",
            want.0, want.1
        ));
    }
    Some(())
}

pub(super) fn analyze(text: &str) -> Option<Value> {
    let data: Value = serde_json::from_str(text).ok()?;
    let root = Path::new(data.get("bundle_root")?.as_str()?);
    if !root.is_absolute()
        || root.parent().is_none()
        || PythonInputFile::through_descriptor(root)
        || root.canonicalize().ok()?.as_os_str() != root.as_os_str()
    {
        return None;
    }
    let bundle = AtomicSibling::open_directory(root)?;
    let discover = match data.get("discover") {
        None => false,
        Some(Value::Bool(true)) if data.get("frames").is_none() => true,
        _ => return None,
    };
    let frames: Vec<String> = if discover {
        let mut paths: Vec<_> = directory::names(&bundle, c"frames")?
            .into_iter()
            .filter(|name| name.ends_with(".png"))
            .map(|name| format!("frames/{name}"))
            .collect();
        paths.sort_unstable();
        paths
    } else {
        data.get("frames")?
            .as_array()?
            .iter()
            .map(|v| v.as_str().map(str::to_owned))
            .collect::<Option<_>>()?
    };
    let screens = data.get("screens")?.as_array()?;
    let scale = data.get("scale")?.as_f64()?;
    if frames.len() + screens.len() > 4096 || !scale.is_finite() || scale.abs() > EXACT_LIMIT {
        return None;
    }
    let mut failures = Vec::new();
    if frames.is_empty() {
        failures.push("no frame PNG downloaded".into());
    }
    for path in &frames {
        let name = path.strip_prefix("frames/")?;
        if name.contains('/') {
            return None;
        }
        match size(&bundle, path)? {
            None => failures.push(format!("invalid PNG: {name}")),
            Some((w, h)) if w == 0 || h == 0 => {
                failures.push(format!("empty PNG dimensions: {name} ({w}, {h})"))
            }
            _ => {}
        }
    }
    for screen in screens {
        check_scale(screen, &bundle, scale, &mut failures)?;
    }
    if discover {
        let assets = directory::names(&bundle, c"assets")?;
        // pathlib glob counts any matching immediate entry, including hidden
        // names and directories. Asset enumeration never opens the entries.
        let svg_count = assets.iter().filter(|name| name.ends_with(".svg")).count();
        let png_count = assets.iter().filter(|name| name.ends_with(".png")).count();
        return Some(
            json!({"failures":failures,"frames":frames,"svg_count":svg_count,"png_count":png_count}),
        );
    }
    Some(json!({"failures":failures}))
}
