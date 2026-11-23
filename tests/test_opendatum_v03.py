"""Tests for OpenDatum v0.3.0 additions:
- Visual SVG + PNG Renderer with Clash Highlighting
- Zero-dep XLSX & CSV Spreadsheet Formula Auditor
- Project Spec Auto-Ingestion into SQLite FTS5 CodesEngine
- AISC Optimal Lightest W-Shape Selector & NEC Conductor/Conduit Selector
- Exact 2D Direct-Stiffness Matrix Truss FEA Solver & ASHRAE Psychrometrics
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from opendatum import (
    CodesEngine,
    StandardTables,
    audit_spreadsheet,
    ingest_spec_document_to_codes,
    render_spatial_views,
    solve_2d_truss_fea,
    solve_psychrometrics_ashrae,
)
from opendatum.mcp_server import OpenDatumMCPServer


def _make_minimal_xlsx(path: Path, cell_xml: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{cell_xml}</sheetData></worksheet>",
        )


class TestOpenDatumV03(unittest.TestCase):
    def test_visual_renderer_emits_valid_svg_and_png(self):
        with tempfile.TemporaryDirectory() as td:
            res = render_spatial_views(
                REPO_ROOT / "examples" / "mep_building.odir.json",
                td,
                view="both",
            )
            self.assertEqual(res["clashes_highlighted"], 1)
            for key in ("plan_xz_png", "elevation_xy_png"):
                png_bytes = Path(res["files"][key]).read_bytes()
                self.assertEqual(png_bytes[:8], b"\x89PNG\r\n\x1a\n")
                self.assertGreater(len(png_bytes), 500)
            svg_txt = Path(res["files"]["elevation_xy_svg"]).read_text(encoding="utf-8")
            self.assertIn("W12x40_Primary_Girder", svg_txt)
            self.assertIn("#e61e1e", svg_txt)  # red clash callout

    def test_spreadsheet_auditor_catches_excel_errors(self):
        with tempfile.TemporaryDirectory() as td:
            good_xlsx = Path(td) / "boq_good.xlsx"
            _make_minimal_xlsx(
                good_xlsx,
                '<row r="1"><c r="A1"><v>10</v></c><c r="B1"><f>A1*2</f><v>20</v></c></row>',
            )
            good_rep = audit_spreadsheet(good_xlsx)
            self.assertTrue(good_rep["pass"])
            self.assertEqual(good_rep["total_formulas"], 1)

            bad_xlsx = Path(td) / "boq_broken.xlsx"
            _make_minimal_xlsx(
                bad_xlsx,
                '<row r="1"><c r="A1" t="e"><f>10/0</f><v>#DIV/0!</v></c></row>',
            )
            bad_rep = audit_spreadsheet(bad_xlsx)
            self.assertFalse(bad_rep["pass"])
            self.assertEqual(bad_rep["error_cells"][0]["cell"], "A1")
            self.assertEqual(bad_rep["error_cells"][0]["value"], "#DIV/0!")

    def test_spec_auto_ingestion_into_codes_engine(self):
        codes = CodesEngine()
        with tempfile.TemporaryDirectory() as td:
            spec = Path(td) / "project_criteria.md"
            spec.write_text(
                "# 1.1 Seismic Equipment Bracing\n"
                "All rooftop air handling units exceeding 180 kg must include seismic isolation curbs.\n\n"
                "# 1.2 Backup Generator Fuel Reserve\n"
                "Provide minimum 72-hour diesel storage for Tier III mission-critical power loads.\n",
                encoding="utf-8",
            )
            res = ingest_spec_document_to_codes(spec, codes, jurisdiction_code="PROJECT", discipline="mechanical")
            self.assertEqual(res["clauses_indexed"], 2)
            hits = codes.search("72-hour diesel generator", jurisdiction="PROJECT")
            self.assertGreater(len(hits), 0)
            self.assertIn("PROJECT-PROJECT_CRITERIA", hits[0]["id"])

    def test_aisc_beam_and_nec_feeder_selectors(self):
        tables = StandardTables()
        beam_sel = tables.select_lightest_steel_beam(span_m=6.0, uniform_load_kn_m=20.0, max_depth_mm=360.0)
        self.assertIsNotNone(beam_sel["recommended"])
        self.assertLessEqual(beam_sel["recommended"]["depth_mm"], 360.0)
        self.assertLessEqual(beam_sel["recommended"]["strength_utilization"], 1.0)
        self.assertLessEqual(beam_sel["recommended"]["deflection_utilization"], 1.0)

        nec_sel = tables.select_nec_feeder_and_conduit(
            voltage_v=480.0,
            current_a=100.0,
            one_way_length_m=60.0,
            phases=3,
            conductor_count_in_conduit=4,
            ambient_temp_c=35.0,
        )
        self.assertTrue(nec_sel["pass"])
        self.assertLessEqual(nec_sel["selected_conductor"]["voltage_drop_pct"], 3.0)
        self.assertLessEqual(nec_sel["selected_emt_conduit"]["fill_pct"], 40.0)

    def test_2d_truss_fea_exact_equilibrium_and_psychrometrics(self):
        # Classic symmetric 3-node triangular truss: span 4m, height 2m, apex downward load 100 kN
        # Analytical solution: Ry1 = Ry3 = +50 kN; diagonal compression = -50*sqrt(2) = -70.71 kN; bottom chord tension = +50 kN
        fea = solve_2d_truss_fea(
            nodes=[
                {"id": "A", "x": 0.0, "y": 0.0, "fix_x": True, "fix_y": True},
                {"id": "B", "x": 4.0, "y": 0.0, "fix_x": False, "fix_y": True},
                {"id": "C", "x": 2.0, "y": 2.0, "fix_x": False, "fix_y": False},
            ],
            elements=[
                {"id": "bottom", "n1": "A", "n2": "B", "area_mm2": 2000.0, "material_id": "steel_a992"},
                {"id": "left_diag", "n1": "A", "n2": "C", "area_mm2": 2000.0, "material_id": "steel_a992"},
                {"id": "right_diag", "n1": "B", "n2": "C", "area_mm2": 2000.0, "material_id": "steel_a992"},
            ],
            loads=[{"node": "C", "fx_n": 0.0, "fy_n": -100_000.0}],
        )
        self.assertTrue(fea["overall_pass"])
        self.assertAlmostEqual(fea["support_reactions"]["A"]["ry_kn"], 50.0, places=2)
        self.assertAlmostEqual(fea["support_reactions"]["B"]["ry_kn"], 50.0, places=2)
        by_id = {m["id"]: m for m in fea["members"]}
        self.assertAlmostEqual(by_id["bottom"]["axial_force_kn"], 50.0, places=2)
        self.assertAlmostEqual(by_id["left_diag"]["axial_force_kn"], -70.7107, places=2)
        self.assertAlmostEqual(by_id["right_diag"]["axial_force_kn"], -70.7107, places=2)

        # Psychrometrics at 25C, 50% RH sea level -> W ~ 0.0099 kg/kg, h ~ 50.3 kJ/kg, Tdp ~ 13.9C
        psy = solve_psychrometrics_ashrae(25.0, 50.0)
        self.assertAlmostEqual(psy["humidity_ratio_kg_kg"], 0.0099, places=3)
        self.assertAlmostEqual(psy["enthalpy_kj_kg"], 50.3, delta=0.5)
        self.assertAlmostEqual(psy["dew_point_c"], 13.9, delta=0.4)

    def test_mcp_exposes_all_v03_tools(self):
        mcp = OpenDatumMCPServer()
        resp = mcp.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        names = {t["name"] for t in resp["result"]["tools"]}
        expected = {
            "spatial_render_views",
            "doc_audit_spreadsheet",
            "doc_ingest_spec_to_codes",
            "table_select_steel_beam",
            "table_select_nec_feeder",
            "solve_2d_truss_fea",
            "solve_psychrometrics",
        }
        self.assertTrue(expected.issubset(names))
        self.assertGreaterEqual(len(names), 35)


if __name__ == "__main__":
    unittest.main()
