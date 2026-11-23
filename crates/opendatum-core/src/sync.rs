use crate::ir::{SpatialDocument, SpatialNode};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashSet};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MergeConflict {
    pub node_id: String,
    pub node_name: String,
    pub reason: String,
    pub resolution: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MergeReport {
    pub preserved_human_locked: Vec<String>,
    pub updated_nodes: Vec<String>,
    pub added_nodes: Vec<String>,
    pub retained_human_only_nodes: Vec<String>,
    pub conflicts: Vec<MergeConflict>,
}

/// Human-in-the-loop safe spatial merge between a `human_current` document
/// (e.g., edited in Godot/Bevy/CAD) and an `agent_incoming` update.
///
/// Rules:
/// 1. Any node marked `provenance.human_locked == true` in `human_current` is NEVER
///    overwritten by `agent_incoming` (its transform, parametric shape, mesh, material,
///    physics, and notes are preserved verbatim, and a conflict record is emitted if
///    the agent tried to alter it).
/// 2. Non-locked nodes present in `agent_incoming` are updated cleanly.
/// 3. New nodes from `agent_incoming` are added.
/// 4. Nodes present only in `human_current` with `human_locked == true` are retained
///    even if omitted by `agent_incoming`.
pub fn merge_documents(
    human_current: &SpatialDocument,
    agent_incoming: &SpatialDocument,
) -> (SpatialDocument, MergeReport) {
    let mut merged = agent_incoming.clone();
    merged.nodes.clear();

    let human_by_id: BTreeMap<&str, &SpatialNode> = human_current
        .nodes
        .iter()
        .map(|n| (n.id.as_str(), n))
        .collect();

    let mut seen_ids: HashSet<String> = HashSet::new();
    let mut report = MergeReport {
        preserved_human_locked: Vec::new(),
        updated_nodes: Vec::new(),
        added_nodes: Vec::new(),
        retained_human_only_nodes: Vec::new(),
        conflicts: Vec::new(),
    };

    for inc in &agent_incoming.nodes {
        seen_ids.insert(inc.id.clone());
        if let Some(&cur) = human_by_id.get(inc.id.as_str()) {
            if cur.provenance.human_locked {
                merged.nodes.push(cur.clone());
                report.preserved_human_locked.push(cur.id.clone());
                if cur.transform.position != inc.transform.position
                    || cur.material_id != inc.material_id
                {
                    report.conflicts.push(MergeConflict {
                        node_id: cur.id.clone(),
                        node_name: cur.name.clone(),
                        reason: "Agent attempted to modify transform or material of a human_locked node".to_string(),
                        resolution: "Kept human_locked version verbatim".to_string(),
                    });
                }
            } else {
                merged.nodes.push(inc.clone());
                report.updated_nodes.push(inc.id.clone());
            }
        } else {
            merged.nodes.push(inc.clone());
            report.added_nodes.push(inc.id.clone());
        }
    }

    // Retain any human_locked nodes that the agent omitted.
    for cur in &human_current.nodes {
        if !seen_ids.contains(&cur.id) && cur.provenance.human_locked {
            merged.nodes.push(cur.clone());
            report.retained_human_only_nodes.push(cur.id.clone());
        }
    }

    (merged, report)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ir::ParametricShape;

    #[test]
    fn test_merge_preserves_human_locked_and_applies_agent_updates() {
        let mut human = SpatialDocument::new("coedit_scene");
        let mut locked = SpatialNode::new("panel_1", "Main_Panel", "electrical_equipment");
        locked.transform.position = [1.5, 1.2, 0.0];
        locked.provenance.human_locked = true;

        let mut duct = SpatialNode::new("duct_1", "Supply_Duct", "duct");
        duct.transform.position = [0.0, 3.0, 0.0];
        duct.parametric = Some(ParametricShape::Box { size: [4.0, 0.3, 0.4] });

        human.nodes.push(locked);
        human.nodes.push(duct);

        let mut agent = human.clone();
        // Agent tries to move locked panel (must be rejected)
        agent.nodes[0].transform.position = [9.9, 9.9, 9.9];
        agent.nodes[0].provenance.human_locked = false;
        // Agent reroutes unlocked duct to clear clash (must be accepted)
        agent.nodes[1].transform.position = [0.0, 2.6, 0.0];
        // Agent adds a hanger support (must be added)
        let hanger = SpatialNode::new("hanger_1", "Seismic_Hanger", "support");
        agent.nodes.push(hanger);

        let (merged, rep) = merge_documents(&human, &agent);
        assert_eq!(merged.nodes.len(), 3);
        assert_eq!(rep.preserved_human_locked, vec!["panel_1"]);
        assert_eq!(rep.updated_nodes, vec!["duct_1"]);
        assert_eq!(rep.added_nodes, vec!["hanger_1"]);
        assert_eq!(rep.conflicts.len(), 1);

        let m_panel = merged.nodes.iter().find(|n| n.id == "panel_1").unwrap();
        assert_eq!(m_panel.transform.position, [1.5, 1.2, 0.0]);
        assert!(m_panel.provenance.human_locked);

        let m_duct = merged.nodes.iter().find(|n| n.id == "duct_1").unwrap();
        assert_eq!(m_duct.transform.position, [0.0, 2.6, 0.0]);
    }
}
