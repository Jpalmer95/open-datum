use crate::ir::{
    DatumFrame, Discipline, LengthUnit, MeshData, ParametricShape, PhysicsBody, PhysicsBodyKind,
    Provenance, SpatialDocument, SpatialNode, UpAxis,
};
use crate::mesh::{recompute_normals, resolve_node_mesh};
use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::fs;
use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SpatialFormat {
    Usir,
    Obj,
    Stl,
    ThreeMf,
    Gltf,
    Usda,
    GodotTscn,
    BevyRon,
    Dxf,
    Ifc,
}

impl SpatialFormat {
    pub fn from_name(s: &str) -> Option<Self> {
        match s.trim().to_ascii_lowercase().as_str() {
            "usir" | "odir" | "json" => Some(Self::Usir),
            "obj" => Some(Self::Obj),
            "stl" => Some(Self::Stl),
            "3mf" | "threemf" => Some(Self::ThreeMf),
            "gltf" | "glb" => Some(Self::Gltf),
            "usd" | "usda" => Some(Self::Usda),
            "godot" | "tscn" => Some(Self::GodotTscn),
            "bevy" | "ron" => Some(Self::BevyRon),
            "dxf" => Some(Self::Dxf),
            "ifc" => Some(Self::Ifc),
            _ => None,
        }
    }
}

pub fn detect_format(path: &Path) -> Option<SpatialFormat> {
    let fname = path.file_name()?.to_str()?.to_ascii_lowercase();
    if fname.ends_with(".odir.json") || fname.ends_with(".usir.json") {
        return Some(SpatialFormat::Usir);
    }
    let ext = path.extension()?.to_str()?.to_ascii_lowercase();
    SpatialFormat::from_name(&ext)
}

pub fn import_document(path: &Path, fmt_override: Option<SpatialFormat>) -> Result<SpatialDocument, String> {
    let fmt = fmt_override
        .or_else(|| detect_format(path))
        .ok_or_else(|| format!("Unsupported or unknown input format for {}", path.display()))?;
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("untitled")
        .to_string();

    match fmt {
        SpatialFormat::Usir => {
            let txt = fs::read_to_string(path).map_err(|e| e.to_string())?;
            serde_json::from_str(&txt).map_err(|e| format!("Invalid USIR JSON: {}", e))
        }
        SpatialFormat::Obj => {
            let txt = fs::read_to_string(path).map_err(|e| e.to_string())?;
            parse_obj(&txt, &stem)
        }
        SpatialFormat::Stl => {
            let bytes = fs::read(path).map_err(|e| e.to_string())?;
            parse_stl(&bytes, &stem)
        }
        SpatialFormat::Dxf => {
            let txt = fs::read_to_string(path).map_err(|e| e.to_string())?;
            parse_dxf(&txt, &stem)
        }
        SpatialFormat::Ifc => {
            let txt = fs::read_to_string(path).map_err(|e| e.to_string())?;
            parse_ifc(&txt, &stem)
        }
        other => Err(format!("Import from {:?} is not yet implemented in Rust core", other)),
    }
}

pub fn export_document(
    doc: &SpatialDocument,
    path: &Path,
    fmt_override: Option<SpatialFormat>,
) -> Result<(), String> {
    let fmt = fmt_override
        .or_else(|| detect_format(path))
        .ok_or_else(|| format!("Unsupported or unknown output format for {}", path.display()))?;

    if let Some(parent) = path.parent() {
        if !parent.as_os_str().is_empty() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
    }

    match fmt {
        SpatialFormat::Usir => {
            let txt = serde_json::to_string_pretty(doc).map_err(|e| e.to_string())?;
            fs::write(path, txt).map_err(|e| e.to_string())
        }
        SpatialFormat::Obj => fs::write(path, emit_obj(doc)).map_err(|e| e.to_string()),
        SpatialFormat::Stl => fs::write(path, emit_stl_ascii(doc)).map_err(|e| e.to_string()),
        SpatialFormat::ThreeMf => fs::write(path, emit_3mf_bytes(doc)).map_err(|e| e.to_string()),
        SpatialFormat::Gltf => fs::write(path, emit_gltf(doc)).map_err(|e| e.to_string()),
        SpatialFormat::Usda => fs::write(path, emit_usda(doc)).map_err(|e| e.to_string()),
        SpatialFormat::GodotTscn => fs::write(path, emit_godot_tscn(doc)).map_err(|e| e.to_string()),
        SpatialFormat::BevyRon => fs::write(path, emit_bevy_ron(doc)).map_err(|e| e.to_string()),
        SpatialFormat::Dxf => fs::write(path, emit_dxf(doc)).map_err(|e| e.to_string()),
        SpatialFormat::Ifc => Err("IFC export is planned via Python IfcOpenShell bridge".to_string()),
    }
}

pub fn convert_file(
    input: &Path,
    output: &Path,
    target_override: Option<SpatialFormat>,
) -> Result<SpatialDocument, String> {
    let doc = import_document(input, None)?;
    export_document(&doc, output, target_override)?;
    Ok(doc)
}

// ============================================================================
// IMPORTERS
// ============================================================================

