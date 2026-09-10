"""Shared manifest validation, reference boundaries, and bounded translation I/O."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pymupdf


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def qa_main(check, description: str) -> None:
    import argparse
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output-tag", default="")
    parser.add_argument("--id", action="append", dest="ids")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    configs = load_manifest(args.manifest, args.ids, args.output_tag)
    if args.report.resolve() in {Path(c[k]).resolve() for c in configs for k in ("source", "output")}:
        parser.error("report must not overwrite a PDF")
    results = [check(c) for c in configs]
    summary = {"papers": len(results), "errors": sum(len(r["errors"]) for r in results),
               "warnings": sum(len(r["warnings"]) for r in results), "results": results}
    write_json(args.report, summary)
    print(json.dumps({k: summary[k] for k in ("papers", "errors", "warnings")}))
    if summary["errors"] or summary["warnings"]:
        raise SystemExit(1)


def output_path_for(config: dict, tag: str = "") -> Path:
    if any(c in tag for c in '/\\'):
        raise ValueError("output tag must not contain path separators")
    path = Path(config["output"])
    return path.with_name(path.stem + tag + path.suffix)


def validate_config(config: dict) -> dict:
    if not isinstance(config, dict):
        raise ValueError("each paper must be an object")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", str(config.get("id", ""))):
        raise ValueError("paper id must be 1-100 letters, digits, underscores or hyphens")
    for key in ("source", "output"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"paper {config['id']}: {key} is required")
        if Path(config[key]).suffix.lower() != ".pdf":
            raise ValueError(f"{key} must be a PDF path")
    source, output = Path(config["source"]), Path(config["output"])
    if not source.is_file():
        raise ValueError(f"source PDF does not exist: {source}")
    if source.resolve() == output.resolve() or (output.exists() and source.samefile(output)):
        raise ValueError("source and output must be different files")
    skip = config.get("skip_first_pages", 0)
    if isinstance(skip, bool) or not isinstance(skip, int) or skip < 0:
        raise ValueError("skip_first_pages must be a non-negative integer")
    for key in ("title_en", "title_zh"):
        if not isinstance(config.get(key, ""), str):
            raise ValueError(f"{key} must be text")
    if bool(config.get("title_en")) != bool(config.get("title_zh")):
        raise ValueError("title_en and title_zh must be supplied together")
    for region in config.get("preserve_regions", []):
        if not isinstance(region.get("page"), int) or region["page"] < 1:
            raise ValueError("preserve_regions page must be a positive 1-based page number")
        rect = pymupdf.Rect(region["bbox"])
        if rect.is_empty or rect.is_infinite:
            raise ValueError("preserve_regions bbox must be a finite, non-empty rectangle")
    return config


def load_manifest(path: Path, ids: list[str] | None = None, output_tag: str = "") -> list[dict]:
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(manifest, dict) or not isinstance(manifest.get("papers"), list) or not manifest["papers"]:
        raise ValueError("manifest must contain a non-empty papers array")
    configs = []
    seen = set()
    for item in manifest["papers"]:
        config = dict(item)
        for key in ("source", "output", "translations"):
            if key in config:
                value = Path(config[key])
                config[key] = str((path.parent / value).resolve() if not value.is_absolute() else value.resolve())
        config = validate_config(config)
        if config["id"] in seen:
            raise ValueError(f"duplicate paper id: {config['id']}")
        seen.add(config["id"])
        config["output"] = str(output_path_for(config, output_tag))
        validate_config(config)
        configs.append(config)
    sources = {Path(c["source"]).resolve() for c in configs}
    outputs = [Path(c["output"]).resolve() for c in configs]
    if len(set(outputs)) != len(outputs) or sources.intersection(outputs):
        raise ValueError("outputs must be unique and must not overwrite any source PDF")
    unknown = set(ids or []) - seen
    if unknown:
        raise ValueError(f"unknown paper ids: {', '.join(sorted(unknown))}")
    return [c for c in configs if not ids or c["id"] in ids]


def load_translations(path: str | Path | None) -> dict[str, str]:
    if path is None:
        return {}
    result = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(result, dict) or any(
        not isinstance(k, str) or not k.strip() or not isinstance(v, str) for k, v in result.items()
    ):
        raise ValueError("translations must be a JSON object mapping English text to Chinese text")
    # Empty exported entries remain untranslated; they must never erase source text.
    return {k: v for k, v in result.items() if v.strip()}


class GoogleWebTranslator:
    """Optional web backend. No automatic retries; each request has a timeout."""

    def translate(self, text: str) -> str:
        import requests
        from bs4 import BeautifulSoup

        try:
            response = requests.get(
                "https://translate.google.com/m",
                params={"sl": "en", "tl": "zh-CN", "q": text},
                timeout=(10, 30),
            )
        except requests.RequestException as exc:
            # Requests exceptions can include the complete source text in the URL.
            raise RuntimeError(f"Google translation connection failed ({type(exc).__name__}); use offline input") from None
        with response:
            if response.status_code >= 400:
                raise RuntimeError(f"Google translation returned HTTP {response.status_code}; no retry performed")
            soup = BeautifulSoup(response.text, "html.parser")
            element = soup.select_one(".result-container, .t0")
            if element is None or not element.get_text(strip=True):
                raise RuntimeError("Google web translation returned no result; use reviewed offline translations")
            return element.get_text(strip=True)


def reference_contexts(document: pymupdf.Document) -> list[tuple[str, dict]]:
    import layout_preserving_bilingual_pdf as pipeline

    active = False
    finished = False
    contexts = []
    for page in document:
        rotation = page.rotation
        page.set_rotation(0)
        try:
            start = None if active or finished else pipeline.find_reference_heading_block(page)
            end = pipeline.find_post_reference_heading_block(page) if active or start is not None else None
            if start is not None and end is not None and not pipeline.region_at_or_after_heading(
                end, start, page.rect.width
            ):
                end = None
            mode = "between" if start is not None and end is not None else (
                "start" if start is not None else "resume" if active and end is not None else
                "after" if active else "none"
            )
            contexts.append((mode, {"start": start, "end": end}))
            if start is not None:
                active = True
            if active and end is not None:
                active, finished = False, True
        finally:
            page.set_rotation(rotation)
    return contexts


def preserved_reference_region(bbox, text: str, mode: str, boundaries: dict, width: float) -> bool:
    import layout_preserving_bilingual_pdf as pipeline

    if mode == "none":
        return False
    if mode == "after":
        return True
    after = pipeline.region_at_or_after_heading
    start, end = boundaries.get("start"), boundaries.get("end")
    if start is not None and not after(bbox, start, width):
        return False
    if end is not None and after(bbox, end, width):
        return False
    if start is not None and pipeline.is_reference_heading(text) and abs(bbox.y0 - start.y0) < 1:
        return False
    return True


def protected_block(page: pymupdf.Page, block, regions: list[dict], page_number: int | None = None) -> bool:
    for region in regions:
        if region["page"] == (page_number or page.number + 1) and block.bbox.intersects(pymupdf.Rect(region["bbox"])):
            return True
    if not __import__("layout_preserving_bilingual_pdf").is_caption(block.text):
        for item in page.get_image_info():
            if pymupdf.Rect(item["bbox"]).contains(block.bbox):
                return True
    return False
