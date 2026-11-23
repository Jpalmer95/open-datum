"""Standard Engineering Reference Tables & Optimal Cost/Code Selectors (AISC Steel + NEC Electrical)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from .materials import MaterialsDB
from .solvers import EngineeringSolvers


def _tables_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "tables"


class StandardTables:
    def __init__(self, materials_db: Optional[MaterialsDB] = None):
        self.materials = materials_db or MaterialsDB()
        self.solvers = EngineeringSolvers(self.materials)
        aisc = json.loads((_tables_dir() / "aisc_shapes.json").read_text(encoding="utf-8"))
        nec = json.loads((_tables_dir() / "nec_tables.json").read_text(encoding="utf-8"))
        self.aisc_shapes: List[Dict[str, Any]] = aisc["shapes"]
        self.nec_conductors: List[Dict[str, Any]] = nec["conductors"]
        self.emt_conduits: List[Dict[str, Any]] = nec["emt_conduits"]

    def get_aisc_shape(self, designation: str) -> Dict[str, Any]:
        key = designation.strip().upper()
        for s in self.aisc_shapes:
            if s["designation"].upper() == key:
                return s
        raise KeyError(f"AISC shape '{designation}' not found in seed catalog.")

    def select_lightest_steel_beam(
        self,
        span_m: float,
        uniform_load_kn_m: float,
        material_id: str = "steel_a992",
        deflection_limit_ratio: float = 360.0,
        max_depth_mm: Optional[float] = None,
        environment: str = "earth_sea_level",
    ) -> Dict[str, Any]:
        """Selects the lightest (most cost-efficient) AISC W-shape satisfying both
        LRFD strength and L/360 serviceability deflection including self-weight."""
        mat = self.materials.get(material_id)
        candidates = []
        for s in self.aisc_shapes:
            if s["family"] != "W":
                continue
            if max_depth_mm is not None and s["depth_mm"] > max_depth_mm:
                continue
            chk = self.solvers.structural_beam_check(
                span_m=span_m,
                uniform_load_kn_m=uniform_load_kn_m,
                material_id=material_id,
                moment_of_inertia_mm4=s["ix_mm4"],
                depth_mm=s["depth_mm"],
                deflection_limit_ratio=deflection_limit_ratio,
                include_self_weight_area_mm2=s["area_mm2"],
                environment=environment,
            )
            if chk["overall_pass"]:
                total_mass_kg = s["mass_kg_m"] * span_m
                candidates.append(
                    {
                        "designation": s["designation"],
                        "mass_kg_m": s["mass_kg_m"],
                        "total_beam_mass_kg": round(total_mass_kg, 2),
                        "estimated_steel_cost_usd": round(total_mass_kg * mat["cost_usd_kg"], 2),
                        "depth_mm": s["depth_mm"],
                        "strength_utilization": chk["strength_utilization"],
                        "deflection_utilization": chk["deflection_utilization"],
                        "deflection_ratio_actual": chk["deflection_ratio_actual"],
                    }
                )
        candidates.sort(key=lambda c: (c["mass_kg_m"], c["depth_mm"]))
        return {
            "span_m": span_m,
            "uniform_load_kn_m": uniform_load_kn_m,
            "material_id": material_id,
            "max_depth_mm": max_depth_mm,
            "recommended": candidates[0] if candidates else None,
            "top_candidates": candidates[:5],
            "passing_count": len(candidates),
        }

    def select_nec_feeder_and_conduit(
        self,
        voltage_v: float,
        current_a: float,
        one_way_length_m: float,
        phases: int = 3,
        conductor_material: str = "copper",
        conductor_count_in_conduit: int = 4,
        ambient_temp_c: float = 30.0,
        continuous_load: bool = True,
        max_vd_pct: float = 3.0,
    ) -> Dict[str, Any]:
        """Selects minimum NEC-compliant THHN conductor size (75°C terminals) & EMT conduit
        satisfying ampacity, ambient/bundling derating, voltage drop, and Ch. 9 Table 1 fill."""
        design_amps = current_a * (1.25 if continuous_load else 1.0)

        # Ambient temp correction factor for 75°C column (NEC Table 310.15(B)(1))
        if ambient_temp_c <= 30.0:
            temp_factor = 1.0
        elif ambient_temp_c <= 35.0:
            temp_factor = 0.94
        elif ambient_temp_c <= 40.0:
            temp_factor = 0.88
        elif ambient_temp_c <= 45.0:
            temp_factor = 0.82
        else:
            temp_factor = 0.75

        # Bundling adjustment (NEC Table 310.15(C)(1))
        if conductor_count_in_conduit <= 3:
            bundle_factor = 1.0
        elif conductor_count_in_conduit <= 6:
            bundle_factor = 0.80
        elif conductor_count_in_conduit <= 9:
            bundle_factor = 0.70
        else:
            bundle_factor = 0.50

        is_cu = conductor_material.strip().lower().startswith("cu") or conductor_material.strip().lower().startswith("cop")
        amp_key = "cu_amp_75c" if is_cu else "al_amp_75c"
        r_key = "r_cu_ohm_km" if is_cu else "r_al_ohm_km"
        phase_mult = math.sqrt(3.0) if phases == 3 else 2.0

        selected = None
        for c in self.nec_conductors:
            base_amp = c.get(amp_key)
            r_km = c.get(r_key)
            if base_amp is None or r_km is None:
                continue
            derated_amp = base_amp * temp_factor * bundle_factor
            if derated_amp < design_amps:
                continue
            vd_v = phase_mult * current_a * (r_km * (one_way_length_m / 1000.0)) * 0.90
            vd_pct = (vd_v / voltage_v) * 100.0
            if vd_pct <= max_vd_pct:
                selected = {
                    "conductor_size": c["size"],
                    "conductor_material": "copper" if is_cu else "aluminum",
                    "area_mm2": c["area_mm2"],
                    "thhn_area_mm2": c["thhn_area_mm2"],
                    "base_ampacity_75c_a": base_amp,
                    "derated_ampacity_a": round(derated_amp, 2),
                    "voltage_drop_v": round(vd_v, 3),
                    "voltage_drop_pct": round(vd_pct, 3),
                }
                break

        conduit_rec = None
        if selected:
            total_wire_area = selected["thhn_area_mm2"] * conductor_count_in_conduit
            fill_limit = 0.53 if conductor_count_in_conduit == 1 else (0.31 if conductor_count_in_conduit == 2 else 0.40)
            for cond in self.emt_conduits:
                fill_frac = total_wire_area / cond["internal_area_mm2"]
                if fill_frac <= fill_limit:
                    conduit_rec = {
                        "emt_trade_size": cond["trade_size"],
                        "fill_pct": round(fill_frac * 100.0, 2),
                        "fill_limit_pct": round(fill_limit * 100.0, 1),
                    }
                    break

        return {
            "standard": "NEC Table 310.16 + Ch. 9 Table 1 & 4 (75C termination)",
            "required_design_amps": round(design_amps, 2),
            "temp_factor": temp_factor,
            "bundle_factor": bundle_factor,
            "selected_conductor": selected,
            "selected_emt_conduit": conduit_rec,
            "pass": selected is not None and conduit_rec is not None,
        }
