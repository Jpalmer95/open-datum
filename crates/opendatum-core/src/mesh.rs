use crate::ir::{
    LengthUnit, MeshData, MeshQualityReport, ParametricShape, RebuildOptions, RebuildReport,
    SpatialDocument, UpAxis,
};
use std::collections::{HashMap, HashSet};
use std::f64::consts::PI;

fn sub(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}

fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

fn norm(a: [f64; 3]) -> f64 {
    dot(a, a).sqrt()
}

fn normalize(a: [f64; 3]) -> [f64; 3] {
    let l = norm(a);
    if l > 1e-12 {
        [a[0] / l, a[1] / l, a[2] / l]
    } else {
        [0.0, 1.0, 0.0]
    }
}

/// Computes comprehensive geometry, manifoldness, 3D-printability, and physical-volume metrics.
pub fn analyze_mesh(mesh: &MeshData) -> MeshQualityReport {
    let mut aabb_min = [f64::INFINITY; 3];
    let mut aabb_max = [f64::NEG_INFINITY; 3];

    for v in &mesh.vertices {
        for i in 0..3 {
            if v[i] < aabb_min[i] {
                aabb_min[i] = v[i];
            }
            if v[i] > aabb_max[i] {
                aabb_max[i] = v[i];
            }
        }
    }

    if mesh.vertices.is_empty() {
        aabb_min = [0.0; 3];
        aabb_max = [0.0; 3];
    }

    let dimensions = [
        aabb_max[0] - aabb_min[0],
        aabb_max[1] - aabb_min[1],
        aabb_max[2] - aabb_min[2],
    ];

    let mut edge_counts: HashMap<(u32, u32), usize> = HashMap::new();
    let mut degenerate_triangles = 0usize;
    let mut surface_area = 0.0f64;
    let mut signed_volume = 0.0f64;
    let mut centroid_accum = [0.0f64; 3];
    let mut weight_sum = 0.0f64;

    for tri in &mesh.indices {
        let (i0, i1, i2) = (tri[0] as usize, tri[1] as usize, tri[2] as usize);
        if i0 >= mesh.vertices.len() || i1 >= mesh.vertices.len() || i2 >= mesh.vertices.len() {
            degenerate_triangles += 1;
            continue;
        }
        if i0 == i1 || i1 == i2 || i2 == i0 {
            degenerate_triangles += 1;
            continue;
        }

        let v0 = mesh.vertices[i0];
        let v1 = mesh.vertices[i1];
        let v2 = mesh.vertices[i2];

        let c = cross(sub(v1, v0), sub(v2, v0));
        let area = 0.5 * norm(c);
        if area < 1e-12 {
            degenerate_triangles += 1;
            continue;
        }
        surface_area += area;
        let vol6 = dot(v0, cross(v1, v2));
        signed_volume += vol6 / 6.0;

        let tri_center = [
            (v0[0] + v1[0] + v2[0]) / 3.0,
            (v0[1] + v1[1] + v2[1]) / 3.0,
            (v0[2] + v1[2] + v2[2]) / 3.0,
        ];
        for k in 0..3 {
            centroid_accum[k] += tri_center[k] * area;
        }
        weight_sum += area;

        for (a, b) in [(tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])] {
            let key = if a < b { (a, b) } else { (b, a) };
            *edge_counts.entry(key).or_insert(0) += 1;
        }
    }

    let mut boundary_edges = 0usize;
    let mut non_manifold_edges = 0usize;
    for &count in edge_counts.values() {
        if count == 1 {
            boundary_edges += 1;
        } else if count > 2 {
            non_manifold_edges += 1;
        }
    }

    let is_manifold = non_manifold_edges == 0 && !mesh.indices.is_empty();
    let is_watertight = is_manifold && boundary_edges == 0;
    let abs_volume = signed_volume.abs();

    let mut warnings = Vec::new();
    if degenerate_triangles > 0 {
        warnings.push(format!(
            "Contains {} degenerate or zero-area triangles",
            degenerate_triangles
        ));
    }
    if boundary_edges > 0 {
        warnings.push(format!(
            "Mesh is open ({} boundary edges) — not watertight for 3D printing or volumetric FEA",
            boundary_edges
        ));
    }
    if non_manifold_edges > 0 {
        warnings.push(format!(
            "Contains {} non-manifold edges (shared by >2 faces)",
            non_manifold_edges
        ));
    }
    if signed_volume < 0.0 && is_watertight {
        warnings.push("Negative signed volume detected (inverted triangle winding)".to_string());
    }

    let printable_3d_ready =
        is_watertight && degenerate_triangles == 0 && abs_volume > 1e-12;

    let centroid = if weight_sum > 1e-12 {
        [
            centroid_accum[0] / weight_sum,
            centroid_accum[1] / weight_sum,
            centroid_accum[2] / weight_sum,
        ]
    } else {
        [
            0.5 * (aabb_min[0] + aabb_max[0]),
            0.5 * (aabb_min[1] + aabb_max[1]),
            0.5 * (aabb_min[2] + aabb_max[2]),
        ]
    };

    MeshQualityReport {
        vertex_count: mesh.vertices.len(),
        triangle_count: mesh.indices.len(),
        degenerate_triangles,
        boundary_edges,
        non_manifold_edges,
        is_manifold,
        is_watertight,
        printable_3d_ready,
        aabb_min,
        aabb_max,
        dimensions,
        surface_area,
        signed_volume,
        abs_volume,
        centroid,
        warnings,
    }
}

