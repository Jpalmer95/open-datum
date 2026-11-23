use opendatum_core::{
    analyze_mesh, detect_clashes, export_document, import_document, rebuild_document,
    LengthUnit, RebuildOptions, SpatialFormat, UpAxis,
};
use std::env;
use std::path::PathBuf;
use std::process;

fn print_usage() {
    eprintln!(
        "odatum — OpenDatum Universal Spatial Hub CLI (v0.1.0)\n\
         \n\
         USAGE:\n\
         \todatum inspect <input_file>\n\
         \todatum convert <input_file> <output_file> [--target usir|obj|stl|3mf|gltf|usd|godot|bevy|dxf]\n\
         \todatum rebuild <input_file> <output_file> [--units m|mm|ft|in] [--up y|z] [--weld 1e-5] [--no-reconstruct]\n\
         \todatum analyze <input_file> [--clearance 0.05]\n"
    );
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    if args.is_empty() || args[0] == "-h" || args[0] == "--help" {
        print_usage();
        return;
    }

    let res = match args[0].as_str() {
        "inspect" => cmd_inspect(&args[1..]),
        "convert" => cmd_convert(&args[1..]),
        "rebuild" => cmd_rebuild(&args[1..]),
        "analyze" => cmd_analyze(&args[1..]),
        other => Err(format!("Unknown subcommand '{}'. Run `odatum --help`.", other)),
    };

    if let Err(err) = res {
        eprintln!("Error: {}", err);
        process::exit(1);
    }
}

fn cmd_inspect(args: &[String]) -> Result<(), String> {
    let input = PathBuf::from(args.first().ok_or("Missing <input_file>")?);
    let doc = import_document(&input, None)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&doc.compact_summary()).map_err(|e| e.to_string())?
    );
    Ok(())
}

fn cmd_convert(args: &[String]) -> Result<(), String> {
    if args.len() < 2 {
        return Err("Usage: odatum convert <input_file> <output_file> [--target <fmt>]".to_string());
    }
    let input = PathBuf::from(&args[0]);
    let output = PathBuf::from(&args[1]);
    let mut target: Option<SpatialFormat> = None;

    let mut i = 2;
    while i < args.len() {
        if args[i] == "--target" && i + 1 < args.len() {
            target = SpatialFormat::from_name(&args[i + 1]);
            if target.is_none() {
                return Err(format!("Unknown target format: {}", args[i + 1]));
            }
            i += 2;
        } else {
            i += 1;
        }
    }

    let doc = import_document(&input, None)?;
    export_document(&doc, &output, target)?;
    let out_json = serde_json::json!({
        "status": "ok",
        "input": input.display().to_string(),
        "output": output.display().to_string(),
        "nodes": doc.nodes.len(),
        "datum": doc.datum
    });
    println!("{}", serde_json::to_string_pretty(&out_json).unwrap());
    Ok(())
}

fn cmd_rebuild(args: &[String]) -> Result<(), String> {
    if args.len() < 2 {
        return Err("Usage: odatum rebuild <input_file> <output_file> [--units m|mm|ft|in] [--up y|z]".to_string());
    }
    let input = PathBuf::from(&args[0]);
    let output = PathBuf::from(&args[1]);
    let mut opts = RebuildOptions::default();

    let mut i = 2;
    while i < args.len() {
        match args[i].as_str() {
            "--units" if i + 1 < args.len() => {
                opts.target_unit = LengthUnit::from_str_loose(&args[i + 1])
                    .ok_or_else(|| format!("Invalid unit: {}", args[i + 1]))?;
                i += 2;
            }
            "--up" if i + 1 < args.len() => {
                opts.target_up = UpAxis::from_str_loose(&args[i + 1])
                    .ok_or_else(|| format!("Invalid up axis: {}", args[i + 1]))?;
                i += 2;
            }
            "--weld" if i + 1 < args.len() => {
                opts.weld_tolerance = args[i + 1]
                    .parse::<f64>()
                    .map_err(|_| format!("Invalid weld tolerance: {}", args[i + 1]))?;
                i += 2;
            }
            "--no-reconstruct" => {
                opts.reconstruct_primitives = false;
                i += 1;
            }
            "--strip-mesh" => {
                opts.strip_redundant_mesh_when_parametric = true;
                i += 1;
            }
            _ => i += 1,
        }
    }

    let doc = import_document(&input, None)?;
    let (rebuilt, report) = rebuild_document(&doc, &opts);
    export_document(&rebuilt, &output, None)?;
    println!(
        "{}",
        serde_json::to_string_pretty(&serde_json::json!({
            "status": "ok",
            "input": input.display().to_string(),
            "output": output.display().to_string(),
            "rebuild_report": report
        }))
        .unwrap()
    );
    Ok(())
}

fn cmd_analyze(args: &[String]) -> Result<(), String> {
    let input = PathBuf::from(args.first().ok_or("Missing <input_file>")?);
    let mut clearance = 0.05f64;
    let mut i = 1;
    while i < args.len() {
        if args[i] == "--clearance" && i + 1 < args.len() {
            clearance = args[i + 1].parse::<f64>().unwrap_or(0.05);
            i += 2;
        } else {
            i += 1;
        }
    }

    let doc = import_document(&input, None)?;
    let mut mesh_reports = Vec::new();
    for node in &doc.nodes {
        if let Some(m) = opendatum_core::mesh::resolve_node_mesh(node) {
            mesh_reports.push(serde_json::json!({
                "node_id": node.id,
                "name": node.name,
                "discipline": node.discipline,
                "quality": analyze_mesh(&m)
            }));
        }
    }
    let clashes = detect_clashes(&doc, clearance);
    let out = serde_json::json!({
        "summary": doc.compact_summary(),
        "mesh_quality": mesh_reports,
        "clash_report": clashes
    });
    println!("{}", serde_json::to_string_pretty(&out).unwrap());
    Ok(())
}
