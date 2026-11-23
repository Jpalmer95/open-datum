"""Engineering Document & Spreadsheet Auditor + Project Spec Auto-Ingestor.

Zero-dependency offline support for:
1. `.xlsx` & `.csv` BOQ / Load Schedule / Cost Sheet auditing (detects Excel formula
   errors `#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`, `#NUM!`, counts formulas vs
   hardcoded numeric cells, and summarizes sheet dimensions).
2. Auto-ingesting project specifications (`.md`, `.txt`, and `.pdf` when `pypdf`/`pdfplumber`
   is installed) directly into OpenDatum's local SQLite FTS5 CodesEngine under a `PROJECT`
   jurisdiction overlay so every specialist agent queries exact project rules in <150 tokens!
"""

from __future__ import annotations

import csv
import json
import re
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List

from .codes import CodesEngine

EXCEL_ERRORS = ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!", "#NULL!")


def audit_spreadsheet(path: str | Path) -> Dict[str, Any]:
    """Audits a `.xlsx` or `.csv` engineering schedule/BOQ for formula errors and integrity."""
    p = Path(path)
    ext = p.suffix.lower()

    if ext == ".csv":
        rows = list(csv.reader(p.read_text(encoding="utf-8", errors="ignore").splitlines()))
        err_cells = []
        for r_i, row in enumerate(rows, start=1):
            for c_i, cell in enumerate(row, start=1):
                if any(e in cell for e in EXCEL_ERRORS):
                    err_cells.append({"row": r_i, "col": c_i, "value": cell})
        return {
            "file": str(p),
            "format": "csv",
            "rows": len(rows),
            "columns": max((len(r) for r in rows), default=0),
            "error_cells": err_cells,
            "pass": len(err_cells) == 0 and len(rows) > 0,
        }

    if ext != ".xlsx":
        raise ValueError(f"Unsupported spreadsheet format: {ext} (expected .xlsx or .csv)")

    # Zero-dependency OOXML `.xlsx` formula & value inspector
    sheets_summary: List[Dict[str, Any]] = []
    total_errors: List[Dict[str, Any]] = []
    total_formulas = 0

    with zipfile.ZipFile(p, "r") as zf:
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter():
                if si.tag.endswith("}si") or si.tag == "si":
                    txt = "".join(t.text or "" for t in si.iter() if t.tag.endswith("}t") or t.tag == "t")
                    shared_strings.append(txt)

        sheet_files = sorted(
            name for name in zf.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
        )
        for sf in sheet_files:
            root = ET.fromstring(zf.read(sf))
            cell_count = 0
            formula_count = 0
            sheet_errors = []

            for c in root.iter():
                if not (c.tag.endswith("}c") or c.tag == "c"):
                    continue
                cell_count += 1
                ref = c.attrib.get("r", "?")
                ctype = c.attrib.get("t", "")
                f_node = None
                v_node = None
                for child in c:
                    if child.tag.endswith("}f") or child.tag == "f":
                        f_node = child
                    elif child.tag.endswith("}v") or child.tag == "v":
                        v_node = child

                if f_node is not None:
                    formula_count += 1
                val_text = v_node.text if v_node is not None and v_node.text else ""
                if ctype == "s" and val_text.isdigit():
                    idx = int(val_text)
                    if idx < len(shared_strings):
                        val_text = shared_strings[idx]
                if ctype == "e" or any(err in val_text for err in EXCEL_ERRORS):
                    rec = {
                        "sheet": Path(sf).stem,
                        "cell": ref,
                        "formula": f_node.text if f_node is not None else None,
                        "value": val_text,
                    }
                    sheet_errors.append(rec)
                    total_errors.append(rec)

            total_formulas += formula_count
            sheets_summary.append(
                {
                    "sheet": Path(sf).stem,
                    "cells": cell_count,
                    "formulas": formula_count,
                    "errors": len(sheet_errors),
                }
            )

    return {
        "file": str(p),
        "format": "xlsx",
        "sheets": sheets_summary,
        "total_formulas": total_formulas,
        "error_cells": total_errors,
        "pass": len(total_errors) == 0 and len(sheets_summary) > 0,
    }


def ingest_spec_document_to_codes(
    doc_path: str | Path,
    codes_engine: CodesEngine,
    jurisdiction_code: str = "PROJECT",
    parent_jurisdiction: str = "US",
    discipline: str = "generic",
) -> Dict[str, Any]:
    """Chunks a project specification document (`.md`, `.txt`, or `.pdf`) into indexed
    clauses inside OpenDatum's local SQLite FTS5 CodesEngine for token-efficient lookup."""
    p = Path(doc_path)
    ext = p.suffix.lower()

    if ext == ".pdf":
        text = _extract_pdf_text(p)
    else:
        text = p.read_text(encoding="utf-8", errors="ignore")

    # Split by markdown headings or numbered sections (e.g., "1.2 ...", "SECTION 23 05 00")
    sections = re.split(r"\n(?=#{1,3}\s+|SECTION\s+\d+|\d+\.\d+\s+[A-Z])", text.strip())
    clauses = []
    for idx, sec in enumerate(sections, start=1):
        block = sec.strip()
        if len(block) < 20:
            continue
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        title = lines[0].lstrip("# ").strip()[:120]
        summary = " ".join(lines[1:3])[:260] if len(lines) > 1 else title
        clauses.append(
            {
                "id": f"{jurisdiction_code}-{p.stem.upper()}-{idx:03d}",
                "jurisdiction": jurisdiction_code,
                "discipline": discipline,
                "standard": f"Project Spec ({p.name})",
                "title": title,
                "summary": summary,
                "details": block[:4000],
                "formula": "",
                "parameters": {},
                "tags": [p.stem.lower(), jurisdiction_code.lower(), discipline.lower()],
            }
        )

    pack = {
        "jurisdictions": [
            {
                "code": jurisdiction_code,
                "name": f"Project Specification Overlay ({p.name})",
                "parent": parent_jurisdiction,
                "adopted_standards": [p.name],
            }
        ],
        "clauses": clauses,
    }
    with tempfile.TemporaryDirectory() as td:
        pack_file = Path(td) / "spec_pack.json"
        pack_file.write_text(json.dumps(pack), encoding="utf-8")
        res = codes_engine.ingest_pack(pack_file)

    return {
        "status": "ok",
        "source": str(p),
        "jurisdiction": jurisdiction_code,
        "clauses_indexed": res["clauses_ingested"],
    }


def _extract_pdf_text(path: Path) -> str:
    for mod in ("pypdf", "pdfplumber"):
        try:
            if mod == "pypdf":
                import pypdf  # type: ignore

                reader = pypdf.PdfReader(str(path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            else:
                import pdfplumber  # type: ignore

                with pdfplumber.open(str(path)) as pdf:
                    return "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception:
            continue
    # Graceful fallback extracting printable ASCII runs if no PDF library installed
    raw = path.read_bytes().decode("latin-1", errors="ignore")
    chunks = re.findall(r"[A-Za-z0-9][A-Za-z0-9 ,.;:()/\-]{12,}", raw)
    return "\n".join(chunks[:500])
