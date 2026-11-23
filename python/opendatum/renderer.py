"""Zero-Dependency Visual Render-and-Check Engine (SVG + True PNG) for USIR & DXF.

Closes the #1 spatial blindness gap for multimodal AI agents on PLE & CAD tasks:
renders clean orthographic Plan (Top) and Elevation (Front) projections with
discipline color coding and bright red Clash Bounding Box callouts — generating BOTH
`.svg` and real `.png` files with pure Python stdlib (`zlib` + `struct`), zero pip deps required!
"""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .spatial import SpatialHub

DISCIPLINE_COLORS = {
    "structural": (41, 98, 255),      # Engineering Blue
    "mechanical": (0, 168, 107),      # HVAC Green
    "electrical": (235, 160, 0),      # Electrical Amber
    "plumbing": (0, 172, 237),        # Plumbing Cyan
    "architecture": (120, 120, 130),  # Architectural Slate
    "civil": (140, 90, 50),           # Civil Earth
    "fabrication": (138, 43, 226),    # Fab Purple
    "generic": (90, 90, 90),
}
CLASH_COLOR = (230, 30, 30)


def _write_png_rgb(path: Path, width: int, height: int, rgb_bytes: bytearray) -> None:
    """Minimal RFC-2083 compliant RGB PNG encoder using only stdlib zlib + struct."""
    def chunk(ctype: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(ctype + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", crc)

    raw = bytearray()
    stride = width * 3
    for y in range(height):
        raw.append(0)  # Filter type 0 (None)
        raw.extend(rgb_bytes[y * stride : (y + 1) * stride])

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), level=6))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


class _Canvas:
    def __init__(self, width: int, height: int, bg=(248, 250, 252)):
        self.w = width
        self.h = height
        self.buf = bytearray(bytes(bg) * (width * height))

    def set_px(self, x: int, y: int, color: Tuple[int, int, int]) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y * self.w + x) * 3
            self.buf[i] = color[0]
            self.buf[i + 1] = color[1]
            self.buf[i + 2] = color[2]

    def draw_rect_outline(self, x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int], thickness: int = 2) -> None:
        lx, rx = min(x0, x1), max(x0, x1)
        ty, by = min(y0, y1), max(y0, y1)
        for t in range(thickness):
            for x in range(lx - t, rx + t + 1):
                self.set_px(x, ty - t, color)
                self.set_px(x, by + t, color)
            for y in range(ty - t, by + t + 1):
                self.set_px(lx - t, y, color)
                self.set_px(rx + t, y, color)

    def fill_rect_tint(self, x0: int, y0: int, x1: int, y1: int, color: Tuple[int, int, int], alpha: float = 0.25) -> None:
        lx, rx = max(0, min(x0, x1)), min(self.w - 1, max(x0, x1))
        ty, by = max(0, min(y0, y1)), min(self.h - 1, max(y0, y1))
        inv = 1.0 - alpha
        for y in range(ty, by + 1):
            for x in range(lx, rx + 1):
                i = (y * self.w + x) * 3
                self.buf[i] = int(self.buf[i] * inv + color[0] * alpha)
                self.buf[i + 1] = int(self.buf[i + 1] * inv + color[1] * alpha)
                self.buf[i + 2] = int(self.buf[i + 2] * inv + color[2] * alpha)


