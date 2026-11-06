//! owner: ManifestObject; allowed imports: ManifestValue; forbidden imports: process/network;
//! callers/tests: manifest parser/validator; verification: duplicate-key ordering tests.
use super::value::ManifestValue;
#[derive(Debug, Clone, Default)]
pub(super) struct ManifestObject(Vec<(String, ManifestValue)>);
impl ManifestObject {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn insert(&mut self, key: String, value: ManifestValue) {
        if let Some((_, old)) = self.0.iter_mut().find(|(k, _)| k == &key) {
            *old = value;
        } else {
            self.0.push((key, value));
        }
    }
    pub fn get(&self, key: &str) -> Option<&ManifestValue> {
        self.0.iter().find(|(k, _)| k == key).map(|(_, v)| v)
    }
    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }
    pub fn len(&self) -> usize {
        self.0.len()
    }
    pub fn is_empty(&self) -> bool {
        self.0.is_empty()
    }
    pub fn iter(&self) -> impl Iterator<Item = (&String, &ManifestValue)> {
        self.0.iter().map(|(k, v)| (k, v))
    }
}