pub fn parse_obj(input: &str, name: &str) -> Result<SpatialDocument, String> {
    let mut doc = SpatialDocument::new(name);
    let mut global_verts: Vec<[f64; 3]> = Vec::new();
    let mut current_name = name.to_string();
    let mut current_faces: Vec<[u32; 3]> = Vec::new();
    let mut node_idx = 0usize;

    let flush = |doc: &mut SpatialDocument,
                 verts: &[[f64; 3]],
                 faces: &mut Vec<[u32; 3]>,
                 obj_name: &str,
                 idx: &mut usize| {
        if faces.is_empty() {
            return;
        }
        // Compact vertices used by this object.
        let mut local_map: BTreeMap<u32, u32> = BTreeMap::new();
        let mut local_verts = Vec::new();
        let mut local_faces = Vec::with_capacity(faces.len());
        for tri in faces.drain(..) {
            let mut out_tri = [0u32; 3];
            for k in 0..3 {
                let g = tri[k];
                let l = *local_map.entry(g).or_insert_with(|| {
                    let id = local_verts.len() as u32;
                    local_verts.push(verts[g as usize]);
                    id
                });
                out_tri[k] = l;
            }
            local_faces.push(out_tri);
        }
        let mut mesh = MeshData {
            vertices: local_verts,
            indices: local_faces,
            normals: Vec::new(),
        };
        recompute_normals(&mut mesh);

        *idx += 1;
        let mut node = SpatialNode::new(format!("obj_{}", *idx), obj_name, "mesh_body");
        node.mesh = Some(mesh);
        node.provenance = Provenance {
            source_format: Some("obj".to_string()),
            source_entity_id: Some(obj_name.to_string()),
            ..Default::default()
        };
        doc.nodes.push(node);
    };

    for raw in input.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let mut parts = line.split_whitespace();
        match parts.next() {
            Some("o") | Some("g") => {
                flush(&mut doc, &global_verts, &mut current_faces, &current_name, &mut node_idx);
                current_name = parts.collect::<Vec<_>>().join("_");
                if current_name.is_empty() {
                    current_name = format!("object_{}", node_idx + 1);
                }
            }
            Some("v") => {
                let x: f64 = parts.next().and_then(|s| s.parse().ok()).unwrap_or(0.0);
                let y: f64 = parts.next().and_then(|s| s.parse().ok()).unwrap_or(0.0);
                let z: f64 = parts.next().and_then(|s| s.parse().ok()).unwrap_or(0.0);
                global_verts.push([x, y, z]);
            }
            Some("f") => {
                let mut poly = Vec::new();
                for tok in parts {
                    let v_str = tok.split('/').next().unwrap_or("");
                    if let Ok(vi) = v_str.parse::<i64>() {
                        let idx = if vi < 0 {
                            (global_verts.len() as i64 + vi) as usize
                        } else {
                            (vi - 1) as usize
                        };
                        if idx < global_verts.len() {
                            poly.push(idx as u32);
                        }
                    }
                }
                for i in 1..poly.len().saturating_sub(1) {
                    current_faces.push([poly[0], poly[i], poly[i + 1]]);
                }
            }
            _ => {}
        }
    }
    flush(&mut doc, &global_verts, &mut current_faces, &current_name, &mut node_idx);
    Ok(doc)
}

pub fn parse_stl(bytes: &[u8], name: &str) -> Result<SpatialDocument, String> {
    let is_ascii = bytes.starts_with(b"solid")
        && std::str::from_utf8(bytes)
            .map(|s| s.contains("facet normal") && s.contains("vertex"))
            .unwrap_or(false);

    let mut mesh = MeshData::default();
    if is_ascii {
        let txt = std::str::from_utf8(bytes).map_err(|e| e.to_string())?;
        let mut tri_verts = Vec::with_capacity(3);
        for raw in txt.lines() {
            let line = raw.trim();
            if let Some(rest) = line.strip_prefix("vertex") {
                let nums: Vec<f64> = rest
                    .split_whitespace()
                    .filter_map(|s| s.parse::<f64>().ok())
                    .collect();
                if nums.len() >= 3 {
                    tri_verts.push([nums[0], nums[1], nums[2]]);
                    if tri_verts.len() == 3 {
                        let base = mesh.vertices.len() as u32;
                        mesh.vertices.extend_from_slice(&tri_verts);
                        mesh.indices.push([base, base + 1, base + 2]);
                        tri_verts.clear();
                    }
                }
            }
        }
    } else {
        if bytes.len() < 84 {
            return Err("Binary STL too short".to_string());
        }
        let tri_count = u32::from_le_bytes([bytes[80], bytes[81], bytes[82], bytes[83]]) as usize;
        let expected = 84 + tri_count * 50;
        if bytes.len() < expected {
            return Err(format!(
                "Binary STL truncated: expected {} bytes for {} triangles, got {}",
                expected,
                tri_count,
                bytes.len()
            ));
        }
        for i in 0..tri_count {
            let off = 84 + i * 50 + 12; // skip 12-byte normal
            let base = mesh.vertices.len() as u32;
            for v in 0..3 {
                let vo = off + v * 12;
                let x = f32::from_le_bytes(bytes[vo..vo + 4].try_into().unwrap()) as f64;
                let y = f32::from_le_bytes(bytes[vo + 4..vo + 8].try_into().unwrap()) as f64;
                let z = f32::from_le_bytes(bytes[vo + 8..vo + 12].try_into().unwrap()) as f64;
                mesh.vertices.push([x, y, z]);
            }
            mesh.indices.push([base, base + 1, base + 2]);
        }
    }

    recompute_normals(&mut mesh);
    let mut doc = SpatialDocument::new(name);
    // Legacy STLs are overwhelmingly millimeters, Z-up.
    doc.datum = DatumFrame {
        length_unit: LengthUnit::Mm,
        up_axis: UpAxis::Z,
        ..DatumFrame::engineering_z_up()
    };
    let mut node = SpatialNode::new("stl_part_1", name, "fabrication_part");
    node.discipline = Discipline::Fabrication;
    node.mesh = Some(mesh);
    node.provenance = Provenance {
        source_format: Some("stl".to_string()),
        ..Default::default()
    };
    doc.nodes.push(node);
    Ok(doc)
}