def render_spatial_views(
    input_path: str | Path,
    output_dir: str | Path,
    view: str = "both",
    width: int = 800,
    height: int = 600,
    clearance: float = 0.05,
) -> Dict[str, Any]:
    """Renders orthographic Plan (Top) and/or Front Elevation SVG + PNG diagnostic images
    of any USIR/OBJ/STL/DXF/IFC file with color-coded disciplines and red clash boxes."""
    hub = SpatialHub()
    analysis = hub.analyze(str(input_path), clearance=clearance)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    boxes = []
    for mq in analysis.get("mesh_quality", []):
        q = mq["quality"]
        # Re-read node transform if USIR, or use mesh AABB directly
        boxes.append(
            {
                "id": mq["node_id"],
                "name": mq["name"],
                "discipline": mq["discipline"],
                "min": q["aabb_min"],
                "max": q["aabb_max"],
            }
        )

    # Shift AABBs by node world transform when source is USIR
    src_p = Path(input_path)
    if src_p.name.endswith(".odir.json"):
        doc = json.loads(src_p.read_text(encoding="utf-8"))
        pos_by_id = {n["id"]: n.get("transform", {}).get("position", [0, 0, 0]) for n in doc.get("nodes", [])}
        for b in boxes:
            p = pos_by_id.get(b["id"], [0, 0, 0])
            b["min"] = [b["min"][k] + p[k] for k in range(3)]
            b["max"] = [b["max"][k] + p[k] for k in range(3)]

    clashes = analysis.get("clash_report", {}).get("clashes", [])
    views_to_render = ["plan_xz", "elevation_xy"] if view == "both" else [view]
    outputs: Dict[str, str] = {}

    for vname in views_to_render:
        ax_u, ax_v = (0, 2) if "xz" in vname else (0, 1)
        all_u = [b["min"][ax_u] for b in boxes] + [b["max"][ax_u] for b in boxes]
        all_v = [b["min"][ax_v] for b in boxes] + [b["max"][ax_v] for b in boxes]
        if not all_u:
            all_u, all_v = [-1.0, 1.0], [-1.0, 1.0]

        umin, umax = min(all_u), max(all_u)
        vmin, vmax = min(all_v), max(all_v)
        span = max(umax - umin, vmax - vmin, 1e-3)
        pad = 60
        scale = min((width - 2 * pad) / span, (height - 2 * pad) / span)

        def to_px(u: float, v: float) -> Tuple[int, int]:
            px = int(pad + (u - umin) * scale)
            py = int(height - pad - (v - vmin) * scale)
            return px, py

        canvas = _Canvas(width, height)
        svg_lines = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#f8fafc"/>',
            f'<text x="16" y="24" font-family="monospace" font-size="14" fill="#0f172a">OpenDatum View: {vname} | Nodes: {len(boxes)} | Clashes: {len(clashes)}</text>',
        ]

        for b in boxes:
            color = DISCIPLINE_COLORS.get(b["discipline"], DISCIPLINE_COLORS["generic"])
            x0, y1 = to_px(b["min"][ax_u], b["min"][ax_v])
            x1, y0 = to_px(b["max"][ax_u], b["max"][ax_v])
            canvas.fill_rect_tint(x0, y0, x1, y1, color, alpha=0.20)
            canvas.draw_rect_outline(x0, y0, x1, y1, color, thickness=2)
            hexc = f"#{color[0]:02x}{color[1]:02x}{color[2]:02x}"
            svg_lines.append(
                f'<rect x="{min(x0,x1)}" y="{min(y0,y1)}" width="{max(2, abs(x1-x0))}" height="{max(2, abs(y1-y0))}" fill="{hexc}" fill-opacity="0.2" stroke="{hexc}" stroke-width="2"/>'
            )
            svg_lines.append(
                f'<text x="{min(x0,x1)+4}" y="{min(y0,y1)+14}" font-family="monospace" font-size="11" fill="#1e293b">{b["name"]}</text>'
            )

        for c in clashes:
            x0, y1 = to_px(c["overlap_box_min"][ax_u], c["overlap_box_min"][ax_v])
            x1, y0 = to_px(c["overlap_box_max"][ax_u], c["overlap_box_max"][ax_v])
            canvas.fill_rect_tint(x0, y0, x1, y1, CLASH_COLOR, alpha=0.45)
            canvas.draw_rect_outline(x0, y0, x1, y1, CLASH_COLOR, thickness=3)
            svg_lines.append(
                f'<rect x="{min(x0,x1)}" y="{min(y0,y1)}" width="{max(4, abs(x1-x0))}" height="{max(4, abs(y1-y0))}" fill="#e61e1e" fill-opacity="0.45" stroke="#b91c1c" stroke-width="3"/>'
            )

        svg_lines.append("</svg>")
        svg_path = out_dir / f"{src_p.stem}_{vname}.svg"
        png_path = out_dir / f"{src_p.stem}_{vname}.png"
        svg_path.write_text("\n".join(svg_lines), encoding="utf-8")
        _write_png_rgb(png_path, width, height, canvas.buf)
        outputs[f"{vname}_svg"] = str(svg_path)
        outputs[f"{vname}_png"] = str(png_path)

    return {
        "status": "ok",
        "source": str(input_path),
        "nodes_rendered": len(boxes),
        "clashes_highlighted": len(clashes),
        "files": outputs,
    }
