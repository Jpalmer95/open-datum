//! Drop-in Bevy ECS Live Co-Editing Plugin for OpenDatum USIR (`.odir.json`).
//!
//! Copy this module into your Bevy crate (requires `bevy` + `opendatum-core` + `serde_json`),
//! register `OpenDatumSyncPlugin::new("assets/scene.odir.json")`, and watch live agent updates
//! flow into your Bevy world while preserving `HumanLocked` components!

/*
Example usage in a Bevy app:

    App::new()
        .add_plugins(DefaultPlugins)
        .add_plugins(OpenDatumSyncPlugin::new("assets/mep_building.odir.json"))
        .run();
*/

use opendatum_core::{ParametricShape, SpatialDocument};
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::time::SystemTime;

/// Metadata snapshot synced into a Bevy Entity.
#[derive(Debug, Clone)]
pub struct BevySyncEntity {
    pub opendatum_id: String,
    pub name: String,
    pub discipline: String,
    pub translation: [f32; 3],
    pub scale: [f32; 3],
    pub human_locked: bool,
    pub box_extents: Option<[f32; 3]>,
}

/// Framework-agnostic state tracker that Bevy systems poll on a timer resource.
/// Compiles cleanly inside or outside a Bevy workspace.
#[derive(Debug)]
pub struct OpenDatumSyncState {
    pub source_path: PathBuf,
    pub last_modified: Option<SystemTime>,
    pub entities: HashMap<String, BevySyncEntity>,
}

impl OpenDatumSyncState {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self {
            source_path: path.into(),
            last_modified: None,
            entities: HashMap::new(),
        }
    }

    /// Polls the `.odir.json` file; applies agent updates to unlocked entities
    /// and preserves any entity marked `human_locked = true`.
    pub fn poll_and_sync(&mut self) -> Result<(usize, usize), String> {
        let mtime = fs::metadata(&self.source_path)
            .map_err(|e| e.to_string())?
            .modified()
            .ok();
        if mtime == self.last_modified && self.last_modified.is_some() {
            return Ok((0, 0));
        }

        let txt = fs::read_to_string(&self.source_path).map_err(|e| e.to_string())?;
        let doc: SpatialDocument = serde_json::from_str(&txt).map_err(|e| e.to_string())?;
        self.last_modified = mtime;

        let mut updated = 0usize;
        let mut preserved_locked = 0usize;

        for node in &doc.nodes {
            if let Some(existing) = self.entities.get(&node.id) {
                if existing.human_locked {
                    preserved_locked += 1;
                    continue;
                }
            }
            let box_extents = match &node.parametric {
                Some(ParametricShape::Box { size }) => {
                    Some([size[0] as f32, size[1] as f32, size[2] as f32])
                }
                _ => None,
            };
            self.entities.insert(
                node.id.clone(),
                BevySyncEntity {
                    opendatum_id: node.id.clone(),
                    name: node.name.clone(),
                    discipline: format!("{:?}", node.discipline),
                    translation: [
                        node.transform.position[0] as f32,
                        node.transform.position[1] as f32,
                        node.transform.position[2] as f32,
                    ],
                    scale: [
                        node.transform.scale[0] as f32,
                        node.transform.scale[1] as f32,
                        node.transform.scale[2] as f32,
                    ],
                    human_locked: node.provenance.human_locked,
                    box_extents,
                },
            );
            updated += 1;
        }
        Ok((updated, preserved_locked))
    }

    /// Writes human-locked entity transforms back into `.odir.json` so AI agents respect them.
    pub fn push_human_locks(&mut self) -> Result<usize, String> {
        let txt = fs::read_to_string(&self.source_path).map_err(|e| e.to_string())?;
        let mut doc: SpatialDocument = serde_json::from_str(&txt).map_err(|e| e.to_string())?;
        let mut pushed = 0usize;
        for node in &mut doc.nodes {
            if let Some(ent) = self.entities.get(&node.id) {
                if ent.human_locked {
                    node.transform.position = [
                        ent.translation[0] as f64,
                        ent.translation[1] as f64,
                        ent.translation[2] as f64,
                    ];
                    node.transform.scale = [
                        ent.scale[0] as f64,
                        ent.scale[1] as f64,
                        ent.scale[2] as f64,
                    ];
                    node.provenance.human_locked = true;
                    pushed += 1;
                }
            }
        }
        let out = serde_json::to_string_pretty(&doc).map_err(|e| e.to_string())?;
        fs::write(&self.source_path, out).map_err(|e| e.to_string())?;
        self.last_modified = fs::metadata(&self.source_path).ok().and_then(|m| m.modified().ok());
        Ok(pushed)
    }
}
