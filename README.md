# OpenDatum

**The Universal Open-Source Spatial Hub, First-Principles Physical Engineering Substrate, and Agentic-Human Connector**

[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

OpenDatum bridges two historically siloed worlds into a single, open, zero-lock-in substrate:

1. **Universal Spatial Hub & Dual-Representation IR (`USIR`)** — Any-to-any spatial translation, legacy cleanup, and parametric reconstruction across **CAD/BIM** (`IFC`, `DXF`, `STEP` hooks), **Game Engines & Simulation** (`Godot 4 .tscn`, `Bevy .ron`, `glTF 2.0`, `OpenUSD .usda`), and **Fabrication / 3D Printing** (`3MF`, `STL`, `OBJ`). Designed for rapid AI-agent iteration *and* painless human hand-tweaking with edit-lock preservation.
2. **First-Principles Physical Engineering Engine (PLE-Ready & Industry-Wide)** — Directly addresses the core agentic bottlenecks identified in **PLE: Physical-Engineering's Last Exam** (`arXiv:2610.30537`) and the Kaggle Agent Harness Challenge:
   - **Token-Efficient Progressive-Disclosure Codes & Standards Engine** (Jurisdiction graph + SQLite FTS5/BM25 hybrid search + pluggable local/licensed code packs across Structural, Civil, Electrical, Mechanical/MEP, Fabrication, and Space/ISRU).
   - **Universal Materials Property Substrate** — Unit-safe, provenance-tracked terrestrial engineering materials (steels, concretes, soils, timbers, polymers, composites, MEP fluids), metamaterials, and **off-Earth / ISRU resources** (lunar sintered regolith, Martian geopolymer, asteroidal Fe-Ni alloys, cryogenic ice), plus live **OPTIMADE / Materials Project** federation.
   - **Deterministic First-Principles Engineering Solvers** — Dimensional-safe solvers for Structural, Civil/Geotech, Electrical (NEC/IEC), Mechanical/HVAC/Fluid/Thermal (including vacuum radiative transfer), plus 3D manifold/printability and multi-discipline clash detection.
   - **Offline-First MCP Server** — Zero-internet JSON-RPC 2.0 stdio Model Context Protocol server ready for isolated PLE containers, coding agents, and local CAD/game workflows.

---

## Architecture Overview

```
                    ┌──────────────────────────────────────────────────────────┐
                    │         Humans (Godot / Bevy / Blender / CAD / Git)      │
                    │         Agents (PLE Harness / MCP / CLI / Python / Rust) │
                    └──────────────────────────┬───────────────────────────────┘
                                               │
                    ┌──────────────────────────▼───────────────────────────────┐
                    │       OpenDatum Universal MCP Server & CLI (`odatum`)    │
                    └──────┬───────────────────┬──────────────────────┬────────┘
                           │                   │                      │
           ┌───────────────▼───────┐ ┌─────────▼──────────┐ ┌─────────▼──────────┐
           │  Rust Spatial Core    │ │ First-Principles   │ │ Progressive Codes  │
           │  (`opendatum-core`)   │ │ Materials & Solvers│ │ & Standards Graph  │
           │                       │ │                    │ │                    │
           │ • Layered USIR Schema │ │ • 40+ Seed Materials│ │ • Intl→Nat→State→  │
           │ • Legacy Mesh Rebuild │ │ • Terrestrial+ISRU │ │   Local Resolution │
           │ • Manifold / Print QA │ │ • Gravity/Env Scale│ │ • SQLite FTS5+BM25 │
           │ • Multi-Disc Clashes  │ │ • OPTIMADE Adapter │ │ • 3-Stage Token    │
           │ • OBJ/STL/3MF/glTF/   │ │ • Structural/Civil/│ │   Disclosure       │
           │   USDA/DXF/IFC/       │ │   Elec/MEP/Thermal │ │ • Pluggable Packs  │
           │   Godot 4 / Bevy      │ │ • SI↔Imperial Safe │ │                    │
           └───────────────────────┘ └────────────────────┘ └────────────────────┘
```

See [docs/RFC-0001-ARCHITECTURE.md](docs/RFC-0001-ARCHITECTURE.md) for the complete specification.

---

## Quick Start

### 1. Build the Rust Spatial Core & CLI
```bash
cargo build --release
cargo test
./target/release/odatum --help
```

### 2. Set up the Python Engineering, Materials, Codes & MCP Layer
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python3 -m unittest discover -s tests -v
```

### 3. Run the Offline MCP Server (for PLE containers, Claude, Hermes, Antigravity, etc.)
```bash
python3 -m opendatum.mcp_server
```

### 4. Live Human + Agent Co-Editing (Godot 4 / Bevy / WASM)
```bash
# Human-lock-safe merge of agent updates into a human-edited scene
./target/release/odatum merge human.odir.json agent.odir.json merged.odir.json

# Hot-sync USIR to Godot 4, Bevy, glTF 2.0, and OpenUSD (add --watch for live loop)
./target/release/odatum sync merged.odir.json --godot out/scene.tscn --bevy out/scene.ron --gltf out/scene.gltf --usd out/scene.usda

# Compile zero-upload WebAssembly build for browser / WebMCP viewers
cargo build --target wasm32-unknown-unknown -p opendatum-wasm --release
```
- **Godot 4 Plugin:** Copy `integrations/godot/addons/opendatum_sync/` into your Godot project's `addons/` folder and enable **OpenDatum Live Sync**.
- **Bevy Plugin:** Use `integrations/bevy/opendatum_bevy.rs` to poll `.odir.json` updates while protecting `human_locked` entities.

### 5. PLE (Physical-Engineering's Last Exam) Offline Container Harness
```bash
# Build offline-ready PLE evaluation container
docker build -f ple/Dockerfile -t opendatum-ple-harness .

# Run in stdio MCP mode or local HTTP JSON-RPC mode
python3 ple/serve.py           # stdio MCP
python3 ple/serve.py --http    # http://127.0.0.1:8080/health
```

### 6. Example CLI Workflows
```bash
# Inspect and rebuild a messy legacy STL/OBJ/DXF/IFC into clean USIR + Godot 4 + Bevy + 3MF
./target/release/odatum rebuild examples/legacy_bracket.obj out/bracket.odir.json --units m --up y
./target/release/odatum convert out/bracket.odir.json out/bracket.tscn --target godot
./target/release/odatum convert out/bracket.odir.json out/bracket.ron --target bevy
./target/release/odatum convert out/bracket.odir.json out/bracket.3mf --target 3mf
./target/release/odatum convert out/bracket.odir.json out/bracket.usda --target usd
./target/release/odatum convert out/bracket.odir.json out/bracket.gltf --target gltf

# Run first-principles engineering & codes queries from CLI
python3 -m opendatum.cli materials search "lunar regolith"
python3 -m opendatum.cli codes search "voltage drop feeder" --discipline electrical --jurisdiction US-CA
python3 -m opendatum.cli solve beam --span-m 6.0 --load-kn-m 18.0 --material steel_a992 --ix-mm4 83.2e6 --depth-mm 310
```

---

## Community & Extensibility

OpenDatum is designed as a **"rising tide"** open-source standard:
- Drop new material JSON packs into `data/materials/packs/` (metals, soils, bio-materials, metamaterials, planetary ISRU).
- Drop jurisdiction code packs into `data/codes/packs/` and index them locally with `opendatum codes ingest`.
- Add new format adapters in `crates/opendatum-core/src/adapters.rs` or Python bridges (e.g., `IfcOpenShell`, `ezdxf`, `OpenCASCADE/OCP`).

## License

Apache License 2.0 — Copyright 2026 Jonathan Korstad.