/// Cleans a messy legacy mesh: welds duplicate vertices within `weld_tol`, removes degenerate/duplicate
/// triangles, flips winding if negative signed volume on a closed shell, and recomputes smooth normals.
pub fn clean_mesh(mesh: &MeshData, weld_tol: f64) -> (MeshData, usize) {
    let tol = weld_tol.max(1e-9);
    let mut cell_to_idx: HashMap<(i64, i64, i64), u32> = HashMap::new();
    let mut new_verts: Vec<[f64; 3]> = Vec::new();
    let mut remap: Vec<u32> = Vec::with_capacity(mesh.vertices.len());

    for v in &mesh.vertices {
        let key = (
            (v[0] / tol).round() as i64,
            (v[1] / tol).round() as i64,
            (v[2] / tol).round() as i64,
        );
        let idx = *cell_to_idx.entry(key).or_insert_with(|| {
            let id = new_verts.len() as u32;
            new_verts.push(*v);
            id
        });
        remap.push(idx);
    }

    let mut seen_tris: HashSet<(u32, u32, u32)> = HashSet::new();
    let mut new_indices: Vec<[u32; 3]> = Vec::new();
    let mut degenerate_removed = 0usize;

    for tri in &mesh.indices {
        let (o0, o1, o2) = (tri[0] as usize, tri[1] as usize, tri[2] as usize);
        if o0 >= remap.len() || o1 >= remap.len() || o2 >= remap.len() {
            degenerate_removed += 1;
            continue;
        }
        let a = remap[o0];
        let b = remap[o1];
        let c = remap[o2];
        if a == b || b == c || c == a {
            degenerate_removed += 1;
            continue;
        }
        let v0 = new_verts[a as usize];
        let v1 = new_verts[b as usize];
        let v2 = new_verts[c as usize];
        let area = 0.5 * norm(cross(sub(v1, v0), sub(v2, v0)));
        if area < 1e-12 {
            degenerate_removed += 1;
            continue;
        }
        let mut sorted = [a, b, c];
        sorted.sort_unstable();
        if !seen_tris.insert((sorted[0], sorted[1], sorted[2])) {
            degenerate_removed += 1;
            continue;
        }
        new_indices.push([a, b, c]);
    }

    let mut cleaned = MeshData {
        vertices: new_verts,
        indices: new_indices,
        normals: Vec::new(),
    };

    // Fix inverted winding if closed shell has negative signed volume.
    let report = analyze_mesh(&cleaned);
    if report.is_watertight && report.signed_volume < 0.0 {
        for tri in &mut cleaned.indices {
            tri.swap(1, 2);
        }
    }

    recompute_normals(&mut cleaned);
    (cleaned, degenerate_removed)
}

