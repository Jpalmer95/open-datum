use crate::ir::{Discipline, SpatialDocument};
use crate::mesh::node_world_aabb;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ClashSeverity {
    HardClash,
    ClearanceViolation,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClashResult {
    pub node_a: String,
    pub discipline_a: Discipline,
    pub node_b: String,
    pub discipline_b: Discipline,
    pub severity: ClashSeverity,
    /// Positive for penetration depth, negative for clearance gap (in document length units).
    pub overlap_or_gap: f64,
    pub overlap_box_min: [f64; 3],
    pub overlap_box_max: [f64; 3],
    pub recommendation: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ClashReport {
    pub document_name: String,
    pub length_unit: String,
    pub clearance_threshold: f64,
    pub pairs_checked: usize,
    pub hard_clashes: usize,
    pub clearance_violations: usize,
    pub clashes: Vec<ClashResult>,
}

/// Runs fast multi-discipline 3D clash & clearance detection across all spatial nodes.
/// Ideal for MEP vs Structural routing verification (e.g., PLE mechanical/electrical tasks).
pub fn detect_clashes(doc: &SpatialDocument, min_clearance: f64) -> ClashReport {
    let mut bounds = Vec::new();
    for node in &doc.nodes {
        if let Some((mn, mx)) = node_world_aabb(node) {
            bounds.push((node, mn, mx));
        }
    }

    let mut clashes = Vec::new();
    let mut pairs_checked = 0usize;
    let mut hard_clashes = 0usize;
    let mut clearance_violations = 0usize;

    for i in 0..bounds.len() {
        for j in (i + 1)..bounds.len() {
            let (na, a_min, a_max) = bounds[i];
            let (nb, b_min, b_max) = bounds[j];

            // Skip direct parent-child pairs.
            if na.parent_id.as_deref() == Some(&nb.id) || nb.parent_id.as_deref() == Some(&na.id) {
                continue;
            }

            pairs_checked += 1;

            // Compute signed overlap along each axis.
            let mut axis_overlap = [0.0f64; 3];
            let mut o_min = [0.0f64; 3];
            let mut o_max = [0.0f64; 3];

            for k in 0..3 {
                o_min[k] = a_min[k].max(b_min[k]);
                o_max[k] = a_max[k].min(b_max[k]);
                axis_overlap[k] = o_max[k] - o_min[k];
            }

            let min_ov = axis_overlap[0].min(axis_overlap[1]).min(axis_overlap[2]);

            if min_ov > 1e-6 {
                hard_clashes += 1;
                clashes.push(ClashResult {
                    node_a: na.id.clone(),
                    discipline_a: na.discipline,
                    node_b: nb.id.clone(),
                    discipline_b: nb.discipline,
                    severity: ClashSeverity::HardClash,
                    overlap_or_gap: min_ov,
                    overlap_box_min: o_min,
                    overlap_box_max: o_max,
                    recommendation: format!(
                        "Hard collision between {:?} '{}' and {:?} '{}' (penetration {:.4} {}). Reroute MEP/secondary element or adjust elevation.",
                        na.discipline,
                        na.name,
                        nb.discipline,
                        nb.name,
                        min_ov,
                        doc.datum.length_unit.as_str()
                    ),
                });
            } else if min_clearance > 0.0 {
                // Compute Euclidean separation distance between AABBs.
                let mut dist_sq = 0.0;
                for k in 0..3 {
                    if axis_overlap[k] < 0.0 {
                        dist_sq += axis_overlap[k] * axis_overlap[k];
                    }
                }
                let gap = dist_sq.sqrt();
                if gap < min_clearance {
                    clearance_violations += 1;
                    clashes.push(ClashResult {
                        node_a: na.id.clone(),
                        discipline_a: na.discipline,
                        node_b: nb.id.clone(),
                        discipline_b: nb.discipline,
                        severity: ClashSeverity::ClearanceViolation,
                        overlap_or_gap: -gap,
                        overlap_box_min: o_min,
                        overlap_box_max: o_max,
                        recommendation: format!(
                            "Clearance violation: gap {:.4} {} < required {:.4} {} between '{}' and '{}'.",
                            gap,
                            doc.datum.length_unit.as_str(),
                            min_clearance,
                            doc.datum.length_unit.as_str(),
                            na.name,
                            nb.name
                        ),
                    });
                }
            }
        }
    }

    ClashReport {
        document_name: doc.name.clone(),
        length_unit: doc.datum.length_unit.as_str().to_string(),
        clearance_threshold: min_clearance,
        pairs_checked,
        hard_clashes,
        clearance_violations,
        clashes,
    }
}