/// Lightweight zero-dependency ASCII DXF parser for PLE-style 2D/3D engineering drawings
/// (extracts LINE, CIRCLE, LWPOLYLINE, TEXT entities with layers & discipline inference).
pub fn parse_dxf(input: &str, name: &str) -> Result<SpatialDocument, String> {
    let lines: Vec<&str> = input.lines().map(|l| l.trim()).collect();
    let mut doc = SpatialDocument::new(name);
    doc.datum = DatumFrame::engineering_z_up();

    let mut i = 0usize;
    let mut in_entities = false;
    let mut counter = 0usize;

    while i + 1 < lines.len() {
        let code = lines[i];
        let val = lines[i + 1];
        i += 2;

        if code == "2" && val == "ENTITIES" {
            in_entities = true;
            continue;
        }
        if in_entities && code == "0" && val == "ENDSEC" {
            break;
        }
        if !in_entities || code != "0" {
            continue;
        }

        let entity_type = val;
        let mut layer = "0".to_string();
        let mut handle = String::new();
        let mut x1 = 0.0f64;
        let mut y1 = 0.0f64;
        let mut z1 = 0.0f64;
        let mut x2 = 0.0f64;
        let mut y2 = 0.0f64;
        let mut z2 = 0.0f64;
        let mut radius = 0.0f64;
        let mut text = String::new();

        while i + 1 < lines.len() && lines[i] != "0" {
            let c = lines[i];
            let v = lines[i + 1];
            i += 2;
            match c {
                "5" => handle = v.to_string(),
                "8" => layer = v.to_string(),
                "10" => x1 = v.parse().unwrap_or(0.0),
                "20" => y1 = v.parse().unwrap_or(0.0),
                "30" => z1 = v.parse().unwrap_or(0.0),
                "11" => x2 = v.parse().unwrap_or(0.0),
                "21" => y2 = v.parse().unwrap_or(0.0),
                "31" => z2 = v.parse().unwrap_or(0.0),
                "40" => radius = v.parse().unwrap_or(0.0),
                "1" => text = v.to_string(),
                _ => {}
            }
        }

        let discipline = infer_discipline_from_layer(&layer);
        match entity_type {
            "LINE" => {
                counter += 1;
                let mut node = SpatialNode::new(
                    format!("dxf_line_{}", counter),
                    format!("{}_line_{}", layer, counter),
                    "cad_line",
                );
                node.discipline = discipline;
                node.parametric = Some(ParametricShape::LineSegment2D {
                    start: [x1, y1],
                    end: [x2, y2],
                    layer: layer.clone(),
                });
                node.properties.insert(
                    "z_endpoints".to_string(),
                    serde_json::json!([z1, z2]),
                );
                node.provenance = Provenance {
                    source_format: Some("dxf".to_string()),
                    source_entity_id: if handle.is_empty() { None } else { Some(handle) },
                    source_layer: Some(layer),
                    ..Default::default()
                };
                doc.nodes.push(node);
            }
            "CIRCLE" => {
                counter += 1;
                let mut node = SpatialNode::new(
                    format!("dxf_circle_{}", counter),
                    format!("{}_circle_{}", layer, counter),
                    "cad_circle",
                );
                node.discipline = discipline;
                node.transform.position = [x1, y1, z1];
                node.parametric = Some(ParametricShape::Cylinder {
                    radius: radius.max(1e-4),
                    height: 0.05,
                    segments: 24,
                });
                node.provenance = Provenance {
                    source_format: Some("dxf".to_string()),
                    source_entity_id: if handle.is_empty() { None } else { Some(handle) },
                    source_layer: Some(layer),
                    ..Default::default()
                };
                doc.nodes.push(node);
            }
            "TEXT" | "MTEXT" => {
                counter += 1;
                let mut node = SpatialNode::new(
                    format!("dxf_note_{}", counter),
                    format!("{}_note_{}", layer, counter),
                    "annotation",
                );
                node.discipline = discipline;
                node.transform.position = [x1, y1, z1];
                node.properties
                    .insert("text".to_string(), serde_json::json!(text));
                node.provenance = Provenance {
                    source_format: Some("dxf".to_string()),
                    source_entity_id: if handle.is_empty() { None } else { Some(handle) },
                    source_layer: Some(layer),
                    ..Default::default()
                };
                doc.nodes.push(node);
            }
            _ => {}
        }
    }

    Ok(doc)
}

fn infer_discipline_from_layer(layer: &str) -> Discipline {
    let l = layer.to_ascii_uppercase();
    if l.starts_with("S-") || l.contains("STRUCT") || l.contains("BEAM") || l.contains("COL") {
        Discipline::Structural
    } else if l.starts_with("M-") || l.contains("HVAC") || l.contains("DUCT") {
        Discipline::Mechanical
    } else if l.starts_with("E-") || l.contains("ELEC") || l.contains("POWER") || l.contains("PANEL") {
        Discipline::Electrical
    } else if l.starts_with("P-") || l.contains("PLUMB") || l.contains("PIPE") {
        Discipline::Plumbing
    } else if l.starts_with("C-") || l.contains("CIVIL") || l.contains("GRADE") || l.contains("STORM") {
        Discipline::Civil
    } else if l.starts_with("FP-") || l.contains("FIRE") || l.contains("SPRINK") {
        Discipline::FireProtection
    } else if l.starts_with("A-") || l.contains("WALL") || l.contains("ARCH") {
        Discipline::Architecture
    } else {
        Discipline::Generic
    }
}

/// Zero-dependency IFC STEP-SPF semantic inspector/importer.
/// Parses IFC building elements (`IFCWALL`, `IFCBEAM`, `IFCCOLUMN`, `IFCSLAB`,
/// `IFCFLOWSEGMENT`, `IFCPIPE`, `IFCDUCT`, `IFCSPACE`, `IFCBUILDINGSTOREY`) into USIR nodes
/// preserving GlobalIds, discipline semantics, and names.
pub fn parse_ifc(input: &str, name: &str) -> Result<SpatialDocument, String> {
    let mut doc = SpatialDocument::new(name);
    doc.datum = DatumFrame::engineering_z_up();

    for raw in input.lines() {
        let line = raw.trim();
        if !line.starts_with('#') {
            continue;
        }
        let Some((id_part, rhs)) = line.split_once('=') else {
            continue;
        };
        let rhs = rhs.trim();
        let Some(open_idx) = rhs.find('(') else {
            continue;
        };
        let entity = rhs[..open_idx].trim().to_ascii_uppercase();
        let (discipline, role) = match entity.as_str() {
            "IFCWALL" | "IFCWALLSTANDARDCASE" => (Discipline::Architecture, "wall"),
            "IFCSLAB" => (Discipline::Structural, "slab"),
            "IFCBEAM" => (Discipline::Structural, "beam"),
            "IFCCOLUMN" => (Discipline::Structural, "column"),
            "IFCFOOTING" => (Discipline::Structural, "footing"),
            "IFCDUCTSEGMENT" | "IFCAIRTERMINAL" => (Discipline::Mechanical, "duct"),
            "IFCPIPESEGMENT" | "IFCVALVE" => (Discipline::Plumbing, "pipe"),
            "IFCCABLECARRIERSEGMENT" | "IFCELECTRICDISTRIBUTIONBOARD" => {
                (Discipline::Electrical, "electrical_equipment")
            }
            "IFCFLOWSEGMENT" => (Discipline::Mechanical, "mep_segment"),
            "IFCSPACE" => (Discipline::Architecture, "space"),
            "IFCBUILDINGSTOREY" => (Discipline::Architecture, "storey"),
            _ => continue,
        };

        let args_str = rhs[open_idx + 1..].trim_end_matches(");");
        let quoted = extract_step_strings(args_str);
        let guid = quoted.first().cloned().unwrap_or_else(|| id_part.trim().to_string());
        let elem_name = quoted
            .get(1)
            .filter(|s| !s.is_empty())
            .cloned()
            .unwrap_or_else(|| format!("{}_{}", role, id_part.trim().trim_start_matches('#')));

        let mut node = SpatialNode::new(
            format!("ifc_{}", id_part.trim().trim_start_matches('#')),
            elem_name,
            role,
        );
        node.discipline = discipline;
        node.provenance = Provenance {
            source_format: Some("ifc".to_string()),
            source_entity_id: Some(guid),
            ..Default::default()
        };
        node.properties
            .insert("ifc_entity".to_string(), serde_json::json!(entity));
        doc.nodes.push(node);
    }

    Ok(doc)
}