pub fn recompute_normals(mesh: &mut MeshData) {
    let mut accum = vec![[0.0f64; 3]; mesh.vertices.len()];
    for tri in &mesh.indices {
        let (a, b, c) = (tri[0] as usize, tri[1] as usize, tri[2] as usize);
        if a >= mesh.vertices.len() || b >= mesh.vertices.len() || c >= mesh.vertices.len() {
            continue;
        }
        let n = cross(
            sub(mesh.vertices[b], mesh.vertices[a]),
            sub(mesh.vertices[c], mesh.vertices[a]),
        );
        for &idx in &[a, b, c] {
            accum[idx][0] += n[0];
            accum[idx][1] += n[1];
            accum[idx][2] += n[2];
        }
    }
    mesh.normals = accum.into_iter().map(normalize).collect();
}

/// Attempts to recognize an axis-aligned box primitive from a clean closed mesh.
/// If the mesh's volume matches its AABB volume within 2% and all vertices lie on the AABB boundary,
/// returns `Some((Box, center_offset))` for dramatic semantic compression.
pub fn try_reconstruct_box(mesh: &MeshData) -> Option<(ParametricShape, [f64; 3])> {
    if mesh.vertices.len() < 8 || mesh.indices.len() < 12 {
        return None;
    }
    let report = analyze_mesh(mesh);
    if !report.is_watertight || report.abs_volume < 1e-12 {
        return None;
    }
    let [dx, dy, dz] = report.dimensions;
    let aabb_vol = dx * dy * dz;
    if aabb_vol < 1e-12 {
        return None;
    }
    let vol_ratio = report.abs_volume / aabb_vol;
    if (vol_ratio - 1.0).abs() > 0.02 {
        return None;
    }
    let eps = (dx.max(dy).max(dz)) * 0.005 + 1e-6;
    for v in &mesh.vertices {
        let on_x = (v[0] - report.aabb_min[0]).abs() <= eps
            || (v[0] - report.aabb_max[0]).abs() <= eps;
        let on_y = (v[1] - report.aabb_min[1]).abs() <= eps
            || (v[1] - report.aabb_max[1]).abs() <= eps;
        let on_z = (v[2] - report.aabb_min[2]).abs() <= eps
            || (v[2] - report.aabb_max[2]).abs() <= eps;
        if !(on_x || on_y || on_z) {
            return None;
        }
    }

    let center = [
        0.5 * (report.aabb_min[0] + report.aabb_max[0]),
        0.5 * (report.aabb_min[1] + report.aabb_max[1]),
        0.5 * (report.aabb_min[2] + report.aabb_max[2]),
    ];
    Some((ParametricShape::Box { size: [dx, dy, dz] }, center))
}

/// Tessellates any `ParametricShape` into a clean, watertight, outward-oriented triangle mesh.
pub fn tessellate_parametric(shape: &ParametricShape) -> MeshData {
    let mut mesh = match shape {
        ParametricShape::Box { size } => build_box_mesh(size[0], size[1], size[2]),
        ParametricShape::Cylinder {
            radius,
            height,
            segments,
        } => build_cylinder_mesh(*radius, *height, (*segments).max(8)),
        ParametricShape::PipeRun {
            start,
            end,
            outer_diameter,
            ..
        } => {
            let dir = sub(*end, *start);
            let len = norm(dir).max(1e-4);
            let mut m = build_cylinder_mesh(outer_diameter * 0.5, len, 16);
            orient_and_translate_cylinder(&mut m, *start, *end);
            m
        }
        ParametricShape::DuctRun {
            start,
            end,
            width,
            height,
        } => {
            let dir = sub(*end, *start);
            let len = norm(dir).max(1e-4);
            let mut m = build_box_mesh(*width, len, *height);
            orient_and_translate_cylinder(&mut m, *start, *end);
            m
        }
        ParametricShape::ExtrudedPolygon { footprint, height } => {
            build_extruded_polygon(footprint, *height)
        }
        ParametricShape::LineSegment2D { start, end, .. } => {
            let dx = end[0] - start[0];
            let dy = end[1] - start[1];
            let len = (dx * dx + dy * dy).sqrt().max(1e-4);
            let mut m = build_box_mesh(len, 0.02, 0.02);
            let mid = [0.5 * (start[0] + end[0]), 0.5 * (start[1] + end[1]), 0.0];
            let angle = dy.atan2(dx);
            let (s, c) = angle.sin_cos();
            for v in &mut m.vertices {
                let rx = v[0] * c - v[1] * s;
                let ry = v[0] * s + v[1] * c;
                v[0] = rx + mid[0];
                v[1] = ry + mid[1];
                v[2] += mid[2];
            }
            m
        }
    };
    recompute_normals(&mut mesh);
    mesh
}

