from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image
import pymupdf
from workflow_support import load_manifest


def page_number(path: Path) -> int:
    return int(path.stem.rsplit("-", 1)[-1])


def inspect_paper(paper_id: str, directory: Path, expected_pages: int) -> dict:
    candidates = list(directory.glob("page-*.png"))
    pages = sorted((p for p in candidates if re.fullmatch(r"page-\d+", p.stem)), key=page_number)
    result = {
        "paper_id": paper_id,
        "expected_pages": expected_pages,
        "rendered_pages": len(pages),
        "errors": [],
        "page_metrics": [],
    }
    if len(candidates) != len(pages):
        result["errors"].append("invalid rendered page filename")
    if [page_number(p) for p in pages] != list(range(1, expected_pages + 1)):
        result["errors"].append("page numbers must be exactly 1 through expected_pages, with no duplicates")
    if len(pages) != expected_pages:
        result["errors"].append(
            f"rendered {len(pages)} pages, expected {expected_pages}"
        )

    previous_size: tuple[int, int] | None = None
    for path in pages:
        with Image.open(path) as image:
            grayscale = image.convert("L")
            grayscale.thumbnail((256, 256))
            pixels = grayscale.tobytes()
            nonwhite_fraction = sum(value < 248 for value in pixels) / max(1, len(pixels))
            dark_fraction = sum(value < 210 for value in pixels) / max(1, len(pixels))
            size = image.size
        number = page_number(path)
        if nonwhite_fraction < 0.0005 or dark_fraction < 0.0001:
            result["errors"].append(
                f"page {number} appears blank: nonwhite={nonwhite_fraction:.6f}"
            )
        if previous_size is not None and number % 2 == 0 and size != previous_size:
            result["errors"].append(
                f"paired page size mismatch at pages {number - 1}/{number}"
            )
        previous_size = size
        result["page_metrics"].append(
            {
                "page": number,
                "width": size[0],
                "height": size[1],
                "nonwhite_fraction": round(nonwhite_fraction, 6),
                "dark_fraction": round(dark_fraction, 6),
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--render-root", required=True, type=Path)
    parser.add_argument("--id", action="append", dest="ids")
    parser.add_argument("--output-tag", default="")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()

    results = []
    for config in load_manifest(args.manifest, args.ids, args.output_tag):
        with pymupdf.open(config["source"]) as document:
            source_pages = document.page_count
        directory = args.render_root / config["id"]
        result = inspect_paper(config["id"], directory, source_pages * 2)
        metadata_path = directory / "render.json"
        if not metadata_path.is_file():
            result["errors"].append("render fingerprint missing; use render_pdf_pages.py")
        else:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            digest = hashlib.sha256(Path(config["output"]).read_bytes()).hexdigest()
            if metadata.get("sha256") != digest:
                result["errors"].append("renders are stale: PDF fingerprint differs")
            if metadata.get("dpi", 0) < 96:
                result["errors"].append("render resolution is below 96 DPI")
        results.append(result)

    summary = {
        "papers": len(results),
        "pages": sum(item["rendered_pages"] for item in results),
        "errors": sum(len(item["errors"]) for item in results),
        "results": results,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({key: summary[key] for key in ("papers", "pages", "errors")}))
    if summary["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
