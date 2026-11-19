//! owner: ManifestObject; allowed imports: ManifestValue and std collections; forbidden imports: process/network;
//! callers/tests: manifest parser/validator; verification: duplicate-key ordering tests.
use super::value::ManifestValue;
use std::collections::HashMap;

#[derive(Debug, Clone, Default)]
pub(crate) struct ManifestObject {
    entries: Vec<(String, ManifestValue)>,
    positions: Option<HashMap<String, usize>>,
}
impl ManifestObject {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn insert(&mut self, key: String, value: ManifestValue) {
        if let Some(index) = self.position(&key) {
            self.entries[index].1 = value;
            return;
        }
        // Keep small schema objects compact and wide input objects linear to build.
        if self.entries.len() == 32 && self.positions.is_none() {
            self.positions = Some(
                self.entries
                    .iter()
                    .enumerate()
                    .map(|(index, (key, _))| (key.clone(), index))
                    .collect(),
            );
        }
        if let Some(positions) = &mut self.positions {
            positions.insert(key.clone(), self.entries.len());
        }
        self.entries.push((key, value));
    }
    fn position(&self, key: &str) -> Option<usize> {
        match &self.positions {
            Some(positions) => positions.get(key).copied(),
            None => self.entries.iter().position(|(name, _)| name == key),
        }
    }
    pub fn get(&self, key: &str) -> Option<&ManifestValue> {
        self.position(key).map(|index| &self.entries[index].1)
    }
    pub fn contains_key(&self, key: &str) -> bool {
        self.get(key).is_some()
    }
    pub fn len(&self) -> usize {
        self.entries.len()
    }
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }
    pub fn iter(&self) -> impl Iterator<Item = (&String, &ManifestValue)> {
        self.entries.iter().map(|(k, v)| (k, v))
    }
}
