//! Backend selection for the native ingress; no policy decisions or I/O.

use std::env;

pub(crate) enum Backend {
    Native,
    Python,
    Unknown,
}

impl Backend {
    pub(crate) fn from_env() -> Self {
        match env::var_os("MORU_CHECKOUT_IDENTITY_BACKEND") {
            None => Self::Native,
            Some(value) => match value.to_str() {
                Some("") | Some("auto") | Some("rust") => Self::Native,
                Some("python") => Self::Python,
                _ => Self::Unknown,
            },
        }
    }
}
