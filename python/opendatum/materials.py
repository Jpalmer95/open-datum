"""First-Principles Universal Materials Substrate.

Supports:
- Rich offline engineering materials corpus (terrestrial metals, concrete, geotech,
  timber, polymers/3D-printing, MEP fluids, composites, metamaterials, and off-Earth ISRU).
- Planetary / operational environment profiles (gravity, vacuum, thermal bounds, radiation).
- Multi-criteria material trade-off comparison (specific strength, specific stiffness,
  thermal diffusivity, embodied carbon, cost, vacuum readiness).
- Extensible community JSON material packs (`load_pack`).
- Optional online federation with OPTIMADE / Materials Project REST APIs.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional


def _default_seed_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "materials" / "seed_materials.json"


class MaterialsDB:
    def __init__(self, seed_path: Optional[Path] = None, packs_dir: Optional[Path] = None):
        self.materials: Dict[str, Dict[str, Any]] = {}
        self.environments: Dict[str, Dict[str, Any]] = {}
        path = seed_path or _default_seed_path()
        if path.exists():
            self.load_pack(path)
        if packs_dir and packs_dir.exists():
            for p in sorted(packs_dir.glob("*.json")):
                self.load_pack(p)

    def load_pack(self, pack_path: Path) -> int:
        data = json.loads(Path(pack_path).read_text(encoding="utf-8"))
        for env_id, env in data.get("environments", {}).items():
            self.environments[env_id] = env
        count = 0
        for mat in data.get("materials", []):
            mid = mat["id"]
            self.materials[mid] = self._enrich_derived(mat)
            count += 1
        return count

    @staticmethod
    def _enrich_derived(mat: Dict[str, Any]) -> Dict[str, Any]:
        """Derive first-principles secondary physical ratios automatically."""
        m = dict(mat)
        rho = float(m.get("density_kg_m3") or 0.0)
        fy = float(m.get("yield_strength_mpa") or 0.0)
        e_gpa = float(m.get("youngs_modulus_gpa") or 0.0)
        k = float(m.get("thermal_conductivity_w_mk") or 0.0)
        cp = float(m.get("specific_heat_j_kgk") or 0.0)

        derived: Dict[str, Any] = {}
        if rho > 0:
            # Specific yield strength in kN*m/kg (= MPa / (kg/m3) * 1000)
            derived["specific_yield_strength_knm_kg"] = round((fy * 1e6 / rho) / 1000.0, 3)
            # Specific stiffness in MN*m/kg (= GPa / (kg/m3) * 1000)
            derived["specific_stiffness_mnm_kg"] = round((e_gpa * 1e9 / rho) / 1e6, 3)
            # Bulk modulus K = E / (3*(1 - 2*nu)) when nu < 0.495
            nu = float(m.get("poissons_ratio", 0.3))
            if nu < 0.495:
                derived["bulk_modulus_gpa"] = round(e_gpa / (3.0 * (1.0 - 2.0 * nu)), 3)
            # Thermal diffusivity alpha = k / (rho * cp) [m^2/s]
            if cp > 0:
                derived["thermal_diffusivity_m2_s"] = k / (rho * cp)
                derived["volumetric_heat_capacity_j_m3k"] = round(rho * cp, 1)
            # Areal density per 10 cm slab [g/cm^2] — useful for shielding & dead loads
            derived["areal_density_per_10cm_g_cm2"] = round((rho / 1000.0) * 10.0, 2)
        m["derived"] = derived
        return m

    def get(self, material_id: str) -> Dict[str, Any]:
        key = material_id.strip().lower()
        if key in self.materials:
            return self.materials[key]
        # Fuzzy fallback by name/id substring
        for mid, mat in self.materials.items():
            if key in mid or key in mat["name"].lower():
                return mat
        raise KeyError(f"Material '{material_id}' not found. Try materials.search().")

    def get_environment(self, env_id: str = "earth_sea_level") -> Dict[str, Any]:
        key = env_id.strip().lower()
        if key not in self.environments:
            raise KeyError(
                f"Unknown environment '{env_id}'. Available: {', '.join(sorted(self.environments))}"
            )
        return self.environments[key]

    def search(
        self,
        query: str = "",
        category: Optional[str] = None,
        domain: Optional[str] = None,
        vacuum_only: bool = False,
        min_yield_mpa: Optional[float] = None,
        max_density_kg_m3: Optional[float] = None,
        limit: int = 12,
    ) -> List[Dict[str, Any]]:
        terms = [t for t in query.lower().split() if t]
        scored: List[tuple[float, Dict[str, Any]]] = []

        for mat in self.materials.values():
            if category and mat.get("category") != category:
                continue
            if domain and domain not in mat.get("domain", ""):
                continue
            if vacuum_only and not mat.get("vacuum_compatible", False):
                continue
            if min_yield_mpa is not None and float(mat.get("yield_strength_mpa", 0)) < min_yield_mpa:
                continue
            if max_density_kg_m3 is not None and float(mat.get("density_kg_m3", 1e9)) > max_density_kg_m3:
                continue

            haystack = " ".join(
                [
                    mat["id"],
                    mat["name"],
                    mat.get("category", ""),
                    mat.get("domain", ""),
                    mat.get("standard", ""),
                    mat.get("notes", ""),
                ]
            ).lower()

            if not terms:
                score = 1.0
            else:
                hits = sum(2.0 if t in mat["id"] else (1.5 if t in mat["name"].lower() else (1.0 if t in haystack else 0.0)) for t in terms)
                if hits == 0:
                    continue
                score = hits / len(terms)

            scored.append(
                (
                    score,
                    {
                        "id": mat["id"],
                        "name": mat["name"],
                        "category": mat["category"],
                        "domain": mat["domain"],
                        "standard": mat.get("standard"),
                        "density_kg_m3": mat["density_kg_m3"],
                        "yield_strength_mpa": mat["yield_strength_mpa"],
                        "compressive_strength_mpa": mat["compressive_strength_mpa"],
                        "youngs_modulus_gpa": mat["youngs_modulus_gpa"],
                        "thermal_conductivity_w_mk": mat["thermal_conductivity_w_mk"],
                        "vacuum_compatible": mat["vacuum_compatible"],
                        "embodied_carbon_kgco2_kg": mat["embodied_carbon_kgco2_kg"],
                        "score": round(score, 3),
                    },
                )
            )

        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        return [item for _, item in scored[:limit]]

    def compare(self, material_ids: List[str], environment: str = "earth_sea_level") -> Dict[str, Any]:
        env = self.get_environment(environment)
        g = env["gravity_m_s2"]
        rows = []
        for mid in material_ids:
            m = self.get(mid)
            temp_ok = m["max_service_temp_k"] >= env["temp_max_k"]
            vac_ok = True if env["ambient_pressure_pa"] > 100.0 else bool(m["vacuum_compatible"])
            rows.append(
                {
                    "id": m["id"],
                    "name": m["name"],
                    "density_kg_m3": m["density_kg_m3"],
                    "unit_weight_kn_m3_in_env": round(m["density_kg_m3"] * g / 1000.0, 4),
                    "yield_strength_mpa": m["yield_strength_mpa"],
                    "compressive_strength_mpa": m["compressive_strength_mpa"],
                    "youngs_modulus_gpa": m["youngs_modulus_gpa"],
                    "specific_yield_knm_kg": m["derived"].get("specific_yield_strength_knm_kg"),
                    "specific_stiffness_mnm_kg": m["derived"].get("specific_stiffness_mnm_kg"),
                    "thermal_conductivity_w_mk": m["thermal_conductivity_w_mk"],
                    "embodied_carbon_kgco2_kg": m["embodied_carbon_kgco2_kg"],
                    "cost_usd_kg": m["cost_usd_kg"],
                    "env_compatible": temp_ok and vac_ok,
                    "env_warnings": [
                        w
                        for w in [
                            None if temp_ok else f"Max service temp {m['max_service_temp_k']} K < env max {env['temp_max_k']} K",
                            None if vac_ok else "Not rated for vacuum/low-pressure environment",
                        ]
                        if w
                    ],
                }
            )
        return {"environment": environment, "gravity_m_s2": g, "comparison": rows}

    def calc_mass_weight_cost(
        self,
        material_id: str,
        volume_m3: float,
        environment: str = "earth_sea_level",
    ) -> Dict[str, Any]:
        m = self.get(material_id)
        env = self.get_environment(environment)
        mass_kg = m["density_kg_m3"] * volume_m3
        weight_n = mass_kg * env["gravity_m_s2"]
        return {
            "material_id": m["id"],
            "material_name": m["name"],
            "environment": environment,
            "gravity_m_s2": env["gravity_m_s2"],
            "volume_m3": volume_m3,
            "mass_kg": round(mass_kg, 4),
            "weight_n": round(weight_n, 4),
            "weight_kn": round(weight_n / 1000.0, 6),
            "weight_lbf": round(weight_n / 4.4482216, 4),
            "estimated_material_cost_usd": round(mass_kg * m["cost_usd_kg"], 2),
            "embodied_carbon_kgco2e": round(mass_kg * m["embodied_carbon_kgco2_kg"], 3),
        }

    def query_optimade(
        self,
        formula: str,
        base_url: str = "https://optimade.materialsproject.org/v1",
        limit: int = 5,
        timeout_s: float = 8.0,
    ) -> Dict[str, Any]:
        """Optional online federation to any OPTIMADE-compliant materials science endpoint
        (e.g., Materials Project, AFLOW, OQMD, NOMAD). Fails gracefully in offline PLE containers."""
        params = urllib.parse.urlencode(
            {
                "filter": f'chemical_formula_reduced="{formula}"',
                "page_limit": limit,
            }
        )
        url = f"{base_url.rstrip('/')}/structures?{params}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "OpenDatum/0.1"})
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            items = []
            for entry in payload.get("data", []):
                attrs = entry.get("attributes", {})
                items.append(
                    {
                        "id": entry.get("id"),
                        "formula": attrs.get("chemical_formula_reduced"),
                        "formula_descriptive": attrs.get("chemical_formula_descriptive"),
                        "elements": attrs.get("elements"),
                        "nsites": attrs.get("nsites"),
                        "lattice_vectors": attrs.get("lattice_vectors"),
                    }
                )
            return {"status": "ok", "endpoint": base_url, "formula": formula, "results": items}
        except Exception as exc:
            return {
                "status": "offline_or_unavailable",
                "endpoint": base_url,
                "formula": formula,
                "error": str(exc),
                "hint": "Offline environment detected or endpoint unreachable; use local OpenDatum seed & packs.",
            }
