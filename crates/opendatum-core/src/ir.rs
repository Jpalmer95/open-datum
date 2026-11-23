use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// Schema version for OpenDatum Universal Spatial IR (USIR).
pub const USIR_SCHEMA_VERSION: &str = "0.1.0";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LengthUnit {
    Mm,
    Cm,
    M,
    In,
    Ft,
}

impl LengthUnit {
    /// Returns multiplicative factor to convert a length in `self` to meters.
    pub fn to_meters(self) -> f64 {
        match self {
            LengthUnit::Mm => 0.001,
            LengthUnit::Cm => 0.01,
            LengthUnit::M => 1.0,
            LengthUnit::In => 0.0254,
            LengthUnit::Ft => 0.3048,
        }
    }

    pub fn from_str_loose(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "mm" | "millimeter" | "millimeters" => Some(Self::Mm),
            "cm" | "centimeter" | "centimeters" => Some(Self::Cm),
            "m" | "meter" | "meters" => Some(Self::M),
            "in" | "inch" | "inches" => Some(Self::In),
            "ft" | "foot" | "feet" => Some(Self::Ft),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            LengthUnit::Mm => "mm",
            LengthUnit::Cm => "cm",
            LengthUnit::M => "m",
            LengthUnit::In => "in",
            LengthUnit::Ft => "ft",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "UPPERCASE")]
pub enum UpAxis {
    Y,
    Z,
}

