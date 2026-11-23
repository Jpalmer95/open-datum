# AGENTS.md — OpenDatum Repository Guidelines

## Overview
OpenDatum is a hybrid **Rust + Python** monorepo implementing:
- `crates/opendatum-core` & `crates/opendatum-cli` (`odatum`): Universal Spatial IR (`USIR`), legacy mesh/CAD rebuild, manifold checks, multi-discipline clash detection, and format adapters (OBJ, STL, 3MF, glTF 2.0, OpenUSD `.usda`, Godot 4 `.tscn`, Bevy `.ron`, DXF, IFC).
- `python/opendatum`: First-principles unit engine, universal materials substrate (terrestrial + metamaterials + off-Earth/ISRU + OPTIMADE federation), jurisdiction-scoped progressive-disclosure codes engine (SQLite FTS5), deterministic engineering solvers (Structural, Civil, Electrical, Mechanical/Thermal), and offline-ready JSON-RPC 2.0 MCP server.

## Build & Verification
- Rust: `cargo test` and `cargo build --release`
- Python: `PYTHONPATH=python python3 -m unittest discover -s tests -v`
- Never break offline execution: all core solvers, seed materials, seed codes, spatial conversions, and MCP tools MUST run with zero internet access for PLE container compatibility.
- Preserve human edit locks (`human_locked: true`) during any automated USIR rebuild or agentic edit.
- All physical quantities in code and data MUST carry explicit units (SI canonical internally) and provenance citations.
