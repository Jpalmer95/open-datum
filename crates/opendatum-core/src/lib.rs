//! OpenDatum Core — Universal Spatial Intermediate Representation (USIR),
//! legacy 3D/CAD cleanup & parametric reconstruction, multi-discipline clash detection,
//! and multi-format adapters for AEC/BIM, Game Engines, Simulation, and 3D Fabrication.

pub mod adapters;
pub mod clash;
pub mod ir;
pub mod mesh;

pub use adapters::{
    convert_file, detect_format, export_document, import_document, SpatialFormat,
};
pub use clash::{detect_clashes, ClashReport, ClashResult, ClashSeverity};
pub use ir::{
    Connection, DatumFrame, Discipline, LengthUnit, MepPort, MeshData, MeshQualityReport,
    ParametricShape, PhysicsBody, PhysicsBodyKind, Provenance, RebuildOptions, RebuildReport,
    SpatialDocument, SpatialNode, Transform, UpAxis,
};
pub use mesh::{analyze_mesh, rebuild_document, tessellate_parametric};
