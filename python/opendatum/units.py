"""Deterministic SI <-> Imperial dimensional unit conversion engine.

Eliminates LLM unit-conversion hallucinations across Structural, Civil,
Electrical, Mechanical, Fabrication, and Off-Earth engineering calculations.
"""

from __future__ import annotations

from typing import Dict, Tuple

# Maps unit symbol -> (dimension, factor_to_si_base)
UNIT_TABLE: Dict[str, Tuple[str, float]] = {
    # Length (base: m)
    "m": ("length", 1.0),
    "mm": ("length", 1e-3),
    "cm": ("length", 1e-2),
    "km": ("length", 1e3),
    "in": ("length", 0.0254),
    "ft": ("length", 0.3048),
    "yd": ("length", 0.9144),
    "mi": ("length", 1609.344),
    # Area (base: m2)
    "m2": ("area", 1.0),
    "mm2": ("area", 1e-6),
    "cm2": ("area", 1e-4),
    "in2": ("area", 0.00064516),
    "ft2": ("area", 0.09290304),
    "acre": ("area", 4046.8564224),
    "ha": ("area", 1e4),
    # Volume (base: m3)
    "m3": ("volume", 1.0),
    "mm3": ("volume", 1e-9),
    "cm3": ("volume", 1e-6),
    "l": ("volume", 1e-3),
    "gal": ("volume", 0.003785411784),
    "in3": ("volume", 1.6387064e-5),
    "ft3": ("volume", 0.028316846592),
    # Mass (base: kg)
    "kg": ("mass", 1.0),
    "g": ("mass", 1e-3),
    "tonne": ("mass", 1e3),
    "lb": ("mass", 0.45359237),
    "lbm": ("mass", 0.45359237),
    "ton_us": ("mass", 907.18474),
    # Force (base: N)
    "n": ("force", 1.0),
    "kn": ("force", 1e3),
    "mn": ("force", 1e6),
    "lbf": ("force", 4.4482216152605),
    "kip": ("force", 4448.2216152605),
    # Distributed load (base: N/m)
    "n/m": ("line_load", 1.0),
    "kn/m": ("line_load", 1e3),
    "plf": ("line_load", 14.5939029372),
    "klf": ("line_load", 14593.9029372),
    # Pressure / Stress (base: Pa)
    "pa": ("pressure", 1.0),
    "kpa": ("pressure", 1e3),
    "mpa": ("pressure", 1e6),
    "gpa": ("pressure", 1e9),
    "bar": ("pressure", 1e5),
    "psi": ("pressure", 6894.757293168),
    "ksi": ("pressure", 6894757.293168),
    "psf": ("pressure", 47.88025898),
    "ksf": ("pressure", 47880.25898),
    "in_wg": ("pressure", 249.08891),
    # Moment / Torque / Energy (base: N*m = J)
    "n*m": ("moment", 1.0),
    "kn*m": ("moment", 1e3),
    "ft*lbf": ("moment", 1.3558179483314),
    "ft*kip": ("moment", 1355.8179483314),
    "in*lbf": ("moment", 0.112984829),
    "j": ("moment", 1.0),
    "kj": ("moment", 1e3),
    "btu": ("moment", 1055.05585262),
    "kwh": ("moment", 3.6e6),
    # Power / Heat Rate (base: W)
    "w": ("power", 1.0),
    "kw": ("power", 1e3),
    "mw": ("power", 1e6),
    "hp": ("power", 745.699872),
    "btu/h": ("power", 0.29307107),
    "ton_ref": ("power", 3516.85284),
    # Volumetric Flow Rate (base: m3/s)
    "m3/s": ("flow_rate", 1.0),
    "l/s": ("flow_rate", 1e-3),
    "cfm": ("flow_rate", 0.0004719474432),
    "gpm": ("flow_rate", 6.30901964e-5),
    "cfs": ("flow_rate", 0.028316846592),
    # Velocity (base: m/s)
    "m/s": ("velocity", 1.0),
    "ft/s": ("velocity", 0.3048),
    "fpm": ("velocity", 0.00508),
    "mph": ("velocity", 0.44704),
    "km/h": ("velocity", 1.0 / 3.6),
    # Density (base: kg/m3)
    "kg/m3": ("density", 1.0),
    "g/cm3": ("density", 1000.0),
    "pcf": ("density", 16.01846337396),
}

TEMP_UNITS = {"k", "c", "f", "r"}


def _norm(u: str) -> str:
    return u.strip().lower().replace(" ", "").replace("°", "")


def convert_unit(value: float, from_unit: str, to_unit: str) -> dict:
    """Convert a scalar physical value between compatible SI/Imperial units."""
    fu = _norm(from_unit)
    tu = _norm(to_unit)

    if fu in TEMP_UNITS or tu in TEMP_UNITS:
        if fu not in TEMP_UNITS or tu not in TEMP_UNITS:
            raise ValueError(f"Incompatible temperature conversion: {from_unit} -> {to_unit}")
        # Convert to Kelvin
        if fu == "k":
            kelvin = value
        elif fu == "c":
            kelvin = value + 273.15
        elif fu == "f":
            kelvin = (value - 32.0) * 5.0 / 9.0 + 273.15
        else:  # Rankine
            kelvin = value * 5.0 / 9.0

        if tu == "k":
            result = kelvin
        elif tu == "c":
            result = kelvin - 273.15
        elif tu == "f":
            result = (kelvin - 273.15) * 9.0 / 5.0 + 32.0
        else:
            result = kelvin * 9.0 / 5.0

        return {
            "input": value,
            "from_unit": from_unit,
            "to_unit": to_unit,
            "dimension": "temperature",
            "result": result,
        }

    if fu not in UNIT_TABLE:
        raise ValueError(f"Unknown unit '{from_unit}'. Supported examples: m, mm, ft, in, MPa, psi, kN, kip, CFM, GPM, W, BTU/h, K, C, F")
    if tu not in UNIT_TABLE:
        raise ValueError(f"Unknown unit '{to_unit}'.")

    dim_f, fac_f = UNIT_TABLE[fu]
    dim_t, fac_t = UNIT_TABLE[tu]
    if dim_f != dim_t:
        raise ValueError(f"Dimension mismatch: '{from_unit}' ({dim_f}) cannot convert to '{to_unit}' ({dim_t})")

    si_value = value * fac_f
    result = si_value / fac_t
    return {
        "input": value,
        "from_unit": from_unit,
        "to_unit": to_unit,
        "dimension": dim_f,
        "si_value": si_value,
        "result": result,
    }
