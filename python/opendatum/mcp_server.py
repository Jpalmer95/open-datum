"""Offline-First Universal MCP Server (JSON-RPC 2.0 over stdio).

Zero external dependencies — drops directly into isolated PLE evaluation containers,
Claude Code, Codex, Hermes, Antigravity, Godot/Bevy agent pipelines, and local CAD stacks.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List

from . import __version__
from .cad_bridges import (
    cad_capabilities,
    export_usir_to_ifc4,
    extract_dxf_takeoff,
    inspect_step_file,
)
from .codes import CodesEngine
from .materials import MaterialsDB
from .solvers import EngineeringSolvers
from .spatial import SpatialHub
from .units import convert_unit


def _ple_harness_import():
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from ple.harness import triage_workspace, verify_deliverables

    return triage_workspace, verify_deliverables


class OpenDatumMCPServer:
    def __init__(self):
        self.materials = MaterialsDB()
        self.codes = CodesEngine()
        self.solvers = EngineeringSolvers(self.materials)
        self._spatial: SpatialHub | None = None
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._register_all_tools()

    def _get_spatial(self) -> SpatialHub:
        if self._spatial is None:
            self._spatial = SpatialHub()
        return self._spatial

    def _register(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[[Dict[str, Any]], Any],
    ) -> None:
        self.tools[name] = {
            "spec": {
                "name": name,
                "description": description,
                "inputSchema": input_schema,
            },
            "handler": handler,
        }

    def _register_all_tools(self) -> None:
        # ---- Spatial Hub ----
        self._register(
            "spatial_inspect",
            "Inspect any supported 3D/CAD/BIM file (USIR, OBJ, STL, DXF, IFC) and return a token-efficient semantic summary.",
            {
                "type": "object",
                "properties": {"input_path": {"type": "string"}},
                "required": ["input_path"],
            },
            lambda a: self._get_spatial().inspect(a["input_path"]),
        )
        self._register(
            "spatial_convert",
            "Convert spatial assets any-to-any across USIR, OBJ, STL, 3MF (3D printing), glTF 2.0, OpenUSD (.usda), Godot 4 (.tscn), Bevy (.ron), and DXF.",
            {
                "type": "object",
                "properties": {
                    "input_path": {"type": "string"},
                    "output_path": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["input_path", "output_path"],
            },
            lambda a: self._get_spatial().convert(a["input_path"], a["output_path"], a.get("target")),
        )
        self._register(
            "spatial_rebuild_legacy",
            "Modernize and clean a legacy 3D/CAD file: normalize units & up-axis, weld vertices, remove degenerates, reconstruct parametric primitives, and preserve human_locked edits.",
            {
                "type": "object",
                "properties": {
                    "input_path": {"type": "string"},
                    "output_path": {"type": "string"},
                    "units": {"type": "string", "default": "m"},
                    "up": {"type": "string", "default": "y"},
                    "weld_tolerance": {"type": "number", "default": 1e-5},
                    "reconstruct_primitives": {"type": "boolean", "default": True},
                    "strip_mesh": {"type": "boolean", "default": False},
                },
                "required": ["input_path", "output_path"],
            },
            lambda a: self._get_spatial().rebuild(
                a["input_path"],
                a["output_path"],
                units=a.get("units", "m"),
                up=a.get("up", "y"),
                weld_tolerance=float(a.get("weld_tolerance", 1e-5)),
                reconstruct_primitives=bool(a.get("reconstruct_primitives", True)),
                strip_mesh=bool(a.get("strip_mesh", False)),
            ),
        )
        self._register(
            "spatial_analyze_and_clash",
            "Analyze mesh manifoldness/3D-printability, volumes, and run multi-discipline MEP/Structural 3D clash & clearance checks.",
            {
                "type": "object",
                "properties": {
                    "input_path": {"type": "string"},
                    "clearance": {"type": "number", "default": 0.05},
                },
                "required": ["input_path"],
            },
            lambda a: self._get_spatial().analyze(a["input_path"], float(a.get("clearance", 0.05))),
        )
        self._register(
            "spatial_merge_human_safe",
            "Merge an incoming agent USIR document into a human-edited USIR document while preserving every human_locked node verbatim.",
            {
                "type": "object",
                "properties": {
                    "human_usir_path": {"type": "string"},
                    "agent_usir_path": {"type": "string"},
                    "output_usir_path": {"type": "string"},
                },
                "required": ["human_usir_path", "agent_usir_path", "output_usir_path"],
            },
            lambda a: self._get_spatial().merge(
                a["human_usir_path"], a["agent_usir_path"], a["output_usir_path"]
            ),
        )
        self._register(
            "spatial_sync_engines",
            "Hot-sync a USIR document simultaneously to Godot 4 (.tscn), Bevy (.ron), glTF 2.0, and/or OpenUSD (.usda) with clash summary.",
            {
                "type": "object",
                "properties": {
                    "usir_path": {"type": "string"},
                    "godot_path": {"type": "string"},
                    "bevy_path": {"type": "string"},
                    "gltf_path": {"type": "string"},
                    "usd_path": {"type": "string"},
                },
                "required": ["usir_path"],
            },
            lambda a: self._get_spatial().sync(
                a["usir_path"],
                godot_path=a.get("godot_path"),
                bevy_path=a.get("bevy_path"),
                gltf_path=a.get("gltf_path"),
                usd_path=a.get("usd_path"),
            ),
        )

        # ---- CAD/BIM Full Bridges & PLE Harness ----
        self._register(
            "cad_capabilities",
            "List built-in zero-dep spatial formats and installed optional CAD/BIM bridges (ezdxf, IfcOpenShell, trimesh, OpenCASCADE/OCP).",
            {"type": "object", "properties": {}},
            lambda _a: cad_capabilities(),
        )
        self._register(
            "cad_inspect_step",
            "Inspect an ISO 10303-21 STEP (.stp/.step) CAD assembly (products, BREP solids, faces, units, plus exact OpenCASCADE volume when installed).",
            {
                "type": "object",
                "properties": {"step_path": {"type": "string"}},
                "required": ["step_path"],
            },
            lambda a: inspect_step_file(a["step_path"]),
        )
        self._register(
            "cad_extract_dxf_takeoff",
            "Extract a per-layer quantity takeoff (total line/polyline lengths, entity counts, annotations) from a DXF engineering drawing.",
            {
                "type": "object",
                "properties": {"dxf_path": {"type": "string"}},
                "required": ["dxf_path"],
            },
            lambda a: extract_dxf_takeoff(a["dxf_path"]),
        )
        self._register(
            "cad_export_ifc",
            "Export an OpenDatum USIR (.odir.json) document into a standards-compliant IFC4 STEP-SPF (.ifc) BIM file.",
            {
                "type": "object",
                "properties": {
                    "usir_path": {"type": "string"},
                    "output_ifc_path": {"type": "string"},
                },
                "required": ["usir_path", "output_ifc_path"],
            },
            lambda a: export_usir_to_ifc4(a["usir_path"], a["output_ifc_path"]),
        )
        self._register(
            "ple_workspace_triage",
            "Scan a PLE or engineering project workspace and produce a token-efficient brief: file inventory, detected disciplines, spatial summaries, and suggested code clauses.",
            {
                "type": "object",
                "properties": {"workspace_dir": {"type": "string"}},
                "required": ["workspace_dir"],
            },
            lambda a: _ple_harness_import()[0](a["workspace_dir"]),
        )
        self._register(
            "ple_verify_deliverables",
            "Pre-submission QA gate verifying deliverables (.odir.json clash-free, valid JSON, non-empty DXF/IFC schemas) before grading or handoff.",
            {
                "type": "object",
                "properties": {
                    "workspace_dir": {"type": "string"},
                    "min_clearance": {"type": "number", "default": 0.05},
                },
                "required": ["workspace_dir"],
            },
            lambda a: _ple_harness_import()[1](
                a["workspace_dir"], float(a.get("min_clearance", 0.05))
            ),
        )

        # ---- Materials Substrate ----
        self._register(
            "materials_search",
            "Search the universal first-principles materials substrate (terrestrial construction, MEP, 3D printing, geotech, composites, metamaterials, and lunar/Martian/asteroid ISRU).",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "default": ""},
                    "category": {"type": "string"},
                    "domain": {"type": "string"},
                    "vacuum_only": {"type": "boolean", "default": False},
                    "min_yield_mpa": {"type": "number"},
                    "max_density_kg_m3": {"type": "number"},
                    "limit": {"type": "integer", "default": 10},
                },
            },
            lambda a: self.materials.search(
                query=a.get("query", ""),
                category=a.get("category"),
                domain=a.get("domain"),
                vacuum_only=bool(a.get("vacuum_only", False)),
                min_yield_mpa=a.get("min_yield_mpa"),
                max_density_kg_m3=a.get("max_density_kg_m3"),
                limit=int(a.get("limit", 10)),
            ),
        )
        self._register(
            "materials_get",
            "Fetch full physical, mechanical, thermal, electrical, tribological, acoustic, embodied-carbon, and derived properties for a material ID.",
            {
                "type": "object",
                "properties": {"material_id": {"type": "string"}},
                "required": ["material_id"],
            },
            lambda a: self.materials.get(a["material_id"]),
        )
        self._register(
            "materials_compare",
            "Compare multiple candidate materials under a target planetary/operational environment (Earth, Moon, Mars, LEO, Asteroid).",
            {
                "type": "object",
                "properties": {
                    "material_ids": {"type": "array", "items": {"type": "string"}},
                    "environment": {"type": "string", "default": "earth_sea_level"},
                },
                "required": ["material_ids"],
            },
            lambda a: self.materials.compare(a["material_ids"], a.get("environment", "earth_sea_level")),
        )
        self._register(
            "materials_calc_mass_cost",
            "Compute mass, gravity-scaled weight (N/kN/lbf), estimated cost, and embodied CO2e from volume & environment.",
            {
                "type": "object",
                "properties": {
                    "material_id": {"type": "string"},
                    "volume_m3": {"type": "number"},
                    "environment": {"type": "string", "default": "earth_sea_level"},
                },
                "required": ["material_id", "volume_m3"],
            },
            lambda a: self.materials.calc_mass_weight_cost(
                a["material_id"], float(a["volume_m3"]), a.get("environment", "earth_sea_level")
            ),
        )
        self._register(
            "materials_query_optimade",
            "Federated online lookup against OPTIMADE / Materials Project REST APIs by reduced chemical formula (graceful offline fallback).",
            {
                "type": "object",
                "properties": {
                    "formula": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                "required": ["formula"],
            },
            lambda a: self.materials.query_optimade(a["formula"], limit=int(a.get("limit", 5))),
        )

        # ---- Codes & Standards Progressive Disclosure ----
        self._register(
            "codes_resolve_jurisdiction",
            "Stage 1 progressive disclosure: resolve applicable international/national/state/space code hierarchy for a location & discipline.",
            {
                "type": "object",
                "properties": {
                    "jurisdiction": {"type": "string"},
                    "discipline": {"type": "string"},
                },
                "required": ["jurisdiction"],
            },
            lambda a: self.codes.resolve_jurisdiction(a["jurisdiction"], a.get("discipline")),
        )
        self._register(
            "codes_search",
            "Stage 2 progressive disclosure: token-efficient BM25 FTS5 search returning compact code clause summaries & formulas.",
            {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "discipline": {"type": "string"},
                    "jurisdiction": {"type": "string"},
                    "limit": {"type": "integer", "default": 6},
                },
                "required": ["query"],
            },
            lambda a: self.codes.search(
                a["query"],
                discipline=a.get("discipline"),
                jurisdiction=a.get("jurisdiction"),
                limit=int(a.get("limit", 6)),
            ),
        )
        self._register(
            "codes_get_clause",
            "Stage 3 progressive disclosure: fetch full rule details, numeric code parameters, and equations for a specific clause ID.",
            {
                "type": "object",
                "properties": {"clause_id": {"type": "string"}},
                "required": ["clause_id"],
            },
            lambda a: self.codes.get_clause(a["clause_id"]),
        )
        self._register(
            "codes_ingest_pack",
            "Ingest a local JSON code pack (municipal ordinances, licensed code tables, project specs) into the local SQLite FTS5 index.",
            {
                "type": "object",
                "properties": {"pack_path": {"type": "string"}},
                "required": ["pack_path"],
            },
            lambda a: self.codes.ingest_pack(Path(a["pack_path"])),
        )

        # ---- Deterministic Engineering Solvers & Units ----
        self._register(
            "convert_units",
            "Dimensional-safe SI <-> Imperial unit converter (length, area, volume, mass, force, line_load, pressure, moment, power, flow_rate, velocity, density, temperature).",
            {
                "type": "object",
                "properties": {
                    "value": {"type": "number"},
                    "from_unit": {"type": "string"},
                    "to_unit": {"type": "string"},
                },
                "required": ["value", "from_unit", "to_unit"],
            },
            lambda a: convert_unit(float(a["value"]), a["from_unit"], a["to_unit"]),
        )
        self._register(
            "solve_structural_load_combos",
            "Compute ASCE 7-22 LRFD governing load combinations (including uplift).",
            {
                "type": "object",
                "properties": {
                    "dead": {"type": "number"},
                    "live": {"type": "number", "default": 0.0},
                    "roof_live_or_snow": {"type": "number", "default": 0.0},
                    "wind": {"type": "number", "default": 0.0},
                    "seismic": {"type": "number", "default": 0.0},
                    "unit_label": {"type": "string", "default": "kN"},
                },
                "required": ["dead"],
            },
            lambda a: self.solvers.structural_load_combinations_asce7(**a),
        )
        self._register(
            "solve_structural_beam",
            "Deterministic beam bending, shear, and L/360 deflection check with optional planetary gravity self-weight.",
            {
                "type": "object",
                "properties": {
                    "span_m": {"type": "number"},
                    "uniform_load_kn_m": {"type": "number"},
                    "material_id": {"type": "string"},
                    "moment_of_inertia_mm4": {"type": "number"},
                    "depth_mm": {"type": "number"},
                    "support_type": {"type": "string", "default": "simply_supported"},
                    "deflection_limit_ratio": {"type": "number", "default": 360.0},
                    "include_self_weight_area_mm2": {"type": "number", "default": 0.0},
                    "environment": {"type": "string", "default": "earth_sea_level"},
                },
                "required": ["span_m", "uniform_load_kn_m", "material_id", "moment_of_inertia_mm4", "depth_mm"],
            },
            lambda a: self.solvers.structural_beam_check(**a),
        )
        self._register(
            "solve_civil_manning_flow",
            "Manning gravity pipe or open-channel stormwater/drainage hydraulics calculator.",
            {
                "type": "object",
                "properties": {
                    "slope": {"type": "number"},
                    "manning_n": {"type": "number"},
                    "diameter_m": {"type": "number"},
                    "width_m": {"type": "number"},
                    "depth_m": {"type": "number"},
                    "fill_fraction": {"type": "number", "default": 1.0},
                },
                "required": ["slope", "manning_n"],
            },
            lambda a: self.solvers.civil_manning_flow(**a),
        )
        self._register(
            "solve_civil_bearing_capacity",
            "Terzaghi shallow foundation ultimate & allowable bearing capacity check (Earth/Moon/Mars).",
            {
                "type": "object",
                "properties": {
                    "footing_width_m": {"type": "number"},
                    "embedment_depth_m": {"type": "number"},
                    "soil_material_id": {"type": "string", "default": "soil_dense_sand"},
                    "footing_shape": {"type": "string", "default": "square"},
                    "applied_load_kn": {"type": "number"},
                    "factor_of_safety": {"type": "number", "default": 3.0},
                    "environment": {"type": "string", "default": "earth_sea_level"},
                },
                "required": ["footing_width_m", "embedment_depth_m"],
            },
            lambda a: self.solvers.civil_bearing_capacity_terzaghi(**a),
        )
        self._register(
            "solve_electrical_feeder",
            "NEC/IEC single-phase & three-phase feeder voltage drop, heat loss, and 125% continuous load check.",
            {
                "type": "object",
                "properties": {
                    "voltage_v": {"type": "number"},
                    "current_a": {"type": "number"},
                    "one_way_length_m": {"type": "number"},
                    "conductor_area_mm2": {"type": "number"},
                    "phases": {"type": "integer", "default": 3},
                    "conductor_material_id": {"type": "string", "default": "copper_c11000"},
                    "power_factor": {"type": "number", "default": 0.90},
                    "continuous_load": {"type": "boolean", "default": True},
                    "max_vd_pct": {"type": "number", "default": 3.0},
                },
                "required": ["voltage_v", "current_a", "one_way_length_m", "conductor_area_mm2"],
            },
            lambda a: self.solvers.electrical_feeder_check(**a),
        )
        self._register(
            "solve_electrical_solar_busbar",
            "NEC 705.12(B)(3)(2) 120% solar PV / ESS busbar interconnection verifier.",
            {
                "type": "object",
                "properties": {
                    "busbar_rating_a": {"type": "number"},
                    "main_breaker_a": {"type": "number"},
                    "inverter_max_output_a": {"type": "number"},
                },
                "required": ["busbar_rating_a", "main_breaker_a", "inverter_max_output_a"],
            },
            lambda a: self.solvers.electrical_solar_busbar_120_check(**a),
        )
        self._register(
            "solve_mechanical_pipe_flow",
            "Darcy-Weisbach & Swamee-Jain hydronic/plumbing pipe pressure drop and pumping power solver.",
            {
                "type": "object",
                "properties": {
                    "flow_rate_l_s": {"type": "number"},
                    "pipe_id_mm": {"type": "number"},
                    "length_m": {"type": "number"},
                    "roughness_mm": {"type": "number", "default": 0.045},
                    "fluid_material_id": {"type": "string", "default": "fluid_water_20c"},
                    "environment": {"type": "string", "default": "earth_sea_level"},
                },
                "required": ["flow_rate_l_s", "pipe_id_mm", "length_m"],
            },
            lambda a: self.solvers.mechanical_pipe_flow_darcy(**a),
        )
        self._register(
            "solve_mechanical_duct",
            "ASHRAE rectangular HVAC duct Huebscher equivalent diameter, friction loss, and velocity noise check.",
            {
                "type": "object",
                "properties": {
                    "airflow_m3_s": {"type": "number"},
                    "width_mm": {"type": "number"},
                    "height_mm": {"type": "number"},
                    "length_m": {"type": "number", "default": 10.0},
                    "roughness_mm": {"type": "number", "default": 0.09},
                },
                "required": ["airflow_m3_s", "width_mm", "height_mm"],
            },
            lambda a: self.solvers.mechanical_duct_sizing(**a),
        )
        self._register(
            "solve_thermal_envelope",
            "Multi-layer composite building wall or off-Earth vacuum radiative habitat thermal & radiation shielding areal density solver.",
            {
                "type": "object",
                "properties": {
                    "layers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "material_id": {"type": "string"},
                                "thickness_m": {"type": "number"},
                            },
                            "required": ["material_id", "thickness_m"],
                        },
                    },
                    "area_m2": {"type": "number"},
                    "t_inside_k": {"type": "number"},
                    "t_outside_k": {"type": "number"},
                    "h_inside_w_m2k": {"type": "number", "default": 8.3},
                    "h_outside_w_m2k": {"type": "number", "default": 25.0},
                    "include_vacuum_radiation_emissivity": {"type": "number"},
                },
                "required": ["layers", "area_m2", "t_inside_k", "t_outside_k"],
            },
            lambda a: self.solvers.thermal_envelope_and_radiation(**a),
        )

    def handle_request(self, req: Dict[str, Any]) -> Dict[str, Any] | None:
        req_id = req.get("id")
        method = req.get("method", "")
        params = req.get("params") or {}

        if method == "notifications/initialized":
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "opendatum-mcp", "version": __version__},
                    "capabilities": {"tools": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": [t["spec"] for t in self.tools.values()]},
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments") or {}
            entry = self.tools.get(tool_name)
            if not entry:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                }
            try:
                output = entry["handler"](arguments)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": json.dumps(output, indent=2)}],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {"error": str(exc), "trace": traceback.format_exc(limit=3)},
                                    indent=2,
                                ),
                            }
                        ],
                        "isError": True,
                    },
                }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Unsupported MCP method: {method}"},
        }

    def serve_stdio(self) -> None:
        """Reads newline-delimited JSON-RPC 2.0 MCP frames from stdin and writes to stdout."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()
                continue

            resp = self.handle_request(req)
            if resp is not None:
                sys.stdout.write(json.dumps(resp) + "\n")
                sys.stdout.flush()


def main() -> None:
    OpenDatumMCPServer().serve_stdio()


if __name__ == "__main__":
    main()
