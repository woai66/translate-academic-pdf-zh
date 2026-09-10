"""Heuristic content QA; semantic accuracy still requires editorial review."""
from __future__ import annotations
from collections import Counter
import re
import pymupdf
from qa_bilingual_pdfs import selected_blocks
from workflow_support import output_path_for, reference_contexts, qa_main

CJK_PATTERN = re.compile(r"[\u3400-\u9fff]")
CITATION_PATTERN = re.compile(r"\[\s*(\d+(?:\s*[,;–−-]\s*\d+)*)\s*\]")
PLACEHOLDER_PATTERN = re.compile(r"XQZ\d+ZQX")
ENGLISH_RUN_PATTERN = re.compile(r"(?:\b[A-Za-z][A-Za-z-]*\b(?:\s+|[,;:()]\s*)){8,}")
NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def citations(text: str) -> Counter:
    return Counter(re.sub(r"\s+", "", m.group(1)) for m in CITATION_PATTERN.finditer(text))


def qa_paper(config: dict, output_tag: str = "") -> dict:
    result = {"paper_id": config["id"], "errors": [], "warnings": [], "details": []}
    with pymupdf.open(config["source"]) as source, pymupdf.open(output_path_for(config, output_tag)) as output:
        if output.page_count != source.page_count * 2:
            result["errors"].append(f"page count {output.page_count}, expected {source.page_count * 2}")
        contexts = reference_contexts(source)
        for index in range(min(source.page_count, output.page_count // 2)):
            original, chinese = source[index], output[index * 2 + 1]
            original.set_rotation(0)
            chinese.set_rotation(0)
            if PLACEHOLDER_PATTERN.search(chinese.get_text()):
                result["errors"].append(f"page {index + 1}: unresolved placeholder")
            mode, boundaries = contexts[index]
            for block, selected in selected_blocks(original, config, index, mode, boundaries):
                if not selected:
                    continue
                replica = chinese.get_textbox(block.bbox + (-0.15, -0.15, 0.15, 0.15))
                failures = []
                if not CJK_PATTERN.search(replica):
                    failures.append("missing Chinese translation")
                if ENGLISH_RUN_PATTERN.search(replica):
                    failures.append("long untranslated English passage")
                if citations(block.text) != citations(replica):
                    failures.append("numeric citations differ")
                before = Counter(NUMBER_PATTERN.findall(block.text))
                after = Counter(NUMBER_PATTERN.findall(replica))
                if before - after:
                    result["warnings"].append(f"page {index + 1}: numeric data may have changed: {dict(before - after)}")
                if failures:
                    result["errors"].extend(f"page {index + 1}: {failure}" for failure in failures)
                    result["details"].append({"page": index + 1, "source": block.text, "replica": replica})
    return result


if __name__ == "__main__":
    qa_main(qa_paper, __doc__)
