//! WebAssembly-compatible pure-memory entrypoints for OpenDatum Spatial Core.
//! Enables zero-upload client-side OBJ/STL/DXF/IFC inspection, legacy rebuild,
//! multi-discipline clash detection, and Godot/Bevy/glTF/USD/3MF export in browsers & WebMCP.

use opendatum_core::adapters::{
    emit_3mf_bytes, emit_bevy_ron, emit_dxf, emit_gltf, emit_godot_tscn, emit_obj, emit_stl_ascii,
    emit_usda, parse_dxf, parse_ifc, parse_obj, parse_stl,
};
use opendatum_core::{
    detect_clashes, merge_documents, rebuild_document, LengthUnit, RebuildOptions, SpatialDocument,
    UpAxis,
};

/// Parses an in-memory text format (`usir`, `obj`, `dxf`, `ifc`) and returns a compact USIR JSON summary.
pub fn inspect_text_asset(format: &str, name: &str, content: &str) -> Result<String, String> {
    let doc = parse_text_doc(format, name, content)?;
    serde_json::to_string_pretty(&doc.compact_summary()).map_err(|e| e.to_string())
}

/// Rebuilds an in-memory legacy asset into normalized USIR JSON + RebuildReport.
pub fn rebuild_text_asset(
    format: &str,
    name: &str,
    content: &str,
    target_unit: &str,
    target_up: &str,
) -> Result<String, String> {
    let doc = parse_text_doc(format, name, content)?;
    let opts = RebuildOptions {
        target_unit: LengthUnit::from_str_loose(target_unit).unwrap_or(LengthUnit::M),
        target_up: UpAxis::from_str_loose(target_up).unwrap_or(UpAxis::Y),
        ..RebuildOptions::default()
    };
    let (rebuilt, report) = rebuild_document(&doc, &opts);
    serde_json::to_string_pretty(&serde_json::json!({
        "document": rebuilt,
        "report": report,
    }))
    .map_err(|e| e.to_string())
}

/// Converts a USIR JSON string to any text-based target format (`obj`, `stl`, `gltf`, `usd`, `godot`, `bevy`, `dxf`).
pub fn export_usir_to_text(usir_json: &str, target: &str) -> Result<String, String> {
    let doc: SpatialDocument =
        serde_json::from_str(usir_json).map_err(|e| format!("Invalid USIR JSON: {}", e))?;
    match target.trim().to_ascii_lowercase().as_str() {
        "usir" | "json" => serde_json::to_string_pretty(&doc).map_err(|e| e.to_string()),
        "obj" => Ok(emit_obj(&doc)),
        "stl" => Ok(emit_stl_ascii(&doc)),
        "gltf" => Ok(emit_gltf(&doc)),
        "usd" | "usda" => Ok(emit_usda(&doc)),
        "godot" | "tscn" => Ok(emit_godot_tscn(&doc)),
        "bevy" | "ron" => Ok(emit_bevy_ron(&doc)),
        "dxf" => Ok(emit_dxf(&doc)),
        other => Err(format!("Unsupported text export target: {}", other)),
    }
}

/// Exports a USIR JSON string to raw 3MF ZIP bytes in memory.
pub fn export_usir_to_3mf_bytes(usir_json: &str) -> Result<Vec<u8>, String> {
    let doc: SpatialDocument =
        serde_json::from_str(usir_json).map_err(|e| format!("Invalid USIR JSON: {}", e))?;
    Ok(emit_3mf_bytes(&doc))
}

/// Parses binary or ASCII STL bytes in memory into USIR JSON.
pub fn import_stl_bytes_to_usir(name: &str, bytes: &[u8]) -> Result<String, String> {
    let doc = parse_stl(bytes, name)?;
    serde_json::to_string_pretty(&doc).map_err(|e| e.to_string())
}

/// Runs multi-discipline 3D clash detection on an in-memory USIR JSON string.
pub fn analyze_clashes_usir(usir_json: &str, min_clearance: f64) -> Result<String, String> {
    let doc: SpatialDocument =
        serde_json::from_str(usir_json).map_err(|e| format!("Invalid USIR JSON: {}", e))?;
    let report = detect_clashes(&doc, min_clearance);
    serde_json::to_string_pretty(&report).map_err(|e| e.to_string())
}

