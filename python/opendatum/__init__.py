"""OpenDatum — Universal Spatial Hub, First-Principles Materials & Codes Substrate,
and Deterministic Physical Engineering Toolkit.
"""

__version__ = "0.2.0"

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

__all__ = [
    "__version__",
    "CodesEngine",
    "EngineeringSolvers",
    "MaterialsDB",
    "SpatialHub",
    "cad_capabilities",
    "convert_unit",
    "export_usir_to_ifc4",
    "extract_dxf_takeoff",
    "inspect_step_file",
]
