"""Python bridge to the compiled Rust `odatum` Universal Spatial Hub core."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


class SpatialHub:
    def __init__(self, binary_path: Optional[Path] = None):
        self.binary = self._resolve_binary(binary_path)

    @staticmethod
    def _resolve_binary(explicit: Optional[Path]) -> Path:
        if explicit and explicit.exists():
            return explicit
        repo_root = Path(__file__).resolve().parents[2]
        candidates = [
            repo_root / "target" / "release" / "odatum",
            repo_root / "target" / "debug" / "odatum",
        ]
        for c in candidates:
            if c.exists():
                return c
        found = shutil.which("odatum")
        if found:
            return Path(found)
        raise FileNotFoundError(
            "Rust `odatum` binary not found. Build it with `cargo build --release` in the repo root."
        )

    def _run(self, args: List[str]) -> Dict[str, Any]:
        proc = subprocess.run(
            [str(self.binary), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"odatum failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
        return json.loads(proc.stdout)

    def inspect(self, input_path: str) -> Dict[str, Any]:
        return self._run(["inspect", input_path])

    def convert(self, input_path: str, output_path: str, target: Optional[str] = None) -> Dict[str, Any]:
        args = ["convert", input_path, output_path]
        if target:
            args.extend(["--target", target])
        return self._run(args)

    def rebuild(
        self,
        input_path: str,
        output_path: str,
        units: str = "m",
        up: str = "y",
        weld_tolerance: float = 1e-5,
        reconstruct_primitives: bool = True,
        strip_mesh: bool = False,
    ) -> Dict[str, Any]:
        args = [
            "rebuild",
            input_path,
            output_path,
            "--units",
            units,
            "--up",
            up,
            "--weld",
            str(weld_tolerance),
        ]
        if not reconstruct_primitives:
            args.append("--no-reconstruct")
        if strip_mesh:
            args.append("--strip-mesh")
        return self._run(args)

    def analyze(self, input_path: str, clearance: float = 0.05) -> Dict[str, Any]:
        return self._run(["analyze", input_path, "--clearance", str(clearance)])

    def merge(self, human_usir_path: str, agent_usir_path: str, output_usir_path: str) -> Dict[str, Any]:
        return self._run(["merge", human_usir_path, agent_usir_path, output_usir_path])

    def sync(
        self,
        usir_path: str,
        godot_path: Optional[str] = None,
        bevy_path: Optional[str] = None,
        gltf_path: Optional[str] = None,
        usd_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        args = ["sync", usir_path]
        if godot_path:
            args.extend(["--godot", godot_path])
        if bevy_path:
            args.extend(["--bevy", bevy_path])
        if gltf_path:
            args.extend(["--gltf", gltf_path])
        if usd_path:
            args.extend(["--usd", usd_path])
        return self._run(args)