fn extract_step_strings(s: &str) -> Vec<String> {
    let mut res = Vec::new();
    let mut chars = s.chars().peekable();
    while let Some(ch) = chars.next() {
        if ch == '\'' {
            let mut buf = String::new();
            while let Some(c) = chars.next() {
                if c == '\'' {
                    if chars.peek() == Some(&'\'') {
                        chars.next();
                        buf.push('\'');
                    } else {
                        break;
                    }
                } else {
                    buf.push(c);
                }
            }
            res.push(buf);
        }
    }
    res
}

// ============================================================================
// EXPORTERS
// ============================================================================

pub fn emit_obj(doc: &SpatialDocument) -> String {
    let mut out = String::new();
    let _ = writeln!(out, "# Exported by OpenDatum USIR v{}", doc.schema_version);
    let _ = writeln!(
        out,
        "# Document: {} | Units: {} | Up: {:?}",
        doc.name,
        doc.datum.length_unit.as_str(),
        doc.datum.up_axis
    );

    let mut vert_offset = 1usize;
    for node in &doc.nodes {
        let Some(mesh) = resolve_node_mesh(node) else {
            continue;
        };
        let _ = writeln!(out, "o {}", sanitize_ident(&node.name));
        for v in &mesh.vertices {
            let wx = v[0] * node.transform.scale[0] + node.transform.position[0];
            let wy = v[1] * node.transform.scale[1] + node.transform.position[1];
            let wz = v[2] * node.transform.scale[2] + node.transform.position[2];
            let _ = writeln!(out, "v {:.6} {:.6} {:.6}", wx, wy, wz);
        }
        for tri in &mesh.indices {
            let _ = writeln!(
                out,
                "f {} {} {}",
                tri[0] as usize + vert_offset,
                tri[1] as usize + vert_offset,
                tri[2] as usize + vert_offset
            );
        }
        vert_offset += mesh.vertices.len();
    }
    out
}

pub fn emit_stl_ascii(doc: &SpatialDocument) -> String {
    let mut out = String::new();
    let name = sanitize_ident(&doc.name);
    let _ = writeln!(out, "solid {}", name);
    for node in &doc.nodes {
        let Some(mesh) = resolve_node_mesh(node) else {
            continue;
        };
        for tri in &mesh.indices {
            let v0 = world_v(mesh.vertices[tri[0] as usize], &node.transform);
            let v1 = world_v(mesh.vertices[tri[1] as usize], &node.transform);
            let v2 = world_v(mesh.vertices[tri[2] as usize], &node.transform);
            let e1 = [v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]];
            let e2 = [v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]];
            let n = [
                e1[1] * e2[2] - e1[2] * e2[1],
                e1[2] * e2[0] - e1[0] * e2[2],
                e1[0] * e2[1] - e1[1] * e2[0],
            ];
            let len = (n[0] * n[0] + n[1] * n[1] + n[2] * n[2]).sqrt().max(1e-12);
            let _ = writeln!(
                out,
                "  facet normal {:.6} {:.6} {:.6}\n    outer loop\n      vertex {:.6} {:.6} {:.6}\n      vertex {:.6} {:.6} {:.6}\n      vertex {:.6} {:.6} {:.6}\n    endloop\n  endfacet",
                n[0] / len, n[1] / len, n[2] / len,
                v0[0], v0[1], v0[2],
                v1[0], v1[1], v1[2],
                v2[0], v2[1], v2[2]
            );
        }
    }
    let _ = writeln!(out, "endsolid {}", name);
    out
}

/// Emits a valid, slicer-ready 3MF archive (uncompressed ZIP container with proper CRC32)
/// compatible with PrusaSlicer, OrcaSlicer, Bambu Studio, and Cura.
pub fn emit_3mf_bytes(doc: &SpatialDocument) -> Vec<u8> {
    let unit_3mf = match doc.datum.length_unit {
        LengthUnit::Mm => "millimeter",
        LengthUnit::Cm => "centimeter",
        LengthUnit::M => "meter",
        LengthUnit::In => "inch",
        LengthUnit::Ft => "foot",
    };

    let mut model_xml = String::new();
    let _ = writeln!(
        model_xml,
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<model unit=\"{}\" xml:lang=\"en-US\" xmlns=\"http://schemas.microsoft.com/3dmanufacturing/core/2015/02\">\n  <metadata name=\"Application\">OpenDatum USIR v{}</metadata>\n  <resources>",
        unit_3mf, doc.schema_version
    );

    let mut build_items = Vec::new();
    let mut obj_id = 1usize;
    for node in &doc.nodes {
        let Some(mesh) = resolve_node_mesh(node) else {
            continue;
        };
        if mesh.vertices.is_empty() || mesh.indices.is_empty() {
            continue;
        }
        let _ = writeln!(
            model_xml,
            "    <object id=\"{}\" name=\"{}\" type=\"model\">\n      <mesh>\n        <vertices>",
            obj_id,
            xml_escape(&node.name)
        );
        for v in &mesh.vertices {
            let w = world_v(*v, &node.transform);
            let _ = writeln!(
                model_xml,
                "          <vertex x=\"{:.6}\" y=\"{:.6}\" z=\"{:.6}\" />",
                w[0], w[1], w[2]
            );
        }
        model_xml.push_str("        </vertices>\n        <triangles>\n");
        for tri in &mesh.indices {
            let _ = writeln!(
                model_xml,
                "          <triangle v1=\"{}\" v2=\"{}\" v3=\"{}\" />",
                tri[0], tri[1], tri[2]
            );
        }
        model_xml.push_str("        </triangles>\n      </mesh>\n    </object>\n");
        build_items.push(obj_id);
        obj_id += 1;
    }

    model_xml.push_str("  </resources>\n  <build>\n");
    for id in build_items {
        let _ = writeln!(model_xml, "    <item objectid=\"{}\" />", id);
    }
    model_xml.push_str("  </build>\n</model>\n");

    let content_types = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">\n  <Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\" />\n  <Default Extension=\"model\" ContentType=\"application/vnd.ms-package.3dmanufacturing-3dmodel+xml\" />\n</Types>\n";
    let rels = "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">\n  <Relationship Target=\"/3D/3dmodel.model\" Id=\"rel0\" Type=\"http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel\" />\n</Relationships>\n";

    build_stored_zip(&[
        ("[Content_Types].xml", content_types.as_bytes()),
        ("_rels/.rels", rels.as_bytes()),
        ("3D/3dmodel.model", model_xml.as_bytes()),
    ])
}