fn build_box_mesh(sx: f64, sy: f64, sz: f64) -> MeshData {
    let hx = sx * 0.5;
    let hy = sy * 0.5;
    let hz = sz * 0.5;
    let vertices = vec![
        [-hx, -hy, -hz],
        [hx, -hy, -hz],
        [hx, hy, -hz],
        [-hx, hy, -hz],
        [-hx, -hy, hz],
        [hx, -hy, hz],
        [hx, hy, hz],
        [-hx, hy, hz],
    ];
    let indices = vec![
        // -Z
        [0, 2, 1],
        [0, 3, 2],
        // +Z
        [4, 5, 6],
        [4, 6, 7],
        // -Y
        [0, 1, 5],
        [0, 5, 4],
        // +Y
        [3, 7, 6],
        [3, 6, 2],
        // -X
        [0, 4, 7],
        [0, 7, 3],
        // +X
        [1, 2, 6],
        [1, 6, 5],
    ];
    MeshData {
        vertices,
        indices,
        normals: Vec::new(),
    }
}

fn build_cylinder_mesh(radius: f64, height: f64, segments: u32) -> MeshData {
    let hy = height * 0.5;
    let mut vertices = Vec::with_capacity((segments * 2 + 2) as usize);
    let mut indices = Vec::with_capacity((segments * 4) as usize);

    // Bottom center (0) and top center (1)
    vertices.push([0.0, -hy, 0.0]);
    vertices.push([0.0, hy, 0.0]);

    for i in 0..segments {
        let theta = 2.0 * PI * (i as f64) / (segments as f64);
        let x = radius * theta.cos();
        let z = radius * theta.sin();
        vertices.push([x, -hy, z]); // bottom ring: 2 + 2*i
        vertices.push([x, hy, z]); // top ring: 2 + 2*i + 1
    }

    for i in 0..segments {
        let next = (i + 1) % segments;
        let b0 = 2 + 2 * i;
        let t0 = b0 + 1;
        let b1 = 2 + 2 * next;
        let t1 = b1 + 1;

        // Side quad (outward winding)
        indices.push([b0, t0, t1]);
        indices.push([b0, t1, b1]);
        // Bottom cap (-Y)
        indices.push([0, b0, b1]);
        // Top cap (+Y)
        indices.push([1, t1, t0]);
    }

    MeshData {
        vertices,
        indices,
        normals: Vec::new(),
    }
}

fn orient_and_translate_cylinder(mesh: &mut MeshData, start: [f64; 3], end: [f64; 3]) {
    let dir = normalize(sub(end, start));
    let mid = [
        0.5 * (start[0] + end[0]),
        0.5 * (start[1] + end[1]),
        0.5 * (start[2] + end[2]),
    ];
    // Orthonormal basis where local +Y maps to `dir`.
    let ref_vec = if dir[1].abs() < 0.9 {
        [0.0, 1.0, 0.0]
    } else {
        [1.0, 0.0, 0.0]
    };
    let right = normalize(cross(ref_vec, dir));
    let forward = normalize(cross(dir, right));

    for v in &mut mesh.vertices {
        let x = v[0] * right[0] + v[1] * dir[0] + v[2] * forward[0] + mid[0];
        let y = v[0] * right[1] + v[1] * dir[1] + v[2] * forward[1] + mid[1];
        let z = v[0] * right[2] + v[1] * dir[2] + v[2] * forward[2] + mid[2];
        *v = [x, y, z];
    }
}

