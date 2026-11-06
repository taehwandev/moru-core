//! owner: ManifestNumber; allowed imports: std; forbidden imports: process/network;
//! callers/tests: manifest parser/validator; verification: numeric representation parity.
#[derive(Debug, Clone)]
pub(super) enum ManifestNumber {
    Integer(String),
    Float(f64),
}
impl ManifestNumber {
    /// Lexical validity is established by ManifestParser, never inferred from f64 parsing.
    pub fn from_token(token: &str, digit_limit: usize) -> Option<Self> {
        if token == "NaN" {
            return Some(Self::Float(f64::NAN));
        }
        if token == "Infinity" {
            return Some(Self::Float(f64::INFINITY));
        }
        if token == "-Infinity" {
            return Some(Self::Float(f64::NEG_INFINITY));
        }
        if token.contains(['.', 'e', 'E']) {
            return token.parse::<f64>().ok().map(Self::Float);
        }
        let digits = token.trim_start_matches('-').len();
        if digit_limit > 0 && digits > digit_limit {
            return None;
        }
        Some(Self::Integer(if token == "-0" {
            "0".into()
        } else {
            token.into()
        }))
    }
    pub fn truthy(&self) -> bool {
        match self {
            Self::Integer(v) => v != "0",
            Self::Float(v) => *v != 0.0,
        }
    }
    pub fn equals_u64(&self, value: u64) -> bool {
        match self {
            Self::Integer(v) => v == &value.to_string(),
            Self::Float(v) => *v == value as f64,
        }
    }
    pub fn text(&self) -> String {
        match self {
            Self::Integer(v) => v.clone(),
            Self::Float(v) => Self::float(*v),
        }
    }
    pub fn float(v: f64) -> String {
        if v.is_nan() {
            return "nan".into();
        }
        if v == f64::INFINITY {
            return "inf".into();
        }
        if v == f64::NEG_INFINITY {
            return "-inf".into();
        }
        let raw = format!("{v:?}");
        let Some((mantissa, exponent)) = raw.split_once('e') else {
            return raw;
        };
        let exponent: i32 = exponent.parse().expect("Rust float exponent");
        if !(-4..16).contains(&exponent) {
            return format!(
                "{}e{}{:02}",
                mantissa,
                if exponent >= 0 { "+" } else { "-" },
                exponent.abs()
            );
        }
        let sign = if mantissa.starts_with('-') { "-" } else { "" };
        let digits = mantissa.trim_start_matches('-').replace('.', "");
        let point = 1 + exponent;
        if point <= 0 {
            format!("{sign}0.{}{digits}", "0".repeat((-point) as usize))
        } else if point as usize >= digits.len() {
            format!(
                "{sign}{digits}{}.0",
                "0".repeat(point as usize - digits.len())
            )
        } else {
            format!(
                "{sign}{}.{}",
                &digits[..point as usize],
                &digits[point as usize..]
            )
        }
    }
}