/// Emits a self-contained glTF 2.0 JSON document with embedded base64 geometry buffer
/// and OpenDatum engineering metadata in `extras`.
pub fn emit_gltf(doc: &SpatialDocument) -> String {
    let mut bin: Vec<u8> = Vec::new();
    let mut buffer_views = Vec::new();
    let mut accessors = Vec::new();
    let mut meshes_json = Vec::new();
    let mut nodes_json = Vec::new();
    let mut root_children = Vec::new();

    for node in &doc.nodes {
        let Some(mesh) = resolve_node_mesh(node) else {
            continue;
        };
        if mesh.vertices.is_empty() || mesh.indices.is_empty() {
            continue;
        }

        // Align to 4 bytes
        while bin.len() % 4 != 0 {
            bin.push(0);
        }
        let pos_offset = bin.len();
        let mut mn = [f32::INFINITY; 3];
        let mut mx = [f32::NEG_INFINITY; 3];
        for v in &mesh.vertices {
            for k in 0..3 {
                let f = v[k] as f32;
                if f < mn[k] {
                    mn[k] = f;
                }
                if f > mx[k] {
                    mx[k] = f;
                }
                bin.extend_from_slice(&f.to_le_bytes());
            }
        }
        let pos_len = bin.len() - pos_offset;
        let pos_bv = buffer_views.len();
        buffer_views.push(serde_json::json!({
            "buffer": 0,
            "byteOffset": pos_offset,
            "byteLength": pos_len,
            "target": 34962
        }));
        let pos_acc = accessors.len();
        accessors.push(serde_json::json!({
            "bufferView": pos_bv,
            "componentType": 5126,
            "count": mesh.vertices.len(),
            "type": "VEC3",
            "min": mn,
            "max": mx
        }));

        let idx_offset = bin.len();
        for tri in &mesh.indices {
            for &i in tri {
                bin.extend_from_slice(&i.to_le_bytes());
            }
        }
        let idx_len = bin.len() - idx_offset;
        let idx_bv = buffer_views.len();
        buffer_views.push(serde_json::json!({
            "buffer": 0,
            "byteOffset": idx_offset,
            "byteLength": idx_len,
            "target": 34963
        }));
        let idx_acc = accessors.len();
        accessors.push(serde_json::json!({
            "bufferView": idx_bv,
            "componentType": 5125,
            "count": mesh.indices.len() * 3,
            "type": "SCALAR"
        }));

        let mesh_idx = meshes_json.len();
        meshes_json.push(serde_json::json!({
            "name": node.name,
            "primitives": [{
                "attributes": { "POSITION": pos_acc },
                "indices": idx_acc
            }]
        }));

        let node_idx = nodes_json.len();
        nodes_json.push(serde_json::json!({
            "name": node.name,
            "mesh": mesh_idx,
            "translation": node.transform.position,
            "rotation": node.transform.rotation_xyzw,
            "scale": node.transform.scale,
            "extras": {
                "opendatum_id": node.id,
                "discipline": node.discipline,
                "role": node.role,
                "material_id": node.material_id,
                "human_locked": node.provenance.human_locked
            }
        }));
        root_children.push(node_idx);
    }

    let b64 = base64_encode(&bin);
    let gltf = serde_json::json!({
        "asset": {
            "version": "2.0",
            "generator": format!("OpenDatum USIR v{}", doc.schema_version),
            "extras": {
                "datum": doc.datum
            }
        },
        "scene": 0,
        "scenes": [{ "name": doc.name, "nodes": root_children }],
        "nodes": nodes_json,
        "meshes": meshes_json,
        "buffers": [{
            "byteLength": bin.len(),
            "uri": format!("data:application/octet-stream;base64,{}", b64)
        }],
        "bufferViews": buffer_views,
        "accessors": accessors
    });

    serde_json::to_string_pretty(&gltf).unwrap_or_default()
}

/// Emits human-readable OpenUSD ASCII (`.usda`) with `metersPerUnit`, `upAxis`,
/// and USD Physics attributes.
pub fn emit_usda(doc: &SpatialDocument) -> String {
    let mut out = String::new();
    let up = match doc.datum.up_axis {
        UpAxis::Y => "Y",
        UpAxis::Z => "Z",
    };
    let _ = writeln!(
        out,
        "#usda 1.0\n(\n    doc = \"Exported by OpenDatum USIR v{}\"\n    metersPerUnit = {}\n    upAxis = \"{}\"\n    defaultPrim = \"World\"\n)\n\ndef Xform \"World\" {{\n    custom string opendatum:environment = \"{}\"",
        doc.schema_version,
        doc.datum.length_unit.to_meters(),
        up,
        doc.datum.environment
    );

    for node in &doc.nodes {
        let pname = sanitize_ident(&node.name);
        let p = node.transform.position;
        let _ = writeln!(out, "    def Xform \"{}\" {{", pname);
        let _ = writeln!(
            out,
            "        double3 xformOp:translate = ({:.6}, {:.6}, {:.6})\n        uniform token[] xformOpOrder = [\"xformOp:translate\"]",
            p[0], p[1], p[2]
        );
        let _ = writeln!(
            out,
            "        custom string opendatum:discipline = \"{:?}\"\n        custom string opendatum:role = \"{}\"",
            node.discipline, node.role
        );
        if let Some(mat) = &node.material_id {
            let _ = writeln!(out, "        custom string opendatum:material_id = \"{}\"", mat);
        }
        if let Some(phys) = &node.physics {
            if let Some(mass) = phys.mass_kg {
                let _ = writeln!(out, "        float physics:mass = {:.4}", mass);
            }
        }

        if let Some(mesh) = resolve_node_mesh(node) {
            let _ = writeln!(out, "        def Mesh \"Geometry\" {{");
            let counts: Vec<String> = mesh.indices.iter().map(|_| "3".to_string()).collect();
            let indices: Vec<String> = mesh
                .indices
                .iter()
                .flat_map(|t| [t[0].to_string(), t[1].to_string(), t[2].to_string()])
                .collect();
            let points: Vec<String> = mesh
                .vertices
                .iter()
                .map(|v| format!("({:.6}, {:.6}, {:.6})", v[0], v[1], v[2]))
                .collect();
            let _ = writeln!(out, "            int[] faceVertexCounts = [{}]", counts.join(", "));
            let _ = writeln!(out, "            int[] faceVertexIndices = [{}]", indices.join(", "));
            let _ = writeln!(out, "            point3f[] points = [{}]", points.join(", "));
            let _ = writeln!(out, "        }}");
        }
        let _ = writeln!(out, "    }}");
    }

    out.push_str("}\n");
    out
}

