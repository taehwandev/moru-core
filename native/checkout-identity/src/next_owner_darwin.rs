//! owner: DarwinParent; allowed imports: libc and std ABI layout; forbidden imports:
//! process spawning/writes; callers/tests: ProcessOwner; verification: macOS live parity.
#[repr(C)]
#[derive(Default)]
struct ProcBsdInfo {
    flags: u32,
    status: u32,
    xstatus: u32,
    pid: u32,
    ppid: u32,
    uid: u32,
    gid: u32,
    ruid: u32,
    rgid: u32,
    svuid: u32,
    svgid: u32,
    reserved: u32,
    comm: [u8; 16],
    name: [u8; 32],
    nfiles: u32,
    pgid: u32,
    pjobc: u32,
    e_tdev: u32,
    e_tpgid: u32,
    nice: i32,
    start_sec: u64,
    start_usec: u64,
}
#[link(name = "proc")]
extern "C" {
    fn proc_pidinfo(
        pid: libc::c_int,
        flavor: libc::c_int,
        arg: u64,
        buffer: *mut libc::c_void,
        size: libc::c_int,
    ) -> libc::c_int;
}
pub(super) struct DarwinParent;
impl DarwinParent {
    pub(super) fn read(pid: i32) -> u32 {
        if pid < 1 {
            return 0;
        }
        let mut info = ProcBsdInfo::default();
        let size = std::mem::size_of::<ProcBsdInfo>() as i32;
        let written =
            unsafe { proc_pidinfo(pid, 3, 0, (&mut info as *mut ProcBsdInfo).cast(), size) };
        if written == size {
            info.ppid
        } else {
            0
        }
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn bsd_info_layout_matches_canonical_ctypes_contract() {
        assert_eq!(std::mem::size_of::<ProcBsdInfo>(), 136);
        assert_eq!(std::mem::align_of::<ProcBsdInfo>(), 8);
    }
}
