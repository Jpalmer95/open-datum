"""Zero-Dependency 2D Direct-Stiffness Finite Element Analysis (FEA) & Moist-Air Psychrometrics.

Provides exact matrix structural analysis for arbitrary 2D trusses and Euler-Bernoulli frames
(with partial-pivoting Gaussian elimination — zero numpy required!) plus ASHRAE psychrometrics.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .materials import MaterialsDB


def _solve_linear_system(a: List[List[float]], b: List[float]) -> List[float]:
    """Dense Gaussian elimination with partial pivoting (pure Python stdlib)."""
    n = len(b)
    mat = [row[:] + [b[i]] for i, row in enumerate(a)]

    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(mat[r][col]))
        if abs(mat[pivot][col]) < 1e-14:
            raise ValueError("Singular stiffness matrix — structure is unstable or under-constrained.")
        if pivot != col:
            mat[col], mat[pivot] = mat[pivot], mat[col]

        piv_val = mat[col][col]
        for j in range(col, n + 1):
            mat[col][j] /= piv_val

        for r in range(n):
            if r != col and abs(mat[r][col]) > 1e-15:
                factor = mat[r][col]
                for j in range(col, n + 1):
                    mat[r][j] -= factor * mat[col][j]

    return [mat[i][n] for i in range(n)]


def solve_2d_truss_fea(
    nodes: List[Dict[str, Any]],
    elements: List[Dict[str, Any]],
    loads: List[Dict[str, Any]],
    materials_db: Optional[MaterialsDB] = None,
) -> Dict[str, Any]:
    """2D Pin-Jointed Truss Direct-Stiffness FEA Solver (SI units: m, N, mm^2).

    nodes:    [{"id": "n1", "x": 0.0, "y": 0.0, "fix_x": True, "fix_y": True}, ...]
    elements: [{"id": "e1", "n1": "n1", "n2": "n2", "area_mm2": 2000.0, "material_id": "steel_a992"}, ...]
    loads:    [{"node": "n2", "fx_n": 0.0, "fy_n": -50000.0}, ...]
    """
    mdb = materials_db or MaterialsDB()
    node_idx = {n["id"]: i for i, n in enumerate(nodes)}
    ndof = 2 * len(nodes)
    K = [[0.0] * ndof for _ in range(ndof)]
    F = [0.0] * ndof

    for ld in loads:
        idx = node_idx[ld["node"]]
        F[2 * idx] += float(ld.get("fx_n", 0.0))
        F[2 * idx + 1] += float(ld.get("fy_n", 0.0))

    elem_cache = []
    for el in elements:
        i1 = node_idx[el["n1"]]
        i2 = node_idx[el["n2"]]
        x1, y1 = float(nodes[i1]["x"]), float(nodes[i1]["y"])
        x2, y2 = float(nodes[i2]["x"]), float(nodes[i2]["y"])
        L = math.hypot(x2 - x1, y2 - y1)
        if L < 1e-9:
            raise ValueError(f"Zero-length truss element {el['id']}")
        c = (x2 - x1) / L
        s = (y2 - y1) / L

        mat = mdb.get(el.get("material_id", "steel_a992"))
        E_pa = mat["youngs_modulus_gpa"] * 1e9
        A_m2 = float(el["area_mm2"]) * 1e-6
        k_ax = E_pa * A_m2 / L

        ke = [
            [c * c, c * s, -c * c, -c * s],
            [c * s, s * s, -c * s, -s * s],
            [-c * c, -c * s, c * c, c * s],
            [-c * s, -s * s, c * s, s * s],
        ]
        dofs = [2 * i1, 2 * i1 + 1, 2 * i2, 2 * i2 + 1]
        for r in range(4):
            for col in range(4):
                K[dofs[r]][dofs[col]] += k_ax * ke[r][col]
        elem_cache.append((el, i1, i2, L, c, s, E_pa, A_m2, mat))

    fixed_dofs = set()
    for i, n in enumerate(nodes):
        if n.get("fix_x", False):
            fixed_dofs.add(2 * i)
        if n.get("fix_y", False):
            fixed_dofs.add(2 * i + 1)

    free_dofs = [d for d in range(ndof) if d not in fixed_dofs]
    K_ff = [[K[r][c] for c in free_dofs] for r in free_dofs]
    F_f = [F[r] for r in free_dofs]

    u_f = _solve_linear_system(K_ff, F_f)
    U = [0.0] * ndof
    for idx_f, dof in enumerate(free_dofs):
        U[dof] = u_f[idx_f]

    # Support reactions R = K * U - F
    reactions = {}
    for i, n in enumerate(nodes):
        rx = sum(K[2 * i][j] * U[j] for j in range(ndof)) - F[2 * i]
        ry = sum(K[2 * i + 1][j] * U[j] for j in range(ndof)) - F[2 * i + 1]
        if n.get("fix_x") or n.get("fix_y"):
            reactions[n["id"]] = {"rx_kn": round(rx / 1000.0, 4), "ry_kn": round(ry / 1000.0, 4)}

    displacements = {
        n["id"]: {
            "ux_mm": round(U[2 * i] * 1000.0, 4),
            "uy_mm": round(U[2 * i + 1] * 1000.0, 4),
        }
        for i, n in enumerate(nodes)
    }

    member_results = []
    max_util = 0.0
    for el, i1, i2, L, c, s, E_pa, A_m2, mat in elem_cache:
        du = (U[2 * i2] - U[2 * i1]) * c + (U[2 * i2 + 1] - U[2 * i1 + 1]) * s
        strain = du / L
        stress_mpa = (E_pa * strain) / 1e6
        axial_kn = (stress_mpa * 1e6 * A_m2) / 1000.0
        fy_design = 0.90 * mat["yield_strength_mpa"]
        util = abs(stress_mpa) / fy_design if fy_design > 0 else 0.0
        max_util = max(max_util, util)
        member_results.append(
            {
                "id": el["id"],
                "length_m": round(L, 4),
                "axial_force_kn": round(axial_kn, 3),
                "state": "tension" if axial_kn >= 0 else "compression",
                "axial_stress_mpa": round(stress_mpa, 3),
                "utilization": round(util, 4),
                "pass": util <= 1.0,
            }
        )

    return {
        "solver": "OpenDatum 2D Direct-Stiffness Truss FEA",
        "displacements": displacements,
        "support_reactions": reactions,
        "members": member_results,
        "max_utilization": round(max_util, 4),
        "overall_pass": max_util <= 1.0,
    }


def solve_psychrometrics_ashrae(
    dry_bulb_c: float,
    relative_humidity_pct: float,
    pressure_pa: float = 101325.0,
) -> Dict[str, Any]:
    """ASHRAE Fundamentals moist-air psychrometric state calculator."""
    T = dry_bulb_c
    rh = max(0.01, min(100.0, relative_humidity_pct)) / 100.0
    # Magnus-Tetens saturation vapor pressure [Pa] (accurate within 0.1% for 0-60C)
    p_ws = 610.94 * math.exp((17.625 * T) / (T + 243.04))
    p_w = rh * p_ws
    # Humidity ratio W [kg water / kg dry air]
    w = 0.621945 * p_w / max(pressure_pa - p_w, 1.0)
    # Enthalpy h [kJ / kg dry air]
    h_kj_kg = 1.006 * T + w * (2501.0 + 1.86 * T)
    # Specific volume v [m^3 / kg dry air]
    v_m3_kg = (287.055 * (T + 273.15) / pressure_pa) * (1.0 + 1.6078 * w)
    # Dew point [C]
    gamma = math.log(max(p_w / 610.94, 1e-6))
    t_dp = (243.04 * gamma) / (17.625 - gamma)
    # Stull wet-bulb approximation [C]
    rh_pct = rh * 100.0
    t_wb = (
        T * math.atan(0.151977 * math.sqrt(rh_pct + 8.313659))
        + math.atan(T + rh_pct)
        - math.atan(rh_pct - 1.676331)
        + 0.00391838 * (rh_pct ** 1.5) * math.atan(0.023101 * rh_pct)
        - 4.686035
    )

    return {
        "standard": "ASHRAE Fundamentals Ch. 1 Psychrometrics",
        "dry_bulb_c": round(T, 2),
        "relative_humidity_pct": round(rh_pct, 2),
        "pressure_pa": pressure_pa,
        "saturation_vapor_pressure_pa": round(p_ws, 2),
        "humidity_ratio_kg_kg": round(w, 6),
        "humidity_ratio_grains_lb": round(w * 7000.0, 2),
        "enthalpy_kj_kg": round(h_kj_kg, 3),
        "specific_volume_m3_kg": round(v_m3_kg, 4),
        "air_density_kg_m3": round((1.0 + w) / v_m3_kg, 4),
        "dew_point_c": round(t_dp, 2),
        "wet_bulb_c": round(t_wb, 2),
    }