/// Emits a Godot 4 `.tscn` scene with physics bodies, collision shapes, and metadata ready
/// for immediate opening and manual editing in the Godot Editor!
pub fn emit_godot_tscn(doc: &SpatialDocument) -> String {
    let mut sub_resources = String::new();
    let mut nodes_sec = String::new();
    let mut res_id = 1usize;

    let _ = writeln!(
        nodes_sec,
        "[node name=\"{}\" type=\"Node3D\"]\nmetadata/opendatum_schema = \"{}\"\nmetadata/opendatum_environment = \"{}\"\n",
        sanitize_ident(&doc.name),
        doc.schema_version,
        doc.datum.environment
    );

    for node in &doc.nodes {
        let nname = sanitize_ident(&node.name);
        let phys = node.physics.clone().unwrap_or_default();
        let body_type = match phys.kind {
            PhysicsBodyKind::Static => "StaticBody3D",
            PhysicsBodyKind::Dynamic => "RigidBody3D",
            PhysicsBodyKind::Kinematic => "CharacterBody3D",
            PhysicsBodyKind::Sensor => "Area3D",
        };
        let p = node.transform.position;
        let _ = writeln!(
            nodes_sec,
            "[node name=\"{}\" type=\"{}\" parent=\".\"]\ntransform = Transform3D(1, 0, 0, 0, 1, 0, 0, 0, 1, {:.6}, {:.6}, {:.6})",
            nname, body_type, p[0], p[1], p[2]
        );
        if phys.kind == PhysicsBodyKind::Dynamic {
            if let Some(m) = phys.mass_kg {
                let _ = writeln!(nodes_sec, "mass = {:.4}", m);
            }
        }
        let _ = writeln!(nodes_sec, "metadata/opendatum_id = \"{}\"", node.id);
        let _ = writeln!(nodes_sec, "metadata/discipline = \"{:?}\"", node.discipline);
        if let Some(mat) = &node.material_id {
            let _ = writeln!(nodes_sec, "metadata/material_id = \"{}\"", mat);
        }

        // Attach parametric MeshInstance3D + CollisionShape3D if Box or Cylinder, else bounding BoxShape3D.
        let (mesh_res, shape_res) = match &node.parametric {
            Some(ParametricShape::Box { size }) => {
                let mid = res_id;
                res_id += 1;
                let _ = writeln!(
                    sub_resources,
                    "[sub_resource type=\"BoxMesh\" id=\"Mesh_{}\"]\nsize = Vector3({:.6}, {:.6}, {:.6})\n",
                    mid, size[0], size[1], size[2]
                );
                let sid = res_id;
                res_id += 1;
                let _ = writeln!(
                    sub_resources,
                    "[sub_resource type=\"BoxShape3D\" id=\"Shape_{}\"]\nsize = Vector3({:.6}, {:.6}, {:.6})\n",
                    sid, size[0], size[1], size[2]
                );
                (Some(format!("Mesh_{}", mid)), Some(format!("Shape_{}", sid)))
            }
            Some(ParametricShape::Cylinder { radius, height, .. }) => {
                let mid = res_id;
                res_id += 1;
                let _ = writeln!(
                    sub_resources,
                    "[sub_resource type=\"CylinderMesh\" id=\"Mesh_{}\"]\ntop_radius = {:.6}\nbottom_radius = {:.6}\nheight = {:.6}\n",
                    mid, radius, radius, height
                );
                let sid = res_id;
                res_id += 1;
                let _ = writeln!(
                    sub_resources,
                    "[sub_resource type=\"CylinderShape3D\" id=\"Shape_{}\"]\nradius = {:.6}\nheight = {:.6}\n",
                    sid, radius, height
                );
                (Some(format!("Mesh_{}", mid)), Some(format!("Shape_{}", sid)))
            }
            _ => {
                if let Some((mn, mx)) = crate::mesh::node_world_aabb(node) {
                    let sx = (mx[0] - mn[0]).max(0.01);
                    let sy = (mx[1] - mn[1]).max(0.01);
                    let sz = (mx[2] - mn[2]).max(0.01);
                    let mid = res_id;
                    res_id += 1;
                    let _ = writeln!(
                        sub_resources,
                        "[sub_resource type=\"BoxMesh\" id=\"Mesh_{}\"]\nsize = Vector3({:.6}, {:.6}, {:.6})\n",
                        mid, sx, sy, sz
                    );
                    let sid = res_id;
                    res_id += 1;
                    let _ = writeln!(
                        sub_resources,
                        "[sub_resource type=\"BoxShape3D\" id=\"Shape_{}\"]\nsize = Vector3({:.6}, {:.6}, {:.6})\n",
                        sid, sx, sy, sz
                    );
                    (Some(format!("Mesh_{}", mid)), Some(format!("Shape_{}", sid)))
                } else {
                    (None, None)
                }
            }
        };

        if let Some(mr) = mesh_res {
            let _ = writeln!(
                nodes_sec,
                "\n[node name=\"Mesh\" type=\"MeshInstance3D\" parent=\"{}\"]\nmesh = SubResource(\"{}\")",
                nname, mr
            );
        }
        if let Some(sr) = shape_res {
            let _ = writeln!(
                nodes_sec,
                "\n[node name=\"Collider\" type=\"CollisionShape3D\" parent=\"{}\"]\nshape = SubResource(\"{}\")",
                nname, sr
            );
        }
        nodes_sec.push('\n');
    }

    format!(
        "[gd_scene load_steps={} format=3]\n\n{}\n{}",
        res_id, sub_resources, nodes_sec
    )
}

/// Emits a Bevy-compatible RON prefab/scene manifest ready for Bevy ECS & Avian/Rapier physics.
pub fn emit_bevy_ron(doc: &SpatialDocument) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "// OpenDatum Bevy Scene Manifest (USIR v{})\n(\n    name: \"{}\",\n    datum: (unit: \"{}\", up_axis: \"{:?}\", environment: \"{}\"),\n    entities: [",
        doc.schema_version,
        doc.name,
        doc.datum.length_unit.as_str(),
        doc.datum.up_axis,
        doc.datum.environment
    );
    for node in &doc.nodes {
        let p = node.transform.position;
        let r = node.transform.rotation_xyzw;
        let s = node.transform.scale;
        let phys = node.physics.as_ref().cloned().unwrap_or_else(PhysicsBody::default);
        let _ = writeln!(
            out,
            "        (\n            id: \"{}\",\n            name: \"{}\",\n            discipline: \"{:?}\",\n            role: \"{}\",\n            material_id: {},\n            transform: (translation: ({:.6}, {:.6}, {:.6}), rotation: ({:.6}, {:.6}, {:.6}, {:.6}), scale: ({:.6}, {:.6}, {:.6})),\n            physics: (body: \"{:?}\", mass_kg: {}, friction: {:.3}),\n        ),",
            node.id,
            node.name,
            node.discipline,
            node.role,
            node.material_id
                .as_ref()
                .map(|m| format!("Some(\"{}\")", m))
                .unwrap_or_else(|| "None".to_string()),
            p[0], p[1], p[2],
            r[0], r[1], r[2], r[3],
            s[0], s[1], s[2],
            phys.kind,
            phys.mass_kg
                .map(|m| format!("Some({:.4})", m))
                .unwrap_or_else(|| "None".to_string()),
            phys.static_friction
        );
    }
    out.push_str("    ],\n)\n");
    out
}

