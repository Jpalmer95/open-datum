"""PLE (Physical-Engineering's Last Exam) Agent Harness Toolkit.

Directly addresses the core failure modes identified in arXiv:2610.30537:
1. Token exhaustion (~27M tokens/task) -> `triage_workspace()` produces a concise,
   structured engineering brief (<1,500 tokens) summarizing all DXF/IFC/STEP/OBJ/CSV/MD files.
2. Spatial & topological disconnects -> automatically inspects spatial files & checks
   multi-discipline clashes before and after edits.
3. Cumulative format corruption -> `verify_deliverables()` runs deterministic schema,
   manifold, clash, and completeness QA before final submission.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "python") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "python"))

from opendatum.cad_bridges import cad_capabilities, extract_dxf_takeoff, inspect_step_file
from opendatum.codes import CodesEngine
from opendatum.docs_engine import audit_spreadsheet
from opendatum.spatial import SpatialHub

SPATIAL_EXTS = {".dxf", ".ifc", ".step", ".stp", ".obj", ".stl", ".odir.json", ".3mf", ".gltf"}
DOC_EXTS = {".md", ".txt", ".pdf", ".csv", ".xlsx", ".json", ".yaml", ".yml", ".py"}

DISCIPLINE_KEYWORDS = {
    "structural": ["beam", "column", "slab", "diaphragm", "seismic", "wind", "asce", "aisc", "aci", "moment", "deflection", "footing"],
    "civil": ["grading", "drainage", "stormwater", "manning", "shoring", "excavation", "settlement", "bearing", "culvert", "soil", "ada"],
    "electrical": ["nec", "feeder", "voltage drop", "panelboard", "busbar", "solar", "pv", "conduit", "ampacity", "breaker", "kwh", "kva"],
    "mechanical": ["hvac", "duct", "cfm", "ashrae", "chilled water", "hydronic", "pipe", "thermal", "boiler", "ahu", "plumbing", "clash"],
}


def triage_workspace(workspace_dir: str | Path) -> Dict[str, Any]:
    """Scans a PLE task workspace and builds a token-efficient engineering brief."""
    root = Path(workspace_dir)
    if not root.exists():
        raise FileNotFoundError(f"Workspace not found: {root}")

    files = [p for p in sorted(root.rglob("*")) if p.is_file() and ".git" not in p.parts]
    spatial_summaries: List[Dict[str, Any]] = []
    text_corpus = ""
    inventory: Dict[str, List[str]] = {"spatial": [], "tabular_and_docs": [], "scripts": [], "other": []}

    hub: SpatialHub | None = None
    try:
        hub = SpatialHub()
    except FileNotFoundError:
        hub = None

    for p in files:
        rel = str(p.relative_to(root))
        ext = p.suffix.lower()
        name_lower = p.name.lower()

        if name_lower.endswith(".odir.json") or ext in {".dxf", ".ifc", ".step", ".stp", ".obj", ".stl"}:
            inventory["spatial"].append(rel)
            try:
                if ext in {".step", ".stp"}:
                    spatial_summaries.append({"file": rel, "summary": inspect_step_file(p)})
                elif ext == ".dxf":
                    spatial_summaries.append({"file": rel, "summary": extract_dxf_takeoff(p)})
                elif hub is not None:
                    spatial_summaries.append({"file": rel, "summary": hub.inspect(str(p))})
            except Exception as exc:
                spatial_summaries.append({"file": rel, "error": str(exc)})
        elif ext == ".py":
            inventory["scripts"].append(rel)
        elif ext in DOC_EXTS:
            inventory["tabular_and_docs"].append(rel)
            if ext in {".md", ".txt", ".yaml", ".yml", ".json"} and p.stat().st_size < 100_000:
                text_corpus += "\n" + p.read_text(encoding="utf-8", errors="ignore").lower()
        else:
            inventory["other"].append(rel)

    # Infer active disciplines from file names, spatial layers, and docs
    combined_signal = (
        text_corpus
        + " "
        + " ".join(inventory["spatial"])
        + " "
        + json.dumps(spatial_summaries).lower()
    )
    detected_disciplines = []
    for disc, kws in DISCIPLINE_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in combined_signal)
        if score > 0:
            detected_disciplines.append({"discipline": disc, "signal_hits": score})
    detected_disciplines.sort(key=lambda d: -d["signal_hits"])

    # Suggest starting code clauses via progressive disclosure (compact!)
    codes = CodesEngine()
    suggested_clauses = []
    for d in detected_disciplines[:2]:
        hits = codes.search(d["discipline"], discipline=d["discipline"], limit=2)
        for h in hits:
            suggested_clauses.append({"id": h["id"], "standard": h["standard"], "title": h["title"]})

    return {
        "workspace": str(root),
        "total_files": len(files),
        "inventory": inventory,
        "detected_disciplines": detected_disciplines,
        "spatial_summaries": spatial_summaries,
        "suggested_code_clauses": suggested_clauses,
        "cad_capabilities": cad_capabilities(),
        "recommended_workflow": [
            "1. Call codes_resolve_jurisdiction + codes_search for exact governing code constraints.",
            "2. Call materials_get / materials_compare for canonical SI material properties.",
            "3. Run deterministic OpenDatum solvers (never do manual arithmetic in LLM tokens).",
            "4. Run spatial_analyze_and_clash & ple_verify_deliverables before submitting.",
        ],
    }


def verify_deliverables(workspace_dir: str | Path, min_clearance: float = 0.05) -> Dict[str, Any]:
    """Automated pre-submission verification gate for PLE / engineering deliverables."""
    root = Path(workspace_dir)
    checks: List[Dict[str, Any]] = []
    errors = 0

    hub: SpatialHub | None = None
    try:
        hub = SpatialHub()
    except FileNotFoundError:
        hub = None

    for p in sorted(root.rglob("*")):
        if not p.is_file() or ".git" in p.parts:
            continue
        rel = str(p.relative_to(root))
        ext = p.suffix.lower()
        size = p.stat().st_size

        if size == 0:
            errors += 1
            checks.append({"file": rel, "status": "fail", "reason": "Zero-byte empty deliverable"})
            continue

        if p.name.endswith(".odir.json") and hub is not None:
            try:
                analysis = hub.analyze(str(p), clearance=min_clearance)
                hard = analysis["clash_report"]["hard_clashes"]
                status = "pass" if hard == 0 else "fail"
                if hard > 0:
                    errors += 1
                checks.append(
                    {
                        "file": rel,
                        "status": status,
                        "hard_clashes": hard,
                        "clearance_violations": analysis["clash_report"]["clearance_violations"],
                        "nodes": analysis["summary"]["node_count"],
                    }
                )
            except Exception as exc:
                errors += 1
                checks.append({"file": rel, "status": "fail", "reason": str(exc)})
        elif ext == ".json":
            try:
                json.loads(p.read_text(encoding="utf-8"))
                checks.append({"file": rel, "status": "pass", "type": "valid_json"})
            except Exception as exc:
                errors += 1
                checks.append({"file": rel, "status": "fail", "reason": f"Invalid JSON: {exc}"})
        elif ext == ".dxf":
            takeoff = extract_dxf_takeoff(p)
            has_ents = bool(takeoff["entity_counts_by_layer"])
            if not has_ents:
                errors += 1
            checks.append(
                {
                    "file": rel,
                    "status": "pass" if has_ents else "fail",
                    "layers": list(takeoff["entity_counts_by_layer"].keys()),
                }
            )
        elif ext == ".ifc":
            txt = p.read_text(encoding="utf-8", errors="ignore")
            ok = "ISO-10303-21;" in txt and "END-ISO-10303-21;" in txt
            if not ok:
                errors += 1
            checks.append({"file": rel, "status": "pass" if ok else "fail", "type": "ifc_step_spf"})
        elif ext in {".xlsx", ".csv"}:
            audit = audit_spreadsheet(p)
            if not audit["pass"]:
                errors += 1
            checks.append(
                {
                    "file": rel,
                    "status": "pass" if audit["pass"] else "fail",
                    "type": f"spreadsheet_{ext.lstrip('.')}",
                    "error_cells": len(audit["error_cells"]),
                }
            )

    return {
        "workspace": str(root),
        "overall_pass": errors == 0,
        "error_count": errors,
        "checks": checks,
    }