impl UpAxis {
    pub fn from_str_loose(s: &str) -> Option<Self> {
        match s.trim().to_ascii_uppercase().as_str() {
            "Y" => Some(Self::Y),
            "Z" => Some(Self::Z),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Discipline {
    Architecture,
    Structural,
    Civil,
    Electrical,
    Mechanical,
    Plumbing,
    FireProtection,
    Gameplay,
    Fabrication,
    Aerospace,
    Generic,
}

impl Default for Discipline {
    fn default() -> Self {
        Self::Generic
    }
}

/// Canonical spatial & physical reference frame for a document.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DatumFrame {
    pub length_unit: LengthUnit,
    pub up_axis: UpAxis,
    pub right_handed: bool,
    /// Planetary / operational environment profile ID (e.g. "earth_sea_level", "lunar_mare_day", "mars_surface").
    pub environment: String,
    /// Gravity acceleration vector in m/s^2 in the document's coordinate axes.
    pub gravity_m_s2: [f64; 3],
    /// Optional WGS84 / planetary geodetic anchor [lat_deg, lon_deg, elev_m].
    #[serde(skip_serializing_if = "Option::is_none")]
    pub geodetic_origin: Option<[f64; 3]>,
}

impl Default for DatumFrame {
    fn default() -> Self {
        Self {
            length_unit: LengthUnit::M,
            up_axis: UpAxis::Y,
            right_handed: true,
            environment: "earth_sea_level".to_string(),
            gravity_m_s2: [0.0, -9.80665, 0.0],
            geodetic_origin: None,
        }
    }
}

impl DatumFrame {
    pub fn engineering_z_up() -> Self {
        Self {
            length_unit: LengthUnit::M,
            up_axis: UpAxis::Z,
            right_handed: true,
            environment: "earth_sea_level".to_string(),
            gravity_m_s2: [0.0, 0.0, -9.80665],
            geodetic_origin: None,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Transform {
    pub position: [f64; 3],
    /// Quaternion [x, y, z, w]
    pub rotation_xyzw: [f64; 4],
    pub scale: [f64; 3],
}

impl Default for Transform {
    fn default() -> Self {
        Self {
            position: [0.0, 0.0, 0.0],
            rotation_xyzw: [0.0, 0.0, 0.0, 1.0],
            scale: [1.0, 1.0, 1.0],
        }
    }
}

/// Concise, human- and agent-editable parametric geometry primitives.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ParametricShape {
    Box {
        size: [f64; 3],
    },
    Cylinder {
        radius: f64,
        height: f64,
        #[serde(default = "default_segments")]
        segments: u32,
    },
    PipeRun {
        start: [f64; 3],
        end: [f64; 3],
        outer_diameter: f64,
        wall_thickness: f64,
    },
    DuctRun {
        start: [f64; 3],
        end: [f64; 3],
        width: f64,
        height: f64,
    },
    ExtrudedPolygon {
        /// 2D polygon footprint vertices in XY (or XZ) plane.
        footprint: Vec<[f64; 2]>,
        height: f64,
    },
    LineSegment2D {
        start: [f64; 2],
        end: [f64; 2],
        layer: String,
    },
}

fn default_segments() -> u32 {
    24
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct MeshData {
    pub vertices: Vec<[f64; 3]>,
    pub indices: Vec<[u32; 3]>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub normals: Vec<[f64; 3]>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MeshQualityReport {
    pub vertex_count: usize,
    pub triangle_count: usize,
    pub degenerate_triangles: usize,
    pub boundary_edges: usize,
    pub non_manifold_edges: usize,
    pub is_manifold: bool,
    pub is_watertight: bool,
    pub printable_3d_ready: bool,
    pub aabb_min: [f64; 3],
    pub aabb_max: [f64; 3],
    pub dimensions: [f64; 3],
    pub surface_area: f64,
    pub signed_volume: f64,
    pub abs_volume: f64,
    pub centroid: [f64; 3],
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PhysicsBodyKind {
    Static,
    Dynamic,
    Kinematic,
    Sensor,
}

impl Default for PhysicsBodyKind {
    fn default() -> Self {
        Self::Static
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PhysicsBody {
    pub kind: PhysicsBodyKind,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mass_kg: Option<f64>,
    #[serde(default = "default_friction")]
    pub static_friction: f64,
    #[serde(default = "default_restitution")]
    pub restitution: f64,
    #[serde(default = "default_collider")]
    pub collider_hint: String,
}

fn default_friction() -> f64 {
    0.5
}
fn default_restitution() -> f64 {
    0.1
}
fn default_collider() -> String {
    "auto".to_string()
}

impl Default for PhysicsBody {
    fn default() -> Self {
        Self {
            kind: PhysicsBodyKind::Static,
            mass_kg: None,
            static_friction: 0.5,
            restitution: 0.1,
            collider_hint: "auto".to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MepPort {
    pub id: String,
    pub system: String, // e.g., "hvac_supply", "potable_water", "electrical_480v", "structural_pin"
    pub position: [f64; 3],
    pub direction: [f64; 3],
    #[serde(skip_serializing_if = "Option::is_none")]
    pub nominal_size_mm: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Connection {
    pub from_node: String,
    pub from_port: String,
    pub to_node: String,
    pub to_port: String,
    pub kind: String, // "bolted", "welded", "flanged", "electrical_feeder", "duct_transition"
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Provenance {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_format: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_entity_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_layer: Option<String>,
    /// When true, automated legacy rebuilds or agent updates must preserve manual edits.
    #[serde(default)]
    pub human_locked: bool,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub notes: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpatialNode {
    pub id: String,
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_id: Option<String>,
    #[serde(default)]
    pub discipline: Discipline,
    pub role: String,
    #[serde(default)]
    pub transform: Transform,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parametric: Option<ParametricShape>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mesh: Option<MeshData>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub material_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub physics: Option<PhysicsBody>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub ports: Vec<MepPort>,
    #[serde(default)]
    pub provenance: Provenance,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub properties: BTreeMap<String, serde_json::Value>,
}

impl SpatialNode {
    pub fn new(id: impl Into<String>, name: impl Into<String>, role: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            name: name.into(),
            parent_id: None,
            discipline: Discipline::Generic,
            role: role.into(),
            transform: Transform::default(),
            parametric: None,
            mesh: None,
            material_id: None,
            physics: None,
            ports: Vec::new(),
            provenance: Provenance::default(),
            properties: BTreeMap::new(),
        }
    }
}

/// Top-level OpenDatum Universal Spatial IR Document (`.odir.json`).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpatialDocument {
    pub schema_version: String,
    pub name: String,
    #[serde(default)]
    pub datum: DatumFrame,
    #[serde(default)]
    pub nodes: Vec<SpatialNode>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub connections: Vec<Connection>,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub metadata: BTreeMap<String, serde_json::Value>,
}

impl SpatialDocument {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            schema_version: USIR_SCHEMA_VERSION.to_string(),
            name: name.into(),
            datum: DatumFrame::default(),
            nodes: Vec::new(),
            connections: Vec::new(),
            metadata: BTreeMap::new(),
        }
    }

    /// Produces a compact, token-efficient summary ideal for LLM agent inspection.
    pub fn compact_summary(&self) -> serde_json::Value {
        let mut by_discipline: BTreeMap<String, usize> = BTreeMap::new();
        let mut total_vertices = 0usize;
        let mut total_triangles = 0usize;
        let mut parametric_nodes = 0usize;
        let mut human_locked_nodes = 0usize;

        for node in &self.nodes {
            let key = format!("{:?}", node.discipline).to_ascii_lowercase();
            *by_discipline.entry(key).or_insert(0) += 1;
            if node.parametric.is_some() {
                parametric_nodes += 1;
            }
            if node.provenance.human_locked {
                human_locked_nodes += 1;
            }
            if let Some(m) = &node.mesh {
                total_vertices += m.vertices.len();
                total_triangles += m.indices.len();
            }
        }

        serde_json::json!({
            "schema_version": self.schema_version,
            "name": self.name,
            "datum": self.datum,
            "node_count": self.nodes.len(),
            "parametric_nodes": parametric_nodes,
            "human_locked_nodes": human_locked_nodes,
            "connection_count": self.connections.len(),
            "total_vertices": total_vertices,
            "total_triangles": total_triangles,
            "disciplines": by_discipline,
            "nodes_preview": self.nodes.iter().take(25).map(|n| serde_json::json!({
                "id": n.id,
                "name": n.name,
                "discipline": n.discipline,
                "role": n.role,
                "material_id": n.material_id,
                "has_parametric": n.parametric.is_some(),
                "triangles": n.mesh.as_ref().map(|m| m.indices.len()).unwrap_or(0),
                "human_locked": n.provenance.human_locked,
            })).collect::<Vec<_>>()
        })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RebuildOptions {
    pub target_unit: LengthUnit,
    pub target_up: UpAxis,
    pub weld_tolerance: f64,
    pub reconstruct_primitives: bool,
    pub strip_redundant_mesh_when_parametric: bool,
}

impl Default for RebuildOptions {
    fn default() -> Self {
        Self {
            target_unit: LengthUnit::M,
            target_up: UpAxis::Y,
            weld_tolerance: 1e-5,
            reconstruct_primitives: true,
            strip_redundant_mesh_when_parametric: false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RebuildReport {
    pub nodes_processed: usize,
    pub nodes_skipped_human_locked: usize,
    pub vertices_before: usize,
    pub vertices_after: usize,
    pub triangles_before: usize,
    pub triangles_after: usize,
    pub degenerate_removed: usize,
    pub primitives_reconstructed: usize,
    pub unit_scale_applied: f64,
    pub axis_remapped: bool,
}