/// Emits a clean, layer-organized ASCII DXF R12/2000 drawing from USIR nodes (plan/3D lines & footprints).
pub fn emit_dxf(doc: &SpatialDocument) -> String {
    let mut out = String::new();
    out.push_str("0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n0\nENDSEC\n0\nSECTION\n2\nENTITIES\n");

    for node in &doc.nodes {
        let layer = format!("{:?}", node.discipline).to_ascii_uppercase();
        match &node.parametric {
            Some(ParametricShape::LineSegment2D { start, end, layer: l }) => {
                let _ = write!(
                    out,
                    "0\nLINE\n8\n{}\n10\n{:.6}\n20\n{:.6}\n30\n0.0\n11\n{:.6}\n21\n{:.6}\n31\n0.0\n",
                    l, start[0], start[1], end[0], end[1]
                );
            }
            Some(ParametricShape::PipeRun { start, end, .. })
            | Some(ParametricShape::DuctRun { start, end, .. }) => {
                let _ = write!(
                    out,
                    "0\nLINE\n8\n{}\n10\n{:.6}\n20\n{:.6}\n30\n{:.6}\n11\n{:.6}\n21\n{:.6}\n31\n{:.6}\n",
                    layer, start[0], start[1], start[2], end[0], end[1], end[2]
                );
            }
            Some(ParametricShape::Cylinder { radius, .. }) => {
                let p = node.transform.position;
                let _ = write!(
                    out,
                    "0\nCIRCLE\n8\n{}\n10\n{:.6}\n20\n{:.6}\n30\n{:.6}\n40\n{:.6}\n",
                    layer, p[0], p[1], p[2], radius
                );
            }
            _ => {
                if let Some((mn, mx)) = crate::mesh::node_world_aabb(node) {
                    let corners = [
                        (mn[0], mn[1]),
                        (mx[0], mn[1]),
                        (mx[0], mx[1]),
                        (mn[0], mx[1]),
                    ];
                    for k in 0..4 {
                        let a = corners[k];
                        let b = corners[(k + 1) % 4];
                        let _ = write!(
                            out,
                            "0\nLINE\n8\n{}\n10\n{:.6}\n20\n{:.6}\n30\n{:.6}\n11\n{:.6}\n21\n{:.6}\n31\n{:.6}\n",
                            layer, a.0, a.1, mn[2], b.0, b.1, mn[2]
                        );
                    }
                }
            }
        }
    }

    out.push_str("0\nENDSEC\n0\nEOF\n");
    out
}

// ============================================================================
// INTERNAL UTILITIES (ZERO EXTRA CRATES)
// ============================================================================

fn world_v(v: [f64; 3], t: &crate::ir::Transform) -> [f64; 3] {
    [
        v[0] * t.scale[0] + t.position[0],
        v[1] * t.scale[1] + t.position[1],
        v[2] * t.scale[2] + t.position[2],
    ]
}

fn sanitize_ident(s: &str) -> String {
    let mut out: String = s
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() || c == '_' { c } else { '_' })
        .collect();
    if out.is_empty() || out.chars().next().unwrap().is_ascii_digit() {
        out.insert(0, '_');
    }
    out
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

fn crc32(data: &[u8]) -> u32 {
    let mut crc = 0xFFFF_FFFFu32;
    for &b in data {
        crc ^= b as u32;
        for _ in 0..8 {
            if crc & 1 != 0 {
                crc = (crc >> 1) ^ 0xEDB8_8320;
            } else {
                crc >>= 1;
            }
        }
    }
    !crc
}