/// Human-lock-safe merge of two USIR JSON strings in memory.
pub fn merge_usir_json(human_json: &str, agent_json: &str) -> Result<String, String> {
    let human: SpatialDocument =
        serde_json::from_str(human_json).map_err(|e| format!("Invalid human USIR JSON: {}", e))?;
    let agent: SpatialDocument =
        serde_json::from_str(agent_json).map_err(|e| format!("Invalid agent USIR JSON: {}", e))?;
    let (merged, report) = merge_documents(&human, &agent);
    serde_json::to_string_pretty(&serde_json::json!({
        "document": merged,
        "report": report,
    }))
    .map_err(|e| e.to_string())
}

fn parse_text_doc(format: &str, name: &str, content: &str) -> Result<SpatialDocument, String> {
    match format.trim().to_ascii_lowercase().as_str() {
        "usir" | "odir" | "json" => {
            serde_json::from_str(content).map_err(|e| format!("Invalid USIR JSON: {}", e))
        }
        "obj" => parse_obj(content, name),
        "dxf" => parse_dxf(content, name),
        "ifc" => parse_ifc(content, name),
        other => Err(format!("Unsupported text import format: {}", other)),
    }
}

// ============================================================================
// C-ABI WASM EXPORTS (Zero wasm-bindgen dependency, callable from any JS/WASI host)
// ============================================================================

/// Allocates a linear-memory buffer inside the WASM module for host-to-guest string transfer.
#[no_mangle]
pub extern "C" fn opendatum_alloc(len: usize) -> *mut u8 {
    let mut buf = Vec::<u8>::with_capacity(len);
    let ptr = buf.as_mut_ptr();
    std::mem::forget(buf);
    ptr
}

/// Frees a buffer previously allocated by `opendatum_alloc`.
#[no_mangle]
pub unsafe extern "C" fn opendatum_dealloc(ptr: *mut u8, len: usize) {
    if !ptr.is_null() {
        let _ = Vec::from_raw_parts(ptr, 0, len);
    }
}

/// Inspects a UTF-8 USIR JSON buffer and returns the number of nodes (or -1 on parse error).
#[no_mangle]
pub unsafe extern "C" fn opendatum_usir_node_count(ptr: *const u8, len: usize) -> i32 {
    if ptr.is_null() {
        return -1;
    }
    let slice = std::slice::from_raw_parts(ptr, len);
    let Ok(text) = std::str::from_utf8(slice) else {
        return -1;
    };
    let Ok(doc) = serde_json::from_str::<SpatialDocument>(text) else {
        return -1;
    };
    doc.nodes.len() as i32
}

/// Runs multi-discipline 3D clash detection on a UTF-8 USIR JSON buffer and returns hard clash count (-1 on error).
#[no_mangle]
pub unsafe extern "C" fn opendatum_usir_hard_clashes(
    ptr: *const u8,
    len: usize,
    min_clearance: f64,
) -> i32 {
    if ptr.is_null() {
        return -1;
    }
    let slice = std::slice::from_raw_parts(ptr, len);
    let Ok(text) = std::str::from_utf8(slice) else {
        return -1;
    };
    let Ok(doc) = serde_json::from_str::<SpatialDocument>(text) else {
        return -1;
    };
    detect_clashes(&doc, min_clearance).hard_clashes as i32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_wasm_api_end_to_end() {
        let obj = "o Cube\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nv 0 0 1\nv 1 0 1\nv 1 1 1\nv 0 1 1\nf 1 3 2\nf 1 4 3\nf 5 6 7\nf 5 7 8\nf 1 2 6\nf 1 6 5\nf 4 8 7\nf 4 7 3\nf 1 5 8\nf 1 8 4\nf 2 3 7\nf 2 7 6\n";
        let summary = inspect_text_asset("obj", "cube", obj).unwrap();
        assert!(summary.contains("\"node_count\": 1"));
        let rebuilt = rebuild_text_asset("obj", "cube", obj, "m", "y").unwrap();
        let val: serde_json::Value = serde_json::from_str(&rebuilt).unwrap();
        let doc_str = serde_json::to_string(&val["document"]).unwrap();
        let tscn = export_usir_to_text(&doc_str, "godot").unwrap();
        assert!(tscn.contains("[gd_scene"));
        let bytes = export_usir_to_3mf_bytes(&doc_str).unwrap();
        assert_eq!(&bytes[0..2], b"PK");
    }
}
