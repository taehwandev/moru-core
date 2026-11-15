use super::released;
use std::io;

#[test]
fn only_the_release_byte_admits() {
    for byte in 0..=255 {
        assert_eq!(released([byte].as_slice()), byte == 1);
    }
    assert!(!released([].as_slice()));
}

#[test]
fn a_failed_read_never_admits() {
    struct Broken;
    impl io::Read for Broken {
        fn read(&mut self, _: &mut [u8]) -> io::Result<usize> {
            Err(io::Error::other("closed"))
        }
    }
    assert!(!released(Broken));
}