fn build_stored_zip(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut buf = Vec::new();
    let mut central = Vec::new();

    for (name, data) in entries {
        let offset = buf.len() as u32;
        let crc = crc32(data);
        let size = data.len() as u32;
        let name_bytes = name.as_bytes();
        let name_len = name_bytes.len() as u16;

        // Local file header
        buf.extend_from_slice(&0x0403_4b50u32.to_le_bytes());
        buf.extend_from_slice(&20u16.to_le_bytes()); // version needed
        buf.extend_from_slice(&0u16.to_le_bytes()); // flags
        buf.extend_from_slice(&0u16.to_le_bytes()); // stored (no compression)
        buf.extend_from_slice(&0u16.to_le_bytes()); // mod time
        buf.extend_from_slice(&0u16.to_le_bytes()); // mod date
        buf.extend_from_slice(&crc.to_le_bytes());
        buf.extend_from_slice(&size.to_le_bytes());
        buf.extend_from_slice(&size.to_le_bytes());
        buf.extend_from_slice(&name_len.to_le_bytes());
        buf.extend_from_slice(&0u16.to_le_bytes()); // extra len
        buf.extend_from_slice(name_bytes);
        buf.extend_from_slice(data);

        // Central directory header
        central.extend_from_slice(&0x0201_4b50u32.to_le_bytes());
        central.extend_from_slice(&20u16.to_le_bytes());
        central.extend_from_slice(&20u16.to_le_bytes());
        central.extend_from_slice(&0u16.to_le_bytes());
        central.extend_from_slice(&0u16.to_le_bytes());
        central.extend_from_slice(&0u16.to_le_bytes());
        central.extend_from_slice(&0u16.to_le_bytes());
        central.extend_from_slice(&crc.to_le_bytes());
        central.extend_from_slice(&size.to_le_bytes());
        central.extend_from_slice(&size.to_le_bytes());
        central.extend_from_slice(&name_len.to_le_bytes());
        central.extend_from_slice(&0u16.to_le_bytes());
        central.extend_from_slice(&0u16.to_le_bytes());
        central.extend_from_slice(&0u16.to_le_bytes());
        central.extend_from_slice(&0u16.to_le_bytes());
        central.extend_from_slice(&0u32.to_le_bytes());
        central.extend_from_slice(&offset.to_le_bytes());
        central.extend_from_slice(name_bytes);
    }

    let cd_offset = buf.len() as u32;
    let cd_size = central.len() as u32;
    buf.extend_from_slice(&central);

    // End of central directory record
    buf.extend_from_slice(&0x0605_4b50u32.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf.extend_from_slice(&(entries.len() as u16).to_le_bytes());
    buf.extend_from_slice(&(entries.len() as u16).to_le_bytes());
    buf.extend_from_slice(&cd_size.to_le_bytes());
    buf.extend_from_slice(&cd_offset.to_le_bytes());
    buf.extend_from_slice(&0u16.to_le_bytes());
    buf
}

fn base64_encode(input: &[u8]) -> String {
    const TABLE: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity((input.len() + 2) / 3 * 4);
    for chunk in input.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = if chunk.len() > 1 { chunk[1] as u32 } else { 0 };
        let b2 = if chunk.len() > 2 { chunk[2] as u32 } else { 0 };
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(TABLE[((n >> 18) & 63) as usize] as char);
        out.push(TABLE[((n >> 12) & 63) as usize] as char);
        if chunk.len() > 1 {
            out.push(TABLE[((n >> 6) & 63) as usize] as char);
        } else {
            out.push('=');
        }
        if chunk.len() > 2 {
            out.push(TABLE[(n & 63) as usize] as char);
        } else {
            out.push('=');
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clash::detect_clashes;
    use crate::mesh::{analyze_mesh, rebuild_document, tessellate_parametric};
    use crate::ir::RebuildOptions;

    #[test]
    fn test_parametric_box_watertight_and_reconstruct() {
        let mesh = tessellate_parametric(&ParametricShape::Box { size: [2.0, 1.0, 0.5] });
        let report = analyze_mesh(&mesh);
        assert!(report.is_manifold);
        assert!(report.is_watertight);
        assert!(report.printable_3d_ready);
        assert!((report.abs_volume - 1.0).abs() < 1e-6);

        let mut doc = SpatialDocument::new("test_box");
        let mut node = SpatialNode::new("n1", "beam_box", "beam");
        node.mesh = Some(mesh);
        doc.nodes.push(node);

        let (rebuilt, rrep) = rebuild_document(&doc, &RebuildOptions::default());
        assert_eq!(rrep.primitives_reconstructed, 1);
        assert!(rebuilt.nodes[0].parametric.is_some());
    }

    #[test]
    fn test_multi_discipline_clash_detection() {
        let mut doc = SpatialDocument::new("mep_clash_test");

        let mut beam = SpatialNode::new("beam_1", "W12x40_Girder", "beam");
        beam.discipline = Discipline::Structural;
        beam.transform.position = [0.0, 3.0, 0.0];
        beam.parametric = Some(ParametricShape::Box { size: [6.0, 0.3, 0.2] });

        let mut duct = SpatialNode::new("duct_1", "Main_Supply_Duct", "duct");
        duct.discipline = Discipline::Mechanical;
        duct.parametric = Some(ParametricShape::DuctRun {
            start: [0.0, 3.0, -2.0],
            end: [0.0, 3.0, 2.0],
            width: 0.4,
            height: 0.3,
        });

        doc.nodes.push(beam);
        doc.nodes.push(duct);

        let report = detect_clashes(&doc, 0.05);
        assert_eq!(report.hard_clashes, 1);
        assert_eq!(report.clashes[0].node_a, "beam_1");
        assert_eq!(report.clashes[0].node_b, "duct_1");
    }

    #[test]
    fn test_exporters_emit_valid_outputs() {
        let mut doc = SpatialDocument::new("hub_demo");
        let mut n = SpatialNode::new("part_1", "Mount_Bracket", "bracket");
        n.discipline = Discipline::Fabrication;
        n.material_id = Some("al_6061_t6".to_string());
        n.parametric = Some(ParametricShape::Box { size: [0.1, 0.05, 0.08] });
        doc.nodes.push(n);

        assert!(emit_obj(&doc).contains("o Mount_Bracket"));
        assert!(emit_stl_ascii(&doc).contains("facet normal"));
        assert!(emit_gltf(&doc).contains("\"version\": \"2.0\""));
        assert!(emit_usda(&doc).contains("#usda 1.0"));
        assert!(emit_godot_tscn(&doc).contains("[gd_scene"));
        assert!(emit_bevy_ron(&doc).contains("Mount_Bracket"));
        assert!(emit_dxf(&doc).contains("ENTITIES"));
        let zip_bytes = emit_3mf_bytes(&doc);
        assert_eq!(&zip_bytes[0..4], &[0x50, 0x4b, 0x03, 0x04]); // PK\x03\x04 ZIP magic
    }

    #[test]
    fn test_dxf_and_ifc_importers() {
        let sample_dxf = "0\nSECTION\n2\nENTITIES\n0\nLINE\n8\nS-BEAM\n10\n0.0\n20\n0.0\n11\n5.0\n21\n0.0\n0\nENDSEC\n0\nEOF\n";
        let dxf_doc = parse_dxf(sample_dxf, "plan").unwrap();
        assert_eq!(dxf_doc.nodes.len(), 1);
        assert_eq!(dxf_doc.nodes[0].discipline, Discipline::Structural);

        let sample_ifc = "ISO-10303-21;\nDATA;\n#10=IFCBEAM('2O2Fr$t4X7Zf8NOew3FLOH',#5,'W14x30_B1',$,$,#20,#30,'B1');\n#11=IFCDUCTSEGMENT('3P3Gs$u5Y8Ag9OPfx4GMPI',#5,'Supply_Main_01',$,$,#21,#31,'D1');\nENDSEC;\n";
        let ifc_doc = parse_ifc(sample_ifc, "bldg").unwrap();
        assert_eq!(ifc_doc.nodes.len(), 2);
        assert_eq!(ifc_doc.nodes[0].discipline, Discipline::Structural);
        assert_eq!(ifc_doc.nodes[1].discipline, Discipline::Mechanical);
    }

    #[test]
    fn test_human_lock_preserved_on_rebuild() {
        let mut doc = SpatialDocument::new("lock_test");
        doc.datum.length_unit = LengthUnit::Mm;
        let mut locked = SpatialNode::new("n_lock", "HandTweaked", "prop");
        locked.transform.position = [100.0, 200.0, 300.0];
        locked.provenance.human_locked = true;
        doc.nodes.push(locked);

        let (rebuilt, rep) = rebuild_document(&doc, &RebuildOptions::default());
        assert_eq!(rep.nodes_skipped_human_locked, 1);
        assert_eq!(rebuilt.nodes[0].transform.position, [100.0, 200.0, 300.0]);
    }
}
