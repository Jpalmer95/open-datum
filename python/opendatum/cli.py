"""Unified OpenDatum CLI for Materials, Codes, Engineering Solvers, Spatial Hub, and MCP Server."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .codes import CodesEngine
from .materials import MaterialsDB
from .mcp_server import OpenDatumMCPServer
from .solvers import EngineeringSolvers
from .spatial import SpatialHub
from .units import convert_unit


def _dump(obj) -> None:
    print(json.dumps(obj, indent=2))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="opendatum",
        description="OpenDatum — Universal Spatial Hub & First-Principles Physical Engineering CLI",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # MCP server
    sub.add_parser("mcp", help="Run the offline-first JSON-RPC 2.0 MCP server over stdio")

    # Units
    p_unit = sub.add_parser("units", help="Convert physical quantities between SI and Imperial")
    p_unit.add_argument("value", type=float)
    p_unit.add_argument("from_unit")
    p_unit.add_argument("to_unit")

    # Materials
    p_mat = sub.add_parser("materials", help="Query and compare first-principles materials")
    mat_sub = p_mat.add_subparsers(dest="mat_cmd", required=True)
    p_ms = mat_sub.add_parser("search")
    p_ms.add_argument("query", nargs="?", default="")
    p_ms.add_argument("--category")
    p_ms.add_argument("--domain")
    p_ms.add_argument("--vacuum", action="store_true")
    p_mg = mat_sub.add_parser("get")
    p_mg.add_argument("material_id")
    p_mc = mat_sub.add_parser("compare")
    p_mc.add_argument("material_ids", nargs="+")
    p_mc.add_argument("--env", default="earth_sea_level")

    # Codes
    p_cod = sub.add_parser("codes", help="Jurisdiction-scoped progressive-disclosure codes search")
    cod_sub = p_cod.add_subparsers(dest="cod_cmd", required=True)
    p_cr = cod_sub.add_parser("resolve")
    p_cr.add_argument("jurisdiction")
    p_cr.add_argument("--discipline")
    p_cs = cod_sub.add_parser("search")
    p_cs.add_argument("query")
    p_cs.add_argument("--discipline")
    p_cs.add_argument("--jurisdiction")
    p_cg = cod_sub.add_parser("get")
    p_cg.add_argument("clause_id")
    p_ci = cod_sub.add_parser("ingest")
    p_ci.add_argument("pack_path")

    # Solvers
    p_sol = sub.add_parser("solve", help="Run deterministic first-principles engineering solvers")
    sol_sub = p_sol.add_subparsers(dest="sol_cmd", required=True)

    p_beam = sol_sub.add_parser("beam")
    p_beam.add_argument("--span-m", type=float, required=True)
    p_beam.add_argument("--load-kn-m", type=float, required=True)
    p_beam.add_argument("--material", required=True)
    p_beam.add_argument("--ix-mm4", type=float, required=True)
    p_beam.add_argument("--depth-mm", type=float, required=True)
    p_beam.add_argument("--env", default="earth_sea_level")

    p_elec = sol_sub.add_parser("feeder")
    p_elec.add_argument("--voltage", type=float, required=True)
    p_elec.add_argument("--current", type=float, required=True)
    p_elec.add_argument("--length-m", type=float, required=True)
    p_elec.add_argument("--area-mm2", type=float, required=True)
    p_elec.add_argument("--phases", type=int, default=3)

    p_pipe = sol_sub.add_parser("pipe")
    p_pipe.add_argument("--flow-ls", type=float, required=True)
    p_pipe.add_argument("--id-mm", type=float, required=True)
    p_pipe.add_argument("--length-m", type=float, required=True)

    # Spatial hub wrapper
    p_sp = sub.add_parser("spatial", help="Invoke Rust Universal Spatial Hub (inspect/convert/rebuild/analyze)")
    sp_sub = p_sp.add_subparsers(dest="sp_cmd", required=True)
    p_si = sp_sub.add_parser("inspect")
    p_si.add_argument("input_path")
    p_sc = sp_sub.add_parser("convert")
    p_sc.add_argument("input_path")
    p_sc.add_argument("output_path")
    p_sc.add_argument("--target")
    p_sr = sp_sub.add_parser("rebuild")
    p_sr.add_argument("input_path")
    p_sr.add_argument("output_path")
    p_sr.add_argument("--units", default="m")
    p_sr.add_argument("--up", default="y")
    p_sa = sp_sub.add_parser("analyze")
    p_sa.add_argument("input_path")
    p_sa.add_argument("--clearance", type=float, default=0.05)

    args = parser.parse_args(argv)

    if args.cmd == "mcp":
        OpenDatumMCPServer().serve_stdio()
        return 0
    if args.cmd == "units":
        _dump(convert_unit(args.value, args.from_unit, args.to_unit))
        return 0
    if args.cmd == "materials":
        db = MaterialsDB()
        if args.mat_cmd == "search":
            _dump(db.search(args.query, category=args.category, domain=args.domain, vacuum_only=args.vacuum))
        elif args.mat_cmd == "get":
            _dump(db.get(args.material_id))
        elif args.mat_cmd == "compare":
            _dump(db.compare(args.material_ids, environment=args.env))
        return 0
    if args.cmd == "codes":
        eng = CodesEngine()
        if args.cod_cmd == "resolve":
            _dump(eng.resolve_jurisdiction(args.jurisdiction, args.discipline))
        elif args.cod_cmd == "search":
            _dump(eng.search(args.query, discipline=args.discipline, jurisdiction=args.jurisdiction))
        elif args.cod_cmd == "get":
            _dump(eng.get_clause(args.clause_id))
        elif args.cod_cmd == "ingest":
            _dump(eng.ingest_pack(Path(args.pack_path)))
        return 0
    if args.cmd == "solve":
        s = EngineeringSolvers()
        if args.sol_cmd == "beam":
            _dump(
                s.structural_beam_check(
                    span_m=args.span_m,
                    uniform_load_kn_m=args.load_kn_m,
                    material_id=args.material,
                    moment_of_inertia_mm4=args.ix_mm4,
                    depth_mm=args.depth_mm,
                    environment=args.env,
                )
            )
        elif args.sol_cmd == "feeder":
            _dump(
                s.electrical_feeder_check(
                    voltage_v=args.voltage,
                    current_a=args.current,
                    one_way_length_m=args.length_m,
                    conductor_area_mm2=args.area_mm2,
                    phases=args.phases,
                )
            )
        elif args.sol_cmd == "pipe":
            _dump(
                s.mechanical_pipe_flow_darcy(
                    flow_rate_l_s=args.flow_ls,
                    pipe_id_mm=args.id_mm,
                    length_m=args.length_m,
                )
            )
        return 0
    if args.cmd == "spatial":
        hub = SpatialHub()
        if args.sp_cmd == "inspect":
            _dump(hub.inspect(args.input_path))
        elif args.sp_cmd == "convert":
            _dump(hub.convert(args.input_path, args.output_path, target=args.target))
        elif args.sp_cmd == "rebuild":
            _dump(hub.rebuild(args.input_path, args.output_path, units=args.units, up=args.up))
        elif args.sp_cmd == "analyze":
            _dump(hub.analyze(args.input_path, clearance=args.clearance))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