fn build_extruded_polygon(footprint: &[[f64; 2]], height: f64) -> MeshData {
    if footprint.len() < 3 {
        return build_box_mesh(1.0, height.max(0.1), 1.0);
    }
    let n = footprint.len();
    let mut cx = 0.0;
    let mut cz = 0.0;
    for p in footprint {
        cx += p[0];
        cz += p[1];
    }
    cx /= n as f64;
    cz /= n as f64;

    let mut vertices = Vec::with_capacity(n * 2 + 2);
    vertices.push([cx, 0.0, cz]);
    vertices.push([cx, height, cz]);
    for p in footprint {
        vertices.push([p[0], 0.0, p[1]]);
        vertices.push([p[0], height, p[1]]);
    }

    let mut indices = Vec::new();
    for i in 0..n {
        let next = (i + 1) % n;
        let b0 = (2 + 2 * i) as u32;
        let t0 = b0 + 1;
        let b1 = (2 + 2 * next) as u32;
        let t1 = b1 + 1;
        indices.push([b0, t0, t1]);
        indices.push([b0, t1, b1]);
        indices.push([0, b0, b1]);
        indices.push([1, t1, t0]);
    }
    MeshData {
        vertices,
        indices,
        normals: Vec::new(),
    }
}

fn remap_vec_axis(v: [f64; 3], from: UpAxis, to: UpAxis) -> [f64; 3] {
    match (from, to) {
        (UpAxis::Z, UpAxis::Y) => [v[0], v[2], -v[1]],
        (UpAxis::Y, UpAxis::Z) => [v[0], -v[2], v[1]],
        _ => v,
    }
}

fn scale_vec(v: [f64; 3], s: f64) -> [f64; 3] {
    [v[0] * s, v[1] * s, v[2] * s]
}

