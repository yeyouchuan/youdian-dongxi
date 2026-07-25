#!/usr/bin/env python3
"""Prepare the official Galaxea A1Z/G1Z URDF for MuJoCo.

This is an offline asset conversion helper. It never imports the A1Z hardware
SDK and cannot open a CAN or serial device.
"""

from __future__ import annotations

import argparse
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = (
    REPO_ROOT
    / "simulation/vendor/galaxea-urdf/A1Z/A1Z_G1Z"
)
DEFAULT_OUTPUT = REPO_ROOT / "simulation/generated/a1z_g1z"


def prepare_model(source: Path, output: Path) -> Path:
    """Copy the complete model and add MuJoCo's inertia repair directive."""
    source_urdf = source / "urdf/A1Z_G1Z.urdf"
    source_meshes = source / "meshes"
    if not source_urdf.is_file() or not source_meshes.is_dir():
        raise FileNotFoundError(
            "A1Z assets are missing; clone the official URDF repository first"
        )

    output.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(source_urdf)
    root = tree.getroot()

    mujoco_extension = root.find("mujoco")
    if mujoco_extension is None:
        mujoco_extension = ET.SubElement(root, "mujoco")
    compiler = mujoco_extension.find("compiler")
    if compiler is None:
        compiler = ET.SubElement(mujoco_extension, "compiler")
    compiler.set("balanceinertia", "true")
    compiler.set("discardvisual", "false")

    output_urdf = output / "A1Z_G1Z.urdf"
    ET.indent(tree, space="  ")
    tree.write(output_urdf, encoding="utf-8", xml_declaration=True)

    for mesh in source_meshes.glob("*.STL"):
        shutil.copy2(mesh, output / mesh.name)

    return output_urdf


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output_urdf = prepare_model(args.source.resolve(), args.output.resolve())
    print(output_urdf)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
