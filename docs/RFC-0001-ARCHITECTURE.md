# RFC-0001: OpenDatum Universal Spatial & Physical Engineering Substrate

- **Status:** Draft v0.1 (Implemented Vertical Slice)
- **License:** Apache-2.0
- **Scope:** Universal Spatial IR (`USIR`), Legacy Asset Modernization, Multi-Engine/CAD/Fabrication Bridging, First-Principles Materials Substrate, Progressive-Disclosure Codes Graph, and Deterministic Physical Engineering Solvers.

---

## 1. Problem Statement

Both **3D/Game/CAD creation** and **autonomous physical engineering** (as benchmarked by *PLE: Physical-Engineering's Last Exam*, arXiv:2610.30537) suffer from the same underlying structural failures:

1. **Fragmented, Lossy Legacy Formats:** Moving geometry between AEC/BIM (`IFC`, `DXF`, `DWG`), mechanical CAD (`STEP`, `IGES`), game engines (`Godot`, `Bevy`, `Unreal`, `Unity`, `glTF`, `OpenUSD`), and 3D printing (`STL`, `3MF`) destroys semantic intent, units, coordinate frames, materials, tolerances, and physics properties.
2. **Token & Context Exhaustion for AI Agents:** Raw legacy meshes, verbose IFC files, and 1,000-page building codes overwhelm agent context windows (PLE frontier baselines average ~27M tokens/task at ~50.6% accuracy).
3. **Human ↔ Agent Round-Trip Friction:** When an agent regenerates a scene or CAD model from scratch, manual human tweaks (hand-adjusted clearances, artistic edits, engineer overrides) are overwritten.
4. **Disconnected Physics, Materials & Codes:** Agents guess material properties, mix SI and Imperial units, ignore local code amendments, or hallucinate arithmetic in load-path, feeder, fluid, and thermal calculations.

---

## 2. Core Design Pillars

### Pillar A: Layered Dual-Representation Spatial IR (`USIR`)
An OpenDatum document (`.odir.json`) separates **concise human/agent-editable intent** from **bulk geometry buffers**:

- **`datum` (Reference Frame):** Canonical length unit (`m`, `mm`, `ft`, `in`), up-axis (`Y` or `Z`), right-handedness, optional geodetic origin, planetary environment ID (`earth_sea_level`, `lunar_mare_day`, `mars_surface`, `orbital_leo`, `asteroid_microgravity`), and gravity vector `[gx, gy, gz]`.
- **`nodes` (Hierarchical Semantic Graph):**
  - `discipline`: `architecture | structural | civil | electrical | mechanical | plumbing | fire | gameplay | fabrication | aerospace | generic`
  - `role`: e.g. `beam`, `column`, `slab`, `wall`, `duct`, `pipe`, `conduit`, `bracket`, `terrain`, `prop`, `collider`, `habitat_shell`
  - `transform`: position, quaternion rotation, scale
  - `parametric`: optional concise parametric generator (`Box`, `Cylinder`, `ExtrudedProfile`, `PipeRun`, `DuctRun`, `StructuralMember`) — orders of magnitude smaller than raw triangles!
  - `mesh`: optional deduplicated, manifold-verified triangle mesh buffer
  - `material_id`: canonical link into the OpenDatum Materials Substrate
  - `physics`: static/dynamic/kinematic body, auto-calculated mass, friction, restitution, collider primitive
  - `ports` & `connections`: MEP/electrical/structural connectivity graph (flow, voltage, load transfer)
  - `provenance`: source format, original entity GUID/handle, `human_locked` flag so automated rebuilds preserve manual tweaks.

### Pillar B: Legacy Modernization & Reconstruction Pipeline
When ingesting messy legacy files (`OBJ`, `STL`, `DXF`, `IFC`):
1. **Normalize Frame & Units:** Convert mm/in/ft → target units; remap Z-up ↔ Y-up cleanly.
2. **Heal Geometry:** Quantized vertex welding, degenerate/zero-area triangle culling, duplicate face removal, consistent normal recalculation.
3. **Inspect Quality:** Compute half-edge manifoldness, boundary edge count (watertight check for 3D printing), signed volume, surface area, and AABB.
4. **Reconstruct Parametric Intent:** Detect axis-aligned prisms/extrusions and cylindrical forms within tolerance so agents can reason over `Box(w=0.2, h=0.4, d=6.0)` instead of 40,000 noisy triangles.
5. **Cross-Discipline Clash & Clearance Analysis:** Fast 3D spatial overlap & minimum-clearance checking (e.g., HVAC duct vs structural beam, electrical conduit vs wet pipe).

### Pillar C: First-Principles Universal Materials Substrate
- **Unified Schema:** SI canonical values with explicit uncertainty bounds, temperature validity range, provenance/standard citation, and category/environment tags.
- **Broad Physical Coverage:** Density, elastic/shear/bulk moduli, Poisson's ratio, yield/ultimate/compressive/shear strengths, fracture toughness, fatigue endurance, thermal conductivity/expansion/specific heat, melting/glass-transition/service temps, electrical resistivity & dielectric strength, static/kinetic friction coefficients, acoustic speed of sound, optical emissivity/solar absorptivity, embodied carbon (`kgCO2e/kg`), radiation shielding areal/hydrogen effectiveness, and vacuum outgassing suitability.
- **Scalable Federation:** Built-in verified offline seed corpus (terrestrial construction, MEP, 3D printing, geotech, composites, metamaterials, Lunar/Martian/Asteroid ISRU) + pluggable local JSON packs + live **OPTIMADE / Materials Project** REST adapter for atomic/crystalline materials discovery.

### Pillar D: Jurisdiction-Scoped Progressive-Disclosure Codes Engine
- **Jurisdiction Tree:** `INTL` (ISO/IEC/ASHRAE/NFPA/NASA-STD) → `US` (IBC/ASCE7/AISC/ACI/NEC/IMC/IPC/OSHA) / `EU` (Eurocodes EN 1990–1999) → `US-CA` (CBC/Title 24), `US-FL` (FBC/HVHZ), `US-TX`, `US-NY` → municipal overlays.
- **3-Stage Token-Budgeted Retrieval:**
  1. Resolve applicable code stack for `(jurisdiction, discipline)`.
  2. Search compact clause summaries via local SQLite FTS5 + BM25 + jurisdiction boost (~150–300 tokens).
  3. Pull full formulas, parameters, and verification checklists only for selected clause IDs.
- **Copyright-Clean Extensibility:** Ships open first-principles engineering rules & public standard summaries; organizations ingest licensed local/proprietary standards into their private local SQLite index.

### Pillar E: Offline-First Deterministic Solvers & Universal MCP Interface
All calculations execute deterministically in code with strict SI/Imperial unit handling and return structured audit trails (inputs, equations, intermediate values, pass/fail code checks, margins of safety) over CLI, Python/Rust SDKs, and stdio JSON-RPC 2.0 MCP.

---

## 3. Roadmap Beyond v0.1 Vertical Slice

- **v0.2:** Native OpenCASCADE (`OCP`/`cadquery`) STEP/BREP exact solid round-tripping + `IfcOpenShell` full IFC4x3 geometry tessellation + `ezdxf` block/hatch/dimension extraction.
- **v0.3:** WebAssembly (`wasm32-unknown-unknown`) build of `opendatum-core` for zero-upload browser viewers & client-side WebMCP.
- **v0.4:** Godot 4 GDExtension & Bevy live hot-reload plugin (`opendatum-sync`) watching `.odir.json` diffs for real-time agent + human co-editing.
- **v0.5:** Embedded local vector embeddings (ONNX/sqlite-vec hybrid alongside FTS5) for massive multi-jurisdiction municipal code corpora + automated PLE harness evaluation adapter.
