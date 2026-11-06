//! owner: ManifestValue; allowed imports: std, ManifestNumber, ManifestObject;
//! forbidden imports: process/network; callers/tests: manifest parser/validator; verification: parser tests.
use super::{number::ManifestNumber, object::ManifestObject};
#[derive(Debug, Clone)]
pub(super) enum ManifestValue {
    Null,
    Bool(bool),
    Number(ManifestNumber),
    String(String),
    Array(Vec<Self>),
    Object(ManifestObject),
}
impl ManifestValue {
    pub fn as_object(&self) -> Option<&ManifestObject> {
        if let Self::Object(v) = self {
            Some(v)
        } else {
            None
        }
    }
    pub fn as_array(&self) -> Option<&Vec<Self>> {
        if let Self::Array(v) = self {
            Some(v)
        } else {
            None
        }
    }
    pub fn as_str(&self) -> Option<&str> {
        if let Self::String(v) = self {
            Some(v)
        } else {
            None
        }
    }
    pub fn is_array(&self) -> bool {
        matches!(self, Self::Array(_))
    }
    pub fn is_object(&self) -> bool {
        matches!(self, Self::Object(_))
    }
    pub fn get(&self, key: &str) -> Option<&Self> {
        self.as_object()?.get(key)
    }
}
impl std::ops::Index<&str> for ManifestValue {
    type Output = Self;
    fn index(&self, key: &str) -> &Self {
        self.get(key).unwrap_or(&Self::Null)
    }
}
#[cfg(test)]
impl From<serde_json::Value> for ManifestValue {
    fn from(value: serde_json::Value) -> Self {
        match value {
            serde_json::Value::Null => Self::Null,
            serde_json::Value::Bool(v) => Self::Bool(v),
            serde_json::Value::Number(v) => {
                Self::Number(ManifestNumber::from_token(&v.to_string(), 0).unwrap())
            }
            serde_json::Value::String(v) => Self::String(v),
            serde_json::Value::Array(v) => Self::Array(v.into_iter().map(Self::from).collect()),
            serde_json::Value::Object(v) => {
                let mut object = ManifestObject::new();
                for (k, v) in v {
                    object.insert(k, Self::from(v));
                }
                Self::Object(object)
            }
        }
    }
}
