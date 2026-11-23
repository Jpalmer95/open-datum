"""OpenDatum — Universal Spatial Hub, First-Principles Materials & Codes Substrate,
and Deterministic Physical Engineering Toolkit.
"""

__version__ = "0.3.0"

from .cad_bridges import (
    cad_capabilities,
    export_usir_to_ifc4,
    extract_dxf_takeoff,
    inspect_step_file,
)
from .codes import CodesEngine
from .docs_engine import audit_spreadsheet, ingest_spec_document_to_codes
from .fea import solve_2d_truss_fea, solve_psychrometrics_ashrae
from .materials import MaterialsDB
from .renderer import render_spatial_views
from .solvers import EngineeringSolvers
from .spatial import SpatialHub
from .tables import StandardTables
from .units import convert_unit

__all__ = [
    "__version__",
    "CodesEngine",
    "EngineeringSolvers",
    "MaterialsDB",
    "SpatialHub",
    "StandardTables",
    "audit_spreadsheet",
    "cad_capabilities",
    "convert_unit",
    "export_usir_to_ifc4",
    "extract_dxf_takeoff",
    "ingest_spec_document_to_codes",
    "inspect_step_file",
    "render_spatial_views",
    "solve_2d_truss_fea",
    "solve_psychrometrics_ashrae",
]
