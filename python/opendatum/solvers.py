"""Deterministic First-Principles Physical Engineering Solvers.

Covers all 4 PLE (Physical-Engineering's Last Exam) disciplines plus off-Earth/vacuum
thermal & gravity-scaled analysis with transparent equations, code references, and pass/fail checks.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .materials import MaterialsDB

SIGMA_SB = 5.670374419e-8  # Stefan-Boltzmann constant [W/(m^2*K^4)]


class EngineeringSolvers:
    def __init__(self, materials_db: Optional[MaterialsDB] = None):
        self.materials = materials_db or MaterialsDB()

    # =========================================================================
    # 1. STRUCTURAL ENGINEERING
    # =========================================================================

    def structural_load_combinations_asce7(
        self,
        dead: float,
        live: float = 0.0,
        roof_live_or_snow: float = 0.0,
        wind: float = 0.0,
        seismic: float = 0.0,
        unit_label: str = "kN",
    ) -> Dict[str, Any]:
        """ASCE 7-22 Section 2.3.1 LRFD governing load combinations."""
        combos = {
            "LC1_1.4D": 1.4 * dead,
            "LC2_1.2D+1.6L+0.5S": 1.2 * dead + 1.6 * live + 0.5 * roof_live_or_snow,
            "LC3a_1.2D+1.6S+L": 1.2 * dead + 1.6 * roof_live_or_snow + live,
            "LC3b_1.2D+1.6S+0.5W": 1.2 * dead + 1.6 * roof_live_or_snow + 0.5 * wind,
            "LC4_1.2D+1.0W+L+0.5S": 1.2 * dead + 1.0 * wind + live + 0.5 * roof_live_or_snow,
            "LC5_1.2D+1.0E+L+0.2S": 1.2 * dead + 1.0 * seismic + live + 0.2 * roof_live_or_snow,
            "LC6_0.9D+1.0W_uplift": 0.9 * dead + 1.0 * wind,
            "LC7_0.9D+1.0E_uplift": 0.9 * dead + 1.0 * seismic,
        }
        gov_name, gov_val = max(combos.items(), key=lambda kv: kv[1])
        min_name, min_val = min(combos.items(), key=lambda kv: kv[1])
        return {
            "standard": "ASCE 7-22 Section 2.3.1 (LRFD)",
            "unit": unit_label,
            "combinations": {k: round(v, 4) for k, v in combos.items()},
            "governing_max": {"combination": gov_name, "value": round(gov_val, 4)},
            "governing_min_uplift": {"combination": min_name, "value": round(min_val, 4)},
        }

    def structural_beam_check(
        self,
        span_m: float,
        uniform_load_kn_m: float,
        material_id: str,
        moment_of_inertia_mm4: float,
        depth_mm: float,
        support_type: str = "simply_supported",
        deflection_limit_ratio: float = 360.0,
        phi_b: float = 0.90,
        include_self_weight_area_mm2: float = 0.0,
        environment: str = "earth_sea_level",
    ) -> Dict[str, Any]:
        """First-principles Euler-Bernoulli beam bending & serviceability deflection check.
        Supports Earth, Lunar, Martian, or arbitrary planetary gravity self-weight scaling."""
        mat = self.materials.get(material_id)
        env = self.materials.get_environment(environment)
        g = env["gravity_m_s2"]

        # Optional self-weight in kN/m
        self_wt_kn_m = 0.0
        if include_self_weight_area_mm2 > 0:
            area_m2 = include_self_weight_area_mm2 * 1e-6
            self_wt_kn_m = (mat["density_kg_m3"] * area_m2 * g) / 1000.0

        w_total_kn_m = uniform_load_kn_m + self_wt_kn_m
        w_n_m = w_total_kn_m * 1000.0
        L = span_m
        I_m4 = moment_of_inertia_mm4 * 1e-12
        c_m = (depth_mm * 0.5) * 1e-3
        E_pa = mat["youngs_modulus_gpa"] * 1e9
        fy_mpa = mat["yield_strength_mpa"]

        if support_type == "cantilever":
            m_max_nm = 0.5 * w_n_m * L**2
            v_max_n = w_n_m * L
            delta_m = (w_n_m * L**4) / (8.0 * E_pa * I_m4)
            eq_label = "Cantilever: M=wL^2/2, V=wL, delta=wL^4/(8EI)"
        else:
            m_max_nm = (w_n_m * L**2) / 8.0
            v_max_n = 0.5 * w_n_m * L
            delta_m = (5.0 * w_n_m * L**4) / (384.0 * E_pa * I_m4)
            eq_label = "Simply Supported: M=wL^2/8, V=wL/2, delta=5wL^4/(384EI)"

        sigma_mpa = (m_max_nm * c_m / I_m4) / 1e6
        allowable_mpa = phi_b * fy_mpa
        strength_util = sigma_mpa / allowable_mpa if allowable_mpa > 0 else float("inf")

        delta_mm = delta_m * 1000.0
        delta_allow_mm = (L * 1000.0) / deflection_limit_ratio
        deflection_util = delta_mm / delta_allow_mm if delta_allow_mm > 0 else float("inf")

        return {
            "equations": eq_label,
            "material_id": mat["id"],
            "environment": environment,
            "gravity_m_s2": g,
            "self_weight_kn_m": round(self_wt_kn_m, 4),
            "total_load_kn_m": round(w_total_kn_m, 4),
            "max_moment_kn_m": round(m_max_nm / 1000.0, 4),
            "max_shear_kn": round(v_max_n / 1000.0, 4),
            "max_bending_stress_mpa": round(sigma_mpa, 3),
            "design_yield_capacity_mpa": round(allowable_mpa, 3),
            "strength_utilization": round(strength_util, 4),
            "strength_pass": strength_util <= 1.0,
            "max_deflection_mm": round(delta_mm, 3),
            "allowable_deflection_mm": round(delta_allow_mm, 3),
            "deflection_ratio_actual": f"L/{int(round((L * 1000.0) / delta_mm))}" if delta_mm > 1e-9 else "L/inf",
            "deflection_utilization": round(deflection_util, 4),
            "deflection_pass": deflection_util <= 1.0,
            "overall_pass": strength_util <= 1.0 and deflection_util <= 1.0,
        }

    # =========================================================================
    # 2. CIVIL & GEOTECHNICAL ENGINEERING
    # =========================================================================

    def civil_manning_flow(
        self,
        slope: float,
        manning_n: float,
        diameter_m: Optional[float] = None,
        width_m: Optional[float] = None,
        depth_m: Optional[float] = None,
        fill_fraction: float = 1.0,
    ) -> Dict[str, Any]:
        """Manning open-channel or circular gravity pipe hydraulics (SI)."""
        if diameter_m is not None:
            r = diameter_m * 0.5
            if fill_fraction >= 0.999:
                area = math.pi * r * r
                wetted_p = 2.0 * math.pi * r
            else:
                h = max(1e-4, min(diameter_m, diameter_m * fill_fraction))
                theta = 2.0 * math.acos(max(-1.0, min(1.0, (r - h) / r)))
                area = 0.5 * r * r * (theta - math.sin(theta))
                wetted_p = r * theta
            geom = f"Circular pipe D={diameter_m} m, fill={fill_fraction*100:.0f}%"
        elif width_m is not None and depth_m is not None:
            area = width_m * depth_m
            wetted_p = width_m + 2.0 * depth_m
            geom = f"Rectangular channel {width_m}m x {depth_m}m"
        else:
            raise ValueError("Provide either diameter_m OR (width_m and depth_m).")

        rh = area / wetted_p
        velocity = (1.0 / manning_n) * (rh ** (2.0 / 3.0)) * math.sqrt(slope)
        discharge_m3_s = area * velocity

        warnings = []
        if velocity < 0.6:
            warnings.append(f"Velocity {velocity:.2f} m/s < 0.6 m/s self-cleansing minimum (sedimentation risk).")
        if velocity > 3.5:
            warnings.append(f"Velocity {velocity:.2f} m/s > 3.5 m/s erosion/scour warning.")

        return {
            "formula": "Q = (1/n) * A * R_h^(2/3) * S^(1/2)",
            "geometry": geom,
            "area_m2": round(area, 5),
            "wetted_perimeter_m": round(wetted_p, 5),
            "hydraulic_radius_m": round(rh, 5),
            "velocity_m_s": round(velocity, 4),
            "discharge_m3_s": round(discharge_m3_s, 5),
            "discharge_l_s": round(discharge_m3_s * 1000.0, 2),
            "discharge_cfs": round(discharge_m3_s / 0.0283168466, 3),
            "warnings": warnings,
        }

    def civil_bearing_capacity_terzaghi(
        self,
        footing_width_m: float,
        embedment_depth_m: float,
        soil_material_id: str = "soil_dense_sand",
        footing_shape: str = "square",
        applied_load_kn: Optional[float] = None,
        factor_of_safety: float = 3.0,
        environment: str = "earth_sea_level",
    ) -> Dict[str, Any]:
        """Terzaghi shallow foundation bearing capacity check (supports Earth, Moon, Mars!)."""
        soil = self.materials.get(soil_material_id)
        env = self.materials.get_environment(environment)
        g = env["gravity_m_s2"]

        gamma_kn_m3 = (soil["density_kg_m3"] * g) / 1000.0
        phi_deg = float(soil.get("friction_angle_deg", 30.0))
        c_kpa = float(soil.get("cohesion_kpa", 0.0))
        phi = math.radians(phi_deg)

        # Vesic / Terzaghi bearing capacity factors
        nq = math.exp(math.pi * math.tan(phi)) * (math.tan(math.radians(45.0 + phi_deg / 2.0)) ** 2)
        nc = 5.14 if phi_deg < 1e-3 else (nq - 1.0) / math.tan(phi)
        ngamma = 2.0 * (nq + 1.0) * math.tan(phi)

        if footing_shape == "square":
            sc, sg = 1.3, 0.8
            area = footing_width_m**2
        elif footing_shape == "circular":
            sc, sg = 1.3, 0.6
            area = math.pi * (footing_width_m * 0.5) ** 2
        else:  # strip (per meter length)
            sc, sg = 1.0, 1.0
            area = footing_width_m

        q_overburden = gamma_kn_m3 * embedment_depth_m
        q_ult_kpa = c_kpa * nc * sc + q_overburden * nq + 0.5 * gamma_kn_m3 * footing_width_m * ngamma * sg
        q_allow_kpa = q_ult_kpa / factor_of_safety

        res: Dict[str, Any] = {
            "formula": "q_ult = c*Nc*sc + q*Nq + 0.5*gamma*B*Ngamma*sg",
            "soil_material": soil["id"],
            "environment": environment,
            "unit_weight_kn_m3": round(gamma_kn_m3, 3),
            "friction_angle_deg": phi_deg,
            "cohesion_kpa": c_kpa,
            "factors": {"Nc": round(nc, 2), "Nq": round(nq, 2), "Ngamma": round(ngamma, 2)},
            "q_ult_kpa": round(q_ult_kpa, 2),
            "q_allow_kpa": round(q_allow_kpa, 2),
            "q_allow_psf": round(q_allow_kpa * 20.885434, 1),
            "allowable_load_kn": round(q_allow_kpa * area, 2),
        }
        if applied_load_kn is not None:
            q_app = applied_load_kn / area
            actual_fs = q_ult_kpa / q_app if q_app > 0 else float("inf")
            res["applied_pressure_kpa"] = round(q_app, 2)
            res["actual_fs"] = round(actual_fs, 2)
            res["pass"] = actual_fs >= factor_of_safety
        return res

    # =========================================================================
    # 3. ELECTRICAL ENGINEERING (NEC / IEC)
    # =========================================================================

    def electrical_feeder_check(
        self,
        voltage_v: float,
        current_a: float,
        one_way_length_m: float,
        conductor_area_mm2: float,
        phases: int = 3,
        conductor_material_id: str = "copper_c11000",
        power_factor: float = 0.90,
        continuous_load: bool = True,
        max_vd_pct: float = 3.0,
    ) -> Dict[str, Any]:
        """NEC/IEC first-principles voltage drop, power loss, and continuous load check."""
        mat = self.materials.get(conductor_material_id)
        # Adjust 20°C resistivity to ~75°C conductor operating temperature (+21.6%)
        rho_75c = mat["electrical_resistivity_ohm_m"] * 1.216
        area_m2 = conductor_area_mm2 * 1e-6
        r_one_way_ohm = rho_75c * one_way_length_m / area_m2

        phase_mult = math.sqrt(3.0) if phases == 3 else 2.0
        vd_v = phase_mult * current_a * r_one_way_ohm * power_factor
        vd_pct = (vd_v / voltage_v) * 100.0

        design_current_a = current_a * (1.25 if continuous_load else 1.0)
        line_loss_w = (3.0 if phases == 3 else 2.0) * (current_a**2) * r_one_way_ohm
        delivered_kw = (
            (math.sqrt(3.0) if phases == 3 else 1.0) * voltage_v * current_a * power_factor / 1000.0
        )

        return {
            "standard": "NEC Art. 210.19 / 215.2 & IEC 60364-5-52",
            "conductor_material": mat["id"],
            "phases": phases,
            "voltage_v": voltage_v,
            "load_current_a": current_a,
            "nec_min_design_ampacity_a": round(design_current_a, 2),
            "one_way_resistance_75c_ohm": round(r_one_way_ohm, 5),
            "voltage_drop_v": round(vd_v, 3),
            "voltage_drop_pct": round(vd_pct, 3),
            "voltage_drop_limit_pct": max_vd_pct,
            "voltage_drop_pass": vd_pct <= max_vd_pct,
            "i2r_heat_loss_w": round(line_loss_w, 2),
            "delivered_real_power_kw": round(delivered_kw, 3),
        }

    def electrical_solar_busbar_120_check(
        self,
        busbar_rating_a: float,
        main_breaker_a: float,
        inverter_max_output_a: float,
    ) -> Dict[str, Any]:
        """NEC 705.12(B)(3)(2) 120% load-side PV/ESS busbar interconnection verifier."""
        min_pv_breaker = 1.25 * inverter_max_output_a
        # Round up to next standard breaker size
        std_breakers = [15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 100, 110, 125, 150, 175, 200, 225, 250, 300, 350, 400]
        pv_breaker = next((b for b in std_breakers if b >= min_pv_breaker), math.ceil(min_pv_breaker))
        max_allowed_total = 1.20 * busbar_rating_a
        actual_total = main_breaker_a + pv_breaker
        max_pv_breaker_allowed = max_allowed_total - main_breaker_a

        return {
            "standard": "NEC 705.12(B)(3)(2) 120% Rule (opposite-end backfed breaker)",
            "busbar_rating_a": busbar_rating_a,
            "main_breaker_a": main_breaker_a,
            "inverter_continuous_125pct_a": round(min_pv_breaker, 2),
            "selected_pv_breaker_a": pv_breaker,
            "max_combined_allowed_a": round(max_allowed_total, 2),
            "actual_combined_a": actual_total,
            "max_pv_breaker_permitted_a": round(max_pv_breaker_allowed, 2),
            "pass": actual_total <= max_allowed_total,
            "remediation": None
            if actual_total <= max_allowed_total
            else f"Derate main breaker to <= {int(max_allowed_total - pv_breaker)} A, upgrade busbar, or use NEC 705.11 supply-side tap.",
        }

    # =========================================================================
    # 4. MECHANICAL, HVAC, FLUID & THERMAL ENGINEERING (TERRESTRIAL + VACUUM)
    # =========================================================================

    def mechanical_pipe_flow_darcy(
        self,
        flow_rate_l_s: float,
        pipe_id_mm: float,
        length_m: float,
        roughness_mm: float = 0.045,
        fluid_material_id: str = "fluid_water_20c",
        environment: str = "earth_sea_level",
    ) -> Dict[str, Any]:
        """Darcy-Weisbach & Swamee-Jain closed-conduit pipe head loss and pumping power."""
        fluid = self.materials.get(fluid_material_id)
        env = self.materials.get_environment(environment)
        g = max(env["gravity_m_s2"], 1e-4)

        rho = fluid["density_kg_m3"]
        mu = float(fluid.get("dynamic_viscosity_pa_s", 0.001002))
        d = pipe_id_mm * 1e-3
        q = flow_rate_l_s * 1e-3
        area = math.pi * (d**2) / 4.0
        vel = q / area
        re = rho * vel * d / mu

        if re < 2300.0:
            regime = "laminar"
            f = 64.0 / max(re, 1e-6)
        else:
            regime = "turbulent"
            rel_rough = (roughness_mm * 1e-3) / d
            f = 0.25 / (math.log10(rel_rough / 3.7 + 5.74 / (re**0.9)) ** 2)

        dp_pa = f * (length_m / d) * (0.5 * rho * vel**2)
        head_loss_m = dp_pa / (rho * g)
        hydraulic_power_w = dp_pa * q

        return {
            "formula": "dP = f * (L/D) * (rho * v^2 / 2)  [Swamee-Jain friction factor]",
            "fluid": fluid["id"],
            "velocity_m_s": round(vel, 4),
            "reynolds_number": round(re, 1),
            "flow_regime": regime,
            "friction_factor_f": round(f, 5),
            "pressure_drop_pa": round(dp_pa, 2),
            "pressure_drop_kpa": round(dp_pa / 1000.0, 4),
            "pressure_drop_psi": round(dp_pa / 6894.757, 4),
            "head_loss_m": round(head_loss_m, 4),
            "hydraulic_pumping_power_w": round(hydraulic_power_w, 3),
            "velocity_within_hydronic_guideline": 0.4 <= vel <= 2.4,
        }

    def mechanical_duct_sizing(
        self,
        airflow_m3_s: float,
        width_mm: float,
        height_mm: float,
        length_m: float = 10.0,
        roughness_mm: float = 0.09,
    ) -> Dict[str, Any]:
        """ASHRAE Huebscher equivalent diameter & equal-friction rectangular HVAC duct check."""
        a = width_mm * 1e-3
        b = height_mm * 1e-3
        area = a * b
        vel = airflow_m3_s / area
        aspect = max(a, b) / min(a, b)
        de = 1.30 * ((a * b) ** 0.625) / ((a + b) ** 0.25)

        air = self.materials.get("fluid_air_stp")
        rho = air["density_kg_m3"]
        mu = float(air.get("dynamic_viscosity_pa_s", 1.825e-5))
        re = rho * vel * de / mu
        rel_rough = (roughness_mm * 1e-3) / de
        f = 0.25 / (math.log10(rel_rough / 3.7 + 5.74 / (max(re, 3000.0) ** 0.9)) ** 2)
        dp_per_m = f * (1.0 / de) * (0.5 * rho * vel**2)
        total_dp_pa = dp_per_m * length_m

        return {
            "standard": "ASHRAE Fundamentals Ch. 21 (Huebscher Equivalent Diameter)",
            "airflow_m3_s": airflow_m3_s,
            "airflow_cfm": round(airflow_m3_s / 0.0004719474, 1),
            "equivalent_diameter_mm": round(de * 1000.0, 2),
            "aspect_ratio": round(aspect, 2),
            "aspect_ratio_pass": aspect <= 4.0,
            "velocity_m_s": round(vel, 3),
            "velocity_fpm": round(vel / 0.00508, 1),
            "friction_rate_pa_m": round(dp_per_m, 4),
            "friction_rate_inwg_100ft": round(dp_per_m * 30.48 / 249.0889, 4),
            "total_pressure_drop_pa": round(total_dp_pa, 2),
            "trunk_noise_pass": vel <= 9.0,
        }

    def thermal_envelope_and_radiation(
        self,
        layers: List[Dict[str, Any]],
        area_m2: float,
        t_inside_k: float,
        t_outside_k: float,
        h_inside_w_m2k: float = 8.3,
        h_outside_w_m2k: float = 25.0,
        include_vacuum_radiation_emissivity: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Multi-layer 1D composite wall/habitat heat transfer (conduction + convection OR vacuum radiation).
        Each layer dict: {"material_id": str, "thickness_m": float}."""
        r_cond_total = 0.0
        layer_breakdown = []
        total_areal_mass_kg_m2 = 0.0

        for layer in layers:
            m = self.materials.get(layer["material_id"])
            t = float(layer["thickness_m"])
            k = float(m["thermal_conductivity_w_mk"])
            r_layer = t / k
            r_cond_total += r_layer
            areal = m["density_kg_m3"] * t
            total_areal_mass_kg_m2 += areal
            layer_breakdown.append(
                {
                    "material_id": m["id"],
                    "thickness_m": t,
                    "k_w_mk": k,
                    "r_si_m2k_w": round(r_layer, 4),
                    "areal_density_g_cm2": round(areal / 10.0, 2),
                }
            )

        if include_vacuum_radiation_emissivity is not None:
            # Vacuum boundary: exterior exchanges purely via Stefan-Boltzmann radiation.
            # Estimate effective linearized radiative coefficient h_rad = eps * sigma * (Ti+To)*(Ti^2+To^2)
            eps = include_vacuum_radiation_emissivity
            h_rad = eps * SIGMA_SB * (t_inside_k + t_outside_k) * (t_inside_k**2 + t_outside_k**2)
            r_total = (1.0 / h_inside_w_m2k) + r_cond_total + (1.0 / max(h_rad, 1e-6))
            mode = f"vacuum_radiative (emissivity={eps})"
        else:
            r_total = (1.0 / h_inside_w_m2k) + r_cond_total + (1.0 / h_outside_w_m2k)
            mode = "terrestrial_convective"

        u_value = 1.0 / r_total
        delta_t = t_inside_k - t_outside_k
        heat_flux_w_m2 = u_value * delta_t
        heat_loss_w = heat_flux_w_m2 * area_m2

        return {
            "mode": mode,
            "layers": layer_breakdown,
            "r_total_si_m2k_w": round(r_total, 4),
            "r_total_imperial_ft2_f_h_btu": round(r_total * 5.678263, 2),
            "u_value_w_m2k": round(u_value, 4),
            "delta_t_k": round(delta_t, 2),
            "heat_flux_w_m2": round(heat_flux_w_m2, 3),
            "total_heat_transfer_w": round(heat_loss_w, 2),
            "total_areal_density_g_cm2": round(total_areal_mass_kg_m2 / 10.0, 2),
        }
