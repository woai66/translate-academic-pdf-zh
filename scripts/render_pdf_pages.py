"""Render every output page with Poppler into a fresh, fingerprinted directory."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess

from workflow_support import load_manifest, write_json


def render(config: dict, root: Path, executable: str, dpi: int) -> None:
    destination = root / config["id"]
    if destination.exists():
        raise ValueError(f"render directory already exists; choose a fresh render root: {destination}")
    destination.mkdir(parents=True)
    output = Path(config["output"])
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    subprocess.run([executable, "-r", str(dpi), "-png", str(output), str(destination / "page")],
                   check=True, timeout=300)
    if hashlib.sha256(output.read_bytes()).hexdigest() != digest:
        raise ValueError("PDF changed while rendering; discard renders and retry with a fresh root")
    write_json(destination / "render.json", {"sha256": digest, "dpi": dpi, "renderer": "poppler"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--id", action="append", dest="ids")
    parser.add_argument("--output-tag", default="")
    parser.add_argument("--render-root", required=True, type=Path)
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--pdftoppm", help="path to the Poppler pdftoppm executable")
    args = parser.parse_args()
    if args.dpi < 96:
        parser.error("--dpi must be at least 96")
    executable = args.pdftoppm or shutil.which("pdftoppm")
    if not executable:
        parser.error("Poppler is missing: install poppler/poppler-utils or pass --pdftoppm")
    for config in load_manifest(args.manifest, args.ids, args.output_tag):
        render(config, args.render_root, executable, args.dpi)


if __name__ == "__main__":
    main()