/// Rebuilds and modernizes an entire `SpatialDocument`:
/// - Scales units cleanly into `options.target_unit`
/// - Remaps coordinate up-axis (`Z-up` <-> `Y-up`)
/// - Cleans messy meshes (weld, cull degenerates, fix winding, recompute normals)
/// - Reconstructs concise parametric shapes where possible
/// - Preserves nodes marked `human_locked = true` untouched!
pub fn rebuild_document(doc: &SpatialDocument, options: &RebuildOptions) -> (SpatialDocument, RebuildReport) {
    let mut out = doc.clone();
    let unit_scale = doc.datum.length_unit.to_meters() / options.target_unit.to_meters();
    let axis_remapped = doc.datum.up_axis != options.target_up;
    let from_up = doc.datum.up_axis;
    let to_up = options.target_up;

    out.datum.length_unit = options.target_unit;
    out.datum.up_axis = options.target_up;
    out.datum.gravity_m_s2 = remap_vec_axis(doc.datum.gravity_m_s2, from_up, to_up);

    let mut report = RebuildReport {
        nodes_processed: 0,
        nodes_skipped_human_locked: 0,
        vertices_before: 0,
        vertices_after: 0,
        triangles_before: 0,
        triangles_after: 0,
        degenerate_removed: 0,
        primitives_reconstructed: 0,
        unit_scale_applied: unit_scale,
        axis_remapped,
    };

    for node in &mut out.nodes {
        if node.provenance.human_locked {
            report.nodes_skipped_human_locked += 1;
            continue;
        }
        report.nodes_processed += 1;

        node.transform.position = scale_vec(
            remap_vec_axis(node.transform.position, from_up, to_up),
            unit_scale,
        );

        for port in &mut node.ports {
            port.position = scale_vec(remap_vec_axis(port.position, from_up, to_up), unit_scale);
            port.direction = remap_vec_axis(port.direction, from_up, to_up);
        }

        // Transform parametric shapes if present.
        if let Some(shape) = &mut node.parametric {
            match shape {
                ParametricShape::Box { size } => {
                    let remapped = remap_vec_axis(*size, from_up, to_up);
                    *size = [
                        remapped[0].abs() * unit_scale,
                        remapped[1].abs() * unit_scale,
                        remapped[2].abs() * unit_scale,
                    ];
                }
                ParametricShape::Cylinder { radius, height, .. } => {
                    *radius *= unit_scale;
                    *height *= unit_scale;
                }
                ParametricShape::PipeRun {
                    start,
                    end,
                    outer_diameter,
                    wall_thickness,
                } => {
                    *start = scale_vec(remap_vec_axis(*start, from_up, to_up), unit_scale);
                    *end = scale_vec(remap_vec_axis(*end, from_up, to_up), unit_scale);
                    *outer_diameter *= unit_scale;
                    *wall_thickness *= unit_scale;
                }
                ParametricShape::DuctRun {
                    start,
                    end,
                    width,
                    height,
                } => {
                    *start = scale_vec(remap_vec_axis(*start, from_up, to_up), unit_scale);
                    *end = scale_vec(remap_vec_axis(*end, from_up, to_up), unit_scale);
                    *width *= unit_scale;
                    *height *= unit_scale;
                }
                ParametricShape::ExtrudedPolygon { footprint, height } => {
                    for p in footprint.iter_mut() {
                        p[0] *= unit_scale;
                        p[1] *= unit_scale;
                    }
                    *height *= unit_scale;
                }
                ParametricShape::LineSegment2D { start, end, .. } => {
                    start[0] *= unit_scale;
                    start[1] *= unit_scale;
                    end[0] *= unit_scale;
                    end[1] *= unit_scale;
                }
            }
        }

        if let Some(mesh) = &mut node.mesh {
            report.vertices_before += mesh.vertices.len();
            report.triangles_before += mesh.indices.len();

            for v in &mut mesh.vertices {
                *v = scale_vec(remap_vec_axis(*v, from_up, to_up), unit_scale);
            }

            let (cleaned, deg) = clean_mesh(mesh, options.weld_tolerance);
            report.degenerate_removed += deg;
            *mesh = cleaned;

            if options.reconstruct_primitives && node.parametric.is_none() {
                if let Some((box_shape, center)) = try_reconstruct_box(mesh) {
                    node.parametric = Some(box_shape);
                    // Re-center node mesh around origin and shift transform by center.
                    for i in 0..3 {
                        node.transform.position[i] += center[i];
                    }
                    for v in &mut mesh.vertices {
                        v[0] -= center[0];
                        v[1] -= center[1];
                        v[2] -= center[2];
                    }
                    report.primitives_reconstructed += 1;
                }
            }

            if options.strip_redundant_mesh_when_parametric && node.parametric.is_some() {
                node.mesh = None;
            } else {
                report.vertices_after += mesh.vertices.len();
                report.triangles_after += mesh.indices.len();
            }
        }
    }

    (out, report)
}

/// Ensures every node with a `ParametricShape` has a tessellated mesh for mesh-only export targets.
pub fn resolve_node_mesh(node: &crate::ir::SpatialNode) -> Option<MeshData> {
    if let Some(m) = &node.mesh {
        if !m.vertices.is_empty() && !m.indices.is_empty() {
            return Some(m.clone());
        }
    }
    node.parametric.as_ref().map(tessellate_parametric)
}

/// Computes world-space AABB for a node (accounting for position & scale).
pub fn node_world_aabb(node: &crate::ir::SpatialNode) -> Option<([f64; 3], [f64; 3])> {
    let mesh = resolve_node_mesh(node)?;
    if mesh.vertices.is_empty() {
        return None;
    }
    let mut mn = [f64::INFINITY; 3];
    let mut mx = [f64::NEG_INFINITY; 3];
    for v in &mesh.vertices {
        for i in 0..3 {
            let w = v[i] * node.transform.scale[i] + node.transform.position[i];
            if w < mn[i] {
                mn[i] = w;
            }
            if w > mx[i] {
                mx[i] = w;
            }
        }
    }
    Some((mn, mx))
}

#[allow(dead_code)]
fn _unit_to_m(u: LengthUnit) -> f64 {
    u.to_meters()
}
