"""Check pairing, original-page fidelity, preserved text, and typesetting."""
from __future__ import annotations
import re
import pymupdf
import layout_preserving_bilingual_pdf as pipeline
from workflow_support import output_path_for, protected_block, reference_contexts, qa_main

CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
BAD_AUTHOR_PATTERN = re.compile(r"(?:等人|等)[。．.]\s*\[\s*\d+")
ISOLATED_CITATION_PATTERN = re.compile(r"^\s*\[\s*\d+(?:\s*[,;–−-]\s*\d+)*\s*\]\s*$")
PUNCTUATION_START = tuple("，。；：！？、,.!?;:）】]")


def normalized(text: str) -> str:
    return re.sub(r"\s+", "", text)


def image_signature(page: pymupdf.Page) -> list:
    return sorted((tuple(round(float(v), 2) for v in item["bbox"]), item["digest"].hex())
                  for item in page.get_image_info(hashes=True))


def selected_blocks(page, config, index, mode, boundaries):
    blocks = []
    for raw in page.get_text("dict", sort=True)["blocks"]:
        block = pipeline.block_from_pdf(raw, page.rect.width)
        if block is None:
            continue
        block.protected = protected_block(page, block, config.get("preserve_regions", []), index + 1)
        blocks.append(block)
    if index == config.get("skip_first_pages", 0):
        blocks = pipeline.merge_manifest_title_blocks(blocks, config.get("title_en", ""), config.get("title_zh", ""))
    for block in blocks:
        selected = pipeline.should_translate(
            block, index + 1, page.rect.width, page.rect.height, config["id"], mode, boundaries,
            index < config.get("skip_first_pages", 0),
        )
        yield block, selected


def qa_paper(config: dict, output_tag: str = "") -> dict:
    result = {"paper_id": config["id"], "errors": [], "warnings": [], "checks": {}, "details": []}
    with pymupdf.open(config["source"]) as source, pymupdf.open(output_path_for(config, output_tag)) as output:
        result["checks"].update(source_pages=source.page_count, output_pages=output.page_count)
        if output.page_count != source.page_count * 2:
            result["errors"].append(f"page count {output.page_count}, expected {source.page_count * 2}")
        contexts = reference_contexts(source)
        for index in range(min(source.page_count, output.page_count // 2)):
            original, english, chinese = source[index], output[index * 2], output[index * 2 + 1]
            number = index + 1
            geometry = lambda p: (tuple(p.rect), tuple(p.mediabox), tuple(p.cropbox), p.rotation)
            if geometry(original) != geometry(english) or geometry(original) != geometry(chinese):
                result["errors"].append(f"page {number}: page geometry/rotation changed")
            if original.get_pixmap().samples != english.get_pixmap().samples or (
                normalized(original.get_text()) != normalized(english.get_text())
            ):
                result["errors"].append(f"page {number}: English original changed or pairing is wrong")
            for page in (original, english, chinese):
                page.set_rotation(0)
            if image_signature(original) != image_signature(chinese):
                result["errors"].append(f"page {number}: image content or position changed")
            mode, boundaries = contexts[index]
            translated_regions = []
            for block, selected in selected_blocks(original, config, index, mode, boundaries):
                box = block.bbox + (-0.15, -0.15, 0.15, 0.15)
                before, after = original.get_textbox(box), chinese.get_textbox(box)
                if selected:
                    translated_regions.append(box)
                    if not after.strip():
                        result["errors"].append(f"page {number}: translated block is empty")
                        result["details"].append({"page": number, "source": block.text})
                elif normalized(before) != normalized(after):
                    result["errors"].append(f"page {number}: preserved text changed")
                    result["details"].append({"page": number, "source": before, "replica": after,
                                              "bbox": list(block.bbox)})
            for raw in chinese.get_text("dict")["blocks"]:
                for line in raw.get("lines", []):
                    rect = pymupdf.Rect(line["bbox"])
                    if not any(rect.intersects(region) for region in translated_regions):
                        continue
                    text = "".join(s["text"] for s in line["spans"]).strip()
                    if BAD_AUTHOR_PATTERN.search(text):
                        result["errors"].append(f"page {number}: punctuation separates author from citation")
                    if ISOLATED_CITATION_PATTERN.fullmatch(text):
                        result["warnings"].append(f"page {number}: isolated citation line")
                    if text.startswith(PUNCTUATION_START) and CJK_PATTERN.search(text):
                        result["warnings"].append(f"page {number}: Chinese line begins with punctuation")
    return result


if __name__ == "__main__":
    qa_main(qa_paper, __doc__)
