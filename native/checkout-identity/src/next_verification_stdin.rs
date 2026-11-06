//! owner: StdinGuard; allowed imports: libc and local file metadata;
//! forbidden imports: consuming stdin, changing flags; callers/tests: NextProcess;
//! verification: seekable replay, closed empty pipe and nonreplayable input process parity.
use std::os::unix::fs::MetadataExt;
pub(crate) struct StdinGuard {
    offset: Option<libc::off_t>,
    committed: bool,
}
impl StdinGuard {
    pub(crate) fn new() -> Option<Self> {
        let mut stat: libc::stat = unsafe { std::mem::zeroed() };
        if unsafe { libc::fstat(0, &mut stat) } != 0 {
            return None;
        }
        let offset = match stat.st_mode & libc::S_IFMT {
            libc::S_IFREG => {
                let offset = unsafe { libc::lseek(0, 0, libc::SEEK_CUR) };
                if offset < 0 {
                    return None;
                }
                Some(offset)
            }
            libc::S_IFCHR => {
                let null = std::fs::metadata("/dev/null").ok()?;
                if stat.st_rdev as u64 != null.rdev() {
                    return None;
                }
                None
            }
            libc::S_IFIFO => {
                // Named FIFOs can gain a new writer after a temporary EOF.
                #[cfg(target_os = "linux")]
                {
                    let mut filesystem: libc::statfs = unsafe { std::mem::zeroed() };
                    // Linux UAPI PIPEFS_MAGIC identifies anonymous pipes.
                    if unsafe { libc::fstatfs(0, &mut filesystem) } != 0
                        || filesystem.f_type != 0x5049_5045
                    {
                        return None;
                    }
                }
                #[cfg(target_os = "macos")]
                if stat.st_dev != 0 || stat.st_nlink != 0 {
                    return None;
                }
                let mut poll = libc::pollfd {
                    fd: 0,
                    events: libc::POLLIN,
                    revents: 0,
                };
                let mut available: libc::c_int = -1;
                if unsafe { libc::poll(&mut poll, 1, 0) } != 1
                    || poll.revents & libc::POLLHUP == 0
                    || unsafe { libc::ioctl(0, libc::FIONREAD, &mut available) } != 0
                    || available != 0
                {
                    return None;
                }
                None
            }
            _ => return None,
        };
        Some(Self {
            offset,
            committed: false,
        })
    }
    pub(crate) fn commit(&mut self) {
        self.committed = true;
    }
}
impl Drop for StdinGuard {
    fn drop(&mut self) {
        if !self.committed {
            if let Some(offset) = self.offset {
                // stdin was seekable and no flags/descriptor are changed by native readers.
                unsafe {
                    libc::lseek(0, offset, libc::SEEK_SET);
                }
            }
        }
    }
}
