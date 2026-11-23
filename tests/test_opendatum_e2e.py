"""End-to-end test suite for OpenDatum (Rust Spatial Core + Python Engineering/Materials/Codes/MCP)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from opendatum import CodesEngine, EngineeringSolvers, MaterialsDB, SpatialHub, convert_unit
from opendatum.mcp_server import OpenDatumMCPServer


class TestUnits(unittest.TestCase):
    def test_si_imperial_conversions(self):
        self.assertAlmostEqual(convert_unit(1.0, "ft", "m")["result"], 0.3048, places=6)
        self.assertAlmostEqual(convert_unit(50.0, "ksi", "MPa")["result"], 344.73786, places=3)
        self.assertAlmostEqual(convert_unit(100.0, "C", "F")["result"], 212.0, places=4)
        self.assertAlmostEqual(convert_unit(1.0, "ton_ref", "kW")["result"], 3.51685, places=4)

    def test_dimension_mismatch_raises(self):
        with self.assertRaises(ValueError):
            convert_unit(10.0, "m", "kg")


class TestMaterialsSubstrate(unittest.TestCase):
    def setUp(self):
        self.db = MaterialsDB()

    def test_seed_materials_and_derived_ratios(self):
        steel = self.db.get("steel_a992")
        self.assertEqual(steel["yield_strength_mpa"], 345.0)
        self.assertGreater(steel["derived"]["specific_yield_strength_knm_kg"], 40.0)

        lunar = self.db.search("lunar regolith", domain="off_earth")
        self.assertGreaterEqual(len(lunar), 2)

    def test_environment_gravity_and_compatibility(self):
        earth_wt = self.db.calc_mass_weight_cost("isru_lunar_sintered_mare", 1.0, "earth_sea_level")
        moon_wt = self.db.calc_mass_weight_cost("isru_lunar_sintered_mare", 1.0, "lunar_mare_day")
        self.assertAlmostEqual(earth_wt["mass_kg"], moon_wt["mass_kg"], places=3)
        self.assertAlmostEqual(earth_wt["weight_n"] / moon_wt["weight_n"], 9.80665 / 1.62, places=2)

        cmp = self.db.compare(["polymer_pla", "polymer_peek", "isru_lunar_sintered_mare"], "lunar_mare_day")
        by_id = {r["id"]: r for r in cmp["comparison"]}
        self.assertFalse(by_id["polymer_pla"]["env_compatible"])
        self.assertTrue(by_id["polymer_peek"]["env_compatible"])
        self.assertTrue(by_id["isru_lunar_sintered_mare"]["env_compatible"])


class TestCodesProgressiveDisclosure(unittest.TestCase):
    def setUp(self):
        self.codes = CodesEngine()

    def test_jurisdiction_inheritance_and_search(self):
        resolved = self.codes.resolve_jurisdiction("US-CA-SF", discipline="structural")
        self.assertEqual(resolved["inheritance_chain"], ["US-CA", "US", "INTL"])
        self.assertGreater(resolved["indexed_clause_count"], 0)

        hits = self.codes.search("seismic drift bracing", discipline="structural", jurisdiction="US-CA")
        self.assertGreater(len(hits), 0)
        self.assertEqual(hits[0]["id"], "US-CA-CBC-SEISMIC")

        full = self.codes.get_clause("US-NEC-705.12")
        self.assertEqual(full["parameters"]["busbar_multiplier"], 1.20)

    def test_custom_pack_ingestion(self):
        with tempfile.TemporaryDirectory() as td:
            pack = Path(td) / "local_austin.json"
            pack.write_text(
                json.dumps(
                    {
                        "jurisdictions": [
                            {
                                "code": "US-TX-AUS",
                                "name": "City of Austin Local Amendments",
                                "parent": "US-TX",
                                "adopted_standards": ["Austin Land Dev Code"],
                            }
                        ],
                        "clauses": [
                            {
                                "id": "US-TX-AUS-SOLAR",
                                "jurisdiction": "US-TX-AUS",
                                "discipline": "electrical",
                                "standard": "Austin Energy Solar Ready",
                                "title": "Austin Solar-Ready Conduit Reserve",
                                "summary": "Reserve 1-inch EMT conduit from attic to main service panel.",
                                "details": "New residential builds in Austin Energy territory must include solar-ready conduit.",
                                "formula": "conduit_id >= 25.4 mm",
                                "parameters": {"min_conduit_mm": 25.4},
                                "tags": ["austin", "solar", "conduit"],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            res = self.codes.ingest_pack(pack)
            self.assertEqual(res["clauses_ingested"], 1)
            hits = self.codes.search("solar conduit", jurisdiction="US-TX-AUS")
            self.assertEqual(hits[0]["id"], "US-TX-AUS-SOLAR")


class TestDeterministicSolvers(unittest.TestCase):
    def setUp(self):
        self.solvers = EngineeringSolvers()

    def test_structural_asce7_and_beam(self):
        combos_wind = self.solvers.structural_load_combinations_asce7(dead=100, live=80, wind=60)
        self.assertEqual(combos_wind["governing_max"]["combination"], "LC4_1.2D+1.0W+L+0.5S")
        self.assertAlmostEqual(combos_wind["governing_max"]["value"], 260.0, places=2)

        combos_grav = self.solvers.structural_load_combinations_asce7(dead=100, live=80, wind=30)
        self.assertEqual(combos_grav["governing_max"]["combination"], "LC2_1.2D+1.6L+0.5S")
        self.assertAlmostEqual(combos_grav["governing_max"]["value"], 248.0, places=2)

        # W12x40-like beam: Ix ~ 129e6 mm^4, d ~ 303 mm, 6m span, 20 kN/m
        beam = self.solvers.structural_beam_check(
            span_m=6.0,
            uniform_load_kn_m=20.0,
            material_id="steel_a992",
            moment_of_inertia_mm4=129e6,
            depth_mm=303.0,
        )
        self.assertTrue(beam["overall_pass"])
        self.assertAlmostEqual(beam["max_moment_kn_m"], 90.0, places=2)

    def test_civil_manning_and_terzaghi(self):
        flow = self.solvers.civil_manning_flow(slope=0.01, manning_n=0.013, diameter_m=0.6)
        self.assertGreater(flow["velocity_m_s"], 1.5)
        self.assertGreater(flow["discharge_l_s"], 500.0)

        brg = self.solvers.civil_bearing_capacity_terzaghi(
            footing_width_m=2.0,
            embedment_depth_m=1.0,
            soil_material_id="soil_dense_sand",
            applied_load_kn=1200.0,
        )
        self.assertTrue(brg["pass"])

    def test_electrical_feeder_and_solar_120_rule(self):
        feeder = self.solvers.electrical_feeder_check(
            voltage_v=480.0,
            current_a=100.0,
            one_way_length_m=60.0,
            conductor_area_mm2=53.5,  # ~1/0 AWG Cu
            phases=3,
        )
        self.assertTrue(feeder["voltage_drop_pass"])
        self.assertEqual(feeder["nec_min_design_ampacity_a"], 125.0)

        pv_ok = self.solvers.electrical_solar_busbar_120_check(200, 200, 32)
        self.assertTrue(pv_ok["pass"])
        pv_fail = self.solvers.electrical_solar_busbar_120_check(200, 200, 48)
        self.assertFalse(pv_fail["pass"])
        self.assertIsNotNone(pv_fail["remediation"])

    def test_mechanical_pipe_duct_and_lunar_thermal(self):
        pipe = self.solvers.mechanical_pipe_flow_darcy(flow_rate_l_s=3.0, pipe_id_mm=50.0, length_m=50.0)
        self.assertEqual(pipe["flow_regime"], "turbulent")
        self.assertTrue(pipe["velocity_within_hydronic_guideline"])

        duct = self.solvers.mechanical_duct_sizing(airflow_m3_s=1.2, width_mm=600.0, height_mm=300.0)
        self.assertTrue(duct["aspect_ratio_pass"])
        self.assertTrue(duct["trunk_noise_pass"])

        # Lunar habitat wall with 2.0m sintered regolith + 0.08m silica aerogel in vacuum night (100K)
        lunar_wall = self.solvers.thermal_envelope_and_radiation(
            layers=[
                {"material_id": "insul_aerogel_silica", "thickness_m": 0.08},
                {"material_id": "isru_lunar_sintered_mare", "thickness_m": 2.0},
            ],
            area_m2=100.0,
            t_inside_k=294.0,
            t_outside_k=100.0,
            include_vacuum_radiation_emissivity=0.93,
        )
        self.assertGreater(lunar_wall["total_areal_density_g_cm2"], 450.0)  # GCR shielding met!
        self.assertLess(lunar_wall["heat_flux_w_m2"], 35.0)


class TestRustSpatialHubAndMCP(unittest.TestCase):
    def setUp(self):
        self.hub = SpatialHub()
        self.mcp = OpenDatumMCPServer()

    def test_legacy_rebuild_and_multi_target_exports(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            rebuilt = tdp / "bracket.odir.json"
            rep = self.hub.rebuild(
                str(REPO_ROOT / "examples" / "legacy_bracket.obj"),
                str(rebuilt),
                units="m",
                up="y",
            )
            rr = rep["rebuild_report"]
            self.assertEqual(rr["vertices_before"], 10)
            self.assertEqual(rr["vertices_after"], 8)
            self.assertEqual(rr["degenerate_removed"], 1)
            self.assertEqual(rr["primitives_reconstructed"], 1)

            # Convert to Godot 4, Bevy, glTF, USD, 3MF, DXF
            for fname, target in [
                ("bracket.tscn", "godot"),
                ("bracket.ron", "bevy"),
                ("bracket.gltf", "gltf"),
                ("bracket.usda", "usd"),
                ("bracket.3mf", "3mf"),
                ("bracket.dxf", "dxf"),
            ]:
                out = tdp / fname
                res = self.hub.convert(str(rebuilt), str(out), target=target)
                self.assertEqual(res["status"], "ok")
                self.assertTrue(out.exists() and out.stat().st_size > 50)

            # Verify 3MF is a valid readable ZIP archive with 3D/3dmodel.model!
            with zipfile.ZipFile(tdp / "bracket.3mf", "r") as zf:
                names = zf.namelist()
                self.assertIn("3D/3dmodel.model", names)
                self.assertIn("[Content_Types].xml", names)
                model_xml = zf.read("3D/3dmodel.model").decode("utf-8")
                self.assertIn("<model ", model_xml)

    def test_mep_clash_analysis_and_mcp_protocol(self):
        # Analyze MEP/Structural bay with deliberate duct-vs-girder hard clash
        analysis = self.hub.analyze(str(REPO_ROOT / "examples" / "mep_building.odir.json"))
        self.assertEqual(analysis["clash_report"]["hard_clashes"], 1)

        # Verify MCP JSON-RPC lifecycle
        init_resp = self.mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "opendatum-mcp")

        list_resp = self.mcp.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tool_names = {t["name"] for t in list_resp["result"]["tools"]}
        self.assertIn("spatial_rebuild_legacy", tool_names)
        self.assertIn("materials_compare", tool_names)
        self.assertIn("codes_search", tool_names)
        self.assertIn("solve_structural_beam", tool_names)

        call_resp = self.mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "spatial_analyze_and_clash",
                    "arguments": {"input_path": str(REPO_ROOT / "examples" / "mep_building.odir.json")},
                },
            }
        )
        self.assertFalse(call_resp["result"]["isError"])
        payload = json.loads(call_resp["result"]["content"][0]["text"])
        self.assertEqual(payload["clash_report"]["hard_clashes"], 1)


class TestPLEHarnessCADBridgesAndLiveSync(unittest.TestCase):
    def setUp(self):
        self.hub = SpatialHub()
        self.mcp = OpenDatumMCPServer()

    def test_step_dxf_and_ifc4_roundtrip(self):
        from opendatum.cad_bridges import (
            export_usir_to_ifc4,
            extract_dxf_takeoff,
            inspect_step_file,
        )

        step_info = inspect_step_file(REPO_ROOT / "examples" / "ple_sample.step")
        self.assertEqual(len(step_info["products"]), 2)
        self.assertEqual(step_info["solid_brep_count"], 2)
        self.assertEqual(step_info["assembly_links"], 1)

        dxf_info = extract_dxf_takeoff(REPO_ROOT / "examples" / "ple_sample.dxf")
        self.assertAlmostEqual(dxf_info["total_length_by_layer"]["S-BEAM"], 6.0, places=3)
        self.assertAlmostEqual(dxf_info["total_length_by_layer"]["M-HVAC-SUPPLY"], 5.0, places=3)
        self.assertEqual(len(dxf_info["annotations"]), 1)

        with tempfile.TemporaryDirectory() as td:
            out_ifc = Path(td) / "exported.ifc"
            res = export_usir_to_ifc4(REPO_ROOT / "examples" / "mep_building.odir.json", out_ifc)
            self.assertEqual(res["elements_exported"], 3)
            # Round-trip back into Rust USIR inspector!
            inspected = self.hub.inspect(str(out_ifc))
            self.assertGreaterEqual(inspected["node_count"], 4)  # 3 elements + storey

    def test_human_lock_safe_merge_and_multi_engine_sync(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            src = REPO_ROOT / "examples" / "mep_building.odir.json"
            human_doc = json.loads(src.read_text(encoding="utf-8"))
            agent_doc = json.loads(src.read_text(encoding="utf-8"))

            # Agent tries to move human-locked electrical panel AND lowers duct to fix clash!
            for n in agent_doc["nodes"]:
                if n["id"] == "elec_panel_lp1":
                    n["transform"]["position"] = [99.0, 99.0, 99.0]
                    n["provenance"]["human_locked"] = False
                elif n["id"] == "mech_duct_supply_01":
                    n["parametric"]["start"][1] = 2.6
                    n["parametric"]["end"][1] = 2.6

            human_p = tdp / "human.odir.json"
            agent_p = tdp / "agent.odir.json"
            merged_p = tdp / "merged.odir.json"
            human_p.write_text(json.dumps(human_doc), encoding="utf-8")
            agent_p.write_text(json.dumps(agent_doc), encoding="utf-8")

            mres = self.hub.merge(str(human_p), str(agent_p), str(merged_p))
            self.assertEqual(mres["merge_report"]["preserved_human_locked"], ["elec_panel_lp1"])
            self.assertEqual(len(mres["merge_report"]["conflicts"]), 1)

            merged = json.loads(merged_p.read_text(encoding="utf-8"))
            panel = next(n for n in merged["nodes"] if n["id"] == "elec_panel_lp1")
            self.assertEqual(panel["transform"]["position"], [-2.8, 1.5, -2.2])
            self.assertTrue(panel["provenance"]["human_locked"])

            # Sync merged clash-free model to Godot 4, Bevy, glTF, and OpenUSD in one shot!
            sres = self.hub.sync(
                str(merged_p),
                godot_path=str(tdp / "scene.tscn"),
                bevy_path=str(tdp / "scene.ron"),
                gltf_path=str(tdp / "scene.gltf"),
                usd_path=str(tdp / "scene.usda"),
            )
            self.assertEqual(sres["hard_clashes"], 0)
            self.assertEqual(len(sres["exported"]), 4)

    def test_ple_triage_and_verify_via_mcp(self):
        triage_resp = self.mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {
                    "name": "ple_workspace_triage",
                    "arguments": {"workspace_dir": str(REPO_ROOT / "examples")},
                },
            }
        )
        self.assertFalse(triage_resp["result"]["isError"])
        triage = json.loads(triage_resp["result"]["content"][0]["text"])
        self.assertGreaterEqual(len(triage["spatial_summaries"]), 3)
        disc_names = {d["discipline"] for d in triage["detected_disciplines"]}
        self.assertTrue({"structural", "mechanical"}.issubset(disc_names))

        # Verify deliverables catches the deliberate clash in examples/mep_building.odir.json
        ver_resp = self.mcp.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "tools/call",
                "params": {
                    "name": "ple_verify_deliverables",
                    "arguments": {"workspace_dir": str(REPO_ROOT / "examples")},
                },
            }
        )
        ver = json.loads(ver_resp["result"]["content"][0]["text"])
        self.assertFalse(ver["overall_pass"])
        self.assertGreaterEqual(ver["error_count"], 1)


if __name__ == "__main__":
    unittest.main()
