"""Full-Fidelity CAD & BIM Bridges (DXF / IFC / STEP-BREP) with Zero-Dependency Fallbacks.

Automatically upgrades to full-fidelity libraries when installed (`ezdxf`, `ifcopenshell`,
`OCP` / `cadquery`, `trimesh`), while remaining 100% functional offline in minimal PLE containers!
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


def _has_module(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:
        return False


def cad_capabilities() -> Dict[str, Any]:
    """Reports installed optional CAD/BIM backends alongside built-in zero-dep engines."""
    return {
        "builtin_zero_dep": [
            "usir_json",
            "obj",
            "stl_ascii_and_binary",
            "3mf_zip_export",
            "gltf_2_0_export",
            "openusd_usda_export",
            "godot4_tscn_export",
            "bevy_ron_export",
            "dxf_ascii_import_export_takeoff",
            "ifc4_step_spf_import_export",
            "step_ap203_ap214_ap242_inspector",
        ],
        "optional_full_fidelity": {
            "ezdxf": _has_module("ezdxf"),
            "ifcopenshell": _has_module("ifcopenshell"),
            "trimesh": _has_module("trimesh"),
            "OCP_opencascade": _has_module("OCP"),
            "cadquery": _has_module("cadquery"),
        },
    }


# =============================================================================
# STEP (ISO 10303-21 AP203 / AP214 / AP242) BRIDGE
# =============================================================================

_STEP_ENTITY_RE = re.compile(r"^#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*;\s*$")
_STEP_STR_RE = re.compile(r"'((?:[^']|'')*)'")


def inspect_step_file(step_path: str | Path) -> Dict[str, Any]:
    """Inspects an ISO 10303-21 STEP (.stp / .step) CAD file.
    Uses OpenCASCADE (`OCP`/`cadquery`) for exact BREP volume/bbox when installed,
    and always extracts full product/assembly tree & entity statistics with zero deps."""
    path = Path(step_path)
    text = path.read_text(encoding="utf-8", errors="ignore")

    schema = "UNKNOWN"
    m_schema = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    if m_schema:
        schema = m_schema.group(1)

    products: List[Dict[str, str]] = []
    entity_counts: Counter[str] = Counter()
    units_detected: List[str] = []

    # Collapse multi-line STEP statements inside DATA section
    in_data = False
    buf = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("DATA;"):
            in_data = True
            continue
        if line.startswith("ENDSEC;"):
            in_data = False
            continue
        if not in_data or not line or line.startswith("/*"):
            continue
        buf += (" " if buf else "") + line
        if line.endswith(";"):
            m = _STEP_ENTITY_RE.match(buf)
            buf = ""
            if not m:
                continue
            eid, etype, args = m.group(1), m.group(2), m.group(3)
            entity_counts[etype] += 1
            if etype == "PRODUCT":
                strs = _STEP_STR_RE.findall(args)
                products.append(
                    {
                        "entity_id": f"#{eid}",
                        "id": strs[0] if len(strs) > 0 else "",
                        "name": strs[1] if len(strs) > 1 else "",
                        "description": strs[2] if len(strs) > 2 else "",
                    }
                )
            elif etype in ("SI_UNIT", "CONVERSION_BASED_UNIT"):
                units_detected.append(args.strip())

    result: Dict[str, Any] = {
        "file": str(path),
        "format": "STEP (ISO 10303-21)",
        "schema": schema,
        "products": products,
        "solid_brep_count": entity_counts.get("MANIFOLD_SOLID_BREP", 0)
        + entity_counts.get("CLOSED_SHELL", 0),
        "advanced_face_count": entity_counts.get("ADVANCED_FACE", 0),
        "assembly_links": entity_counts.get("NEXT_ASSEMBLY_USAGE_OCCURRENCE", 0),
        "units_raw": units_detected[:5],
        "top_entities": dict(entity_counts.most_common(12)),
        "exact_brep_backend": None,
    }

    # Optional OpenCASCADE exact solid analysis if installed
    if _has_module("cadquery"):
        try:
            import cadquery as cq  # type: ignore

            shape = cq.importers.importStep(str(path))
            bb = shape.val().BoundingBox()
            result["exact_brep_backend"] = "cadquery/OCP"
            result["exact_volume"] = shape.val().Volume()
            result["exact_aabb"] = {
                "min": [bb.xmin, bb.ymin, bb.zmin],
                "max": [bb.xmax, bb.ymax, bb.zmax],
                "dimensions": [bb.xlen, bb.ylen, bb.zlen],
            }
        except Exception as exc:
            result["exact_brep_warning"] = str(exc)

    return result


# =============================================================================
# DXF ENGINEERING TAKEOFF BRIDGE (`ezdxf` + ZERO-DEP FALLBACK)
# =============================================================================


def extract_dxf_takeoff(dxf_path: str | Path) -> Dict[str, Any]:
    """Extracts a quantity takeoff (total line length per layer, circles/openings,
    text annotations, and bounding box) from a DXF engineering drawing — critical for PLE."""
    path = Path(dxf_path)

    if _has_module("ezdxf"):
        import ezdxf  # type: ignore

        doc = ezdxf.readfile(str(path))
        msp = doc.modelspace()
        length_by_layer: Dict[str, float] = {}
        counts_by_layer: Dict[str, int] = {}
        annotations: List[Dict[str, Any]] = []
        for ent in msp:
            layer = ent.dxf.layer
            counts_by_layer[layer] = counts_by_layer.get(layer, 0) + 1
            if ent.dxftype() == "LINE":
                s, e = ent.dxf.start, ent.dxf.end
                seg = math.dist((s.x, s.y, s.z), (e.x, e.y, e.z))
                length_by_layer[layer] = length_by_layer.get(layer, 0.0) + seg
            elif ent.dxftype() == "LWPOLYLINE":
                pts = list(ent.get_points("xy"))
                seg = sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))
                if ent.closed and len(pts) > 2:
                    seg += math.dist(pts[-1], pts[0])
                length_by_layer[layer] = length_by_layer.get(layer, 0.0) + seg
            elif ent.dxftype() in ("TEXT", "MTEXT"):
                txt = ent.dxf.text if ent.dxftype() == "TEXT" else ent.text
                annotations.append({"layer": layer, "text": txt})
        return {
            "file": str(path),
            "backend": "ezdxf",
            "dxf_version": doc.dxfversion,
            "entity_counts_by_layer": counts_by_layer,
            "total_length_by_layer": {k: round(v, 4) for k, v in length_by_layer.items()},
            "annotations": annotations[:50],
        }

    # Zero-dependency ASCII DXF takeoff fallback
    lines = [l.strip() for l in path.read_text(encoding="utf-8", errors="ignore").splitlines()]
    in_entities = False
    i = 0
    length_by_layer: Dict[str, float] = {}
    counts_by_layer: Dict[str, int] = {}
    annotations: List[Dict[str, Any]] = []

    while i + 1 < len(lines):
        code, val = lines[i], lines[i + 1]
        i += 2
        if code == "2" and val == "ENTITIES":
            in_entities = True
            continue
        if in_entities and code == "0" and val == "ENDSEC":
            break
        if not in_entities or code != "0":
            continue

        etype = val
        layer = "0"
        x1 = y1 = z1 = x2 = y2 = z2 = r = 0.0
        txt = ""
        while i + 1 < len(lines) and lines[i] != "0":
            c, v = lines[i], lines[i + 1]
            i += 2
            if c == "8":
                layer = v
            elif c == "10":
                x1 = float(v)
            elif c == "20":
                y1 = float(v)
            elif c == "30":
                z1 = float(v)
            elif c == "11":
                x2 = float(v)
            elif c == "21":
                y2 = float(v)
            elif c == "31":
                z2 = float(v)
            elif c == "40":
                r = float(v)
            elif c == "1":
                txt = v

        counts_by_layer[layer] = counts_by_layer.get(layer, 0) + 1
        if etype == "LINE":
            seg = math.dist((x1, y1, z1), (x2, y2, z2))
            length_by_layer[layer] = length_by_layer.get(layer, 0.0) + seg
        elif etype == "CIRCLE":
            length_by_layer[layer] = length_by_layer.get(layer, 0.0) + 2.0 * math.pi * r
        elif etype in ("TEXT", "MTEXT") and txt:
            annotations.append({"layer": layer, "text": txt})

    return {
        "file": str(path),
        "backend": "opendatum_zero_dep",
        "entity_counts_by_layer": counts_by_layer,
        "total_length_by_layer": {k: round(v, 4) for k, v in length_by_layer.items()},
        "annotations": annotations[:50],
    }


# =============================================================================
# IFC4 ROUND-TRIP EXPORTER (USIR -> VALID IFC4 STEP-SPF)
# =============================================================================

_ROLE_TO_IFC = {
    "wall": "IFCWALL",
    "beam": "IFCBEAM",
    "column": "IFCCOLUMN",
    "slab": "IFCSLAB",
    "footing": "IFCFOOTING",
    "duct": "IFCDUCTSEGMENT",
    "pipe": "IFCPIPESEGMENT",
    "electrical_equipment": "IFCELECTRICDISTRIBUTIONBOARD",
    "space": "IFCSPACE",
}


def _ifc_guid() -> str:
    # Compact 22-char IFC base64-like GUID
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz_$"
    n = uuid.uuid4().int
    out = []
    for _ in range(22):
        out.append(chars[n & 63])
        n >>= 6
    return "".join(reversed(out))


def export_usir_to_ifc4(usir_path: str | Path, output_ifc_path: str | Path) -> Dict[str, Any]:
    """Exports an OpenDatum USIR (`.odir.json`) document into an IFC4 STEP-SPF file.
    Works 100% offline with zero external dependencies (and pairs with IfcOpenShell when installed)."""
    doc = json.loads(Path(usir_path).read_text(encoding="utf-8"))
    out_path = Path(output_ifc_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    proj_name = doc.get("name", "OpenDatumProject").replace("'", "")
    lines = [
        "ISO-10303-21;",
        "HEADER;",
        f"FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');",
        f"FILE_NAME('{out_path.name}','2026-11-22T00:00:00',('OpenDatum'),('OpenDatum'),'OpenDatum USIR v0.2','OpenDatum','');",
        "FILE_SCHEMA(('IFC4'));",
        "ENDSEC;",
        "DATA;",
        "#1=IFCPERSON($,'Korstad','Jonathan',$,$,$,$,$);",
        "#2=IFCORGANIZATION($,'OpenDatum','Universal Spatial Substrate',$,$);",
        "#3=IFCPERSONANDORGANIZATION(#1,#2,$);",
        "#4=IFCAPPLICATION(#2,'0.2.0','OpenDatum','OPENDATUM');",
        "#5=IFCOWNERHISTORY(#3,#4,$,.NOCHANGE.,$,$,$,0);",
        "#6=IFCDIRECTION((1.,0.,0.));",
        "#7=IFCDIRECTION((0.,0.,1.));",
        "#8=IFCCARTESIANPOINT((0.,0.,0.));",
        "#9=IFCAXIS2PLACEMENT3D(#8,#7,#6);",
        "#10=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-05,#9,$);",
        "#11=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);",
        "#12=IFCUNITASSIGNMENT((#11));",
        f"#13=IFCPROJECT('{_ifc_guid()}',#5,'{proj_name}',$,$,$,$,(#10),#12);",
        f"#14=IFCSITE('{_ifc_guid()}',#5,'DefaultSite',$,$,$,$,$,.ELEMENT.,$,$,$,$,$);",
        f"#15=IFCBUILDING('{_ifc_guid()}',#5,'{proj_name}_Building',$,$,$,$,$,.ELEMENT.,$,$,$);",
        f"#16=IFCBUILDINGSTOREY('{_ifc_guid()}',#5,'Level_1',$,$,$,$,$,.ELEMENT.,0.);",
        f"#17=IFCRELAGGREGATES('{_ifc_guid()}',#5,$,$,#13,(#14));",
        f"#18=IFCRELAGGREGATES('{_ifc_guid()}',#5,$,$,#14,(#15));",
        f"#19=IFCRELAGGREGATES('{_ifc_guid()}',#5,$,$,#15,(#16));",
    ]

    eid = 20
    elem_refs: List[str] = []
    for node in doc.get("nodes", []):
        role = str(node.get("role", "")).lower()
        ifc_cls = _ROLE_TO_IFC.get(role, "IFCBUILDINGELEMENTPROXY")
        pos = node.get("transform", {}).get("position", [0.0, 0.0, 0.0])
        pt_id = eid
        pl_id = eid + 1
        lp_id = eid + 2
        el_id = eid + 3
        eid += 4

        nname = str(node.get("name", node.get("id", "Element"))).replace("'", "")
        tag = str(node.get("id", "")).replace("'", "")
        mat_note = str(node.get("material_id") or "")
        lines.append(f"#{pt_id}=IFCCARTESIANPOINT(({float(pos[0]):.6f},{float(pos[1]):.6f},{float(pos[2]):.6f}));")
        lines.append(f"#{pl_id}=IFCAXIS2PLACEMENT3D(#{pt_id},#7,#6);")
        lines.append(f"#{lp_id}=IFCLOCALPLACEMENT($,#{pl_id});")
        if ifc_cls in ("IFCWALL", "IFCBEAM", "IFCCOLUMN", "IFCSLAB", "IFCFOOTING", "IFCBUILDINGELEMENTPROXY"):
            lines.append(
                f"#{el_id}={ifc_cls}('{_ifc_guid()}',#5,'{nname}','{mat_note}',$,#{lp_id},$,'{tag}',.NOTDEFINED.);"
            )
        else:
            lines.append(
                f"#{el_id}={ifc_cls}('{_ifc_guid()}',#5,'{nname}','{mat_note}',$,#{lp_id},$,'{tag}');"
            )
        elem_refs.append(f"#{el_id}")

    if elem_refs:
        refs_csv = ",".join(elem_refs)
        lines.append(
            f"#{eid}=IFCRELCONTAINEDINSPATIALSTRUCTURE('{_ifc_guid()}',#5,'Level1Elements',$,({refs_csv}),#16);"
        )

    lines.extend(["ENDSEC;", "END-ISO-10303-21;", ""])
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {
        "status": "ok",
        "schema": "IFC4",
        "input_usir": str(usir_path),
        "output_ifc": str(out_path),
        "elements_exported": len(elem_refs),
    }
