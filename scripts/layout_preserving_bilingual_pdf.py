from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from dataclasses import dataclass
from html import escape
from pathlib import Path

import pymupdf


from workflow_support import (
    GoogleWebTranslator, load_manifest, load_translations, output_path_for,
    validate_config, reference_contexts, preserved_reference_region, write_json, protected_block,
)

FONT_REGULAR = pymupdf.Font("cjk")
FONT_BOLD = pymupdf.Font("cjk")
FONT_LATIN = pymupdf.Font("tiro")
FONT_NAME = "CJKRegular"
FONT_BOLD_NAME = "CJKBold"
FONT_ARCHIVE = pymupdf.Archive()
FONT_ARCHIVE.add((FONT_REGULAR.buffer, "regular.otf"))
FONT_ARCHIVE.add((FONT_BOLD.buffer, "bold.otf"))
FONT_ARCHIVE.add((FONT_LATIN.buffer, "latin.otf"))

PROTECTED_PATTERN = re.compile(
    r"https?://\S+"
    r"|\[\s*\d+(?:\s*[,;–−-]\s*\d+)*\s*\]"
    r"|\b(?:Ihat|dhat|XW|W|I|D|L|d)_[A-Za-z]+\b"
    r"|\b[xyw]\[[a-z]\]"
    r"|\b\d+e\^\(-\d+\)"
    r"|δ\s*<\s*1\.25(?:\^[23])?"
    r"|±\d+\.\d+"
    r"|H/\d+\s*×\s*W/\d+\s*×\s*C_\d+"
    r"|H\s*×\s*W\s*×\s*C"
    r"|\b(?:Lite-Mono(?:-tiny|-small|-8M)?|MonoViT(?:-tiny)?|Monodepth2|"
    r"R-MSFM\d?|CDC|LGFI|MHSA|DepthNet|PoseNet|ImageNet|KITTI|Make3D|"
    r"PyTorch|TensorFlow|TinyML|MCUNet|TinyEngine|MobileNet(?:V\d)?|"
    r"ResNet\d*|AlexNet|VGG\d*|YOLO\w*|DNN|CNN|RNN|LSTM|IoT|IIoT|"
    r"RTOS|MEC|DRL|RL|QoS|TCP|UDP|IPv\d|MQTT|CoAP|HTTP|FLOPs?)\b"
)

AUTHOR_CITATION_PATTERN = re.compile(
    r"\b([A-Z][A-Za-z'-]+)\s+et\s+al\.\s*"
    r"(\[\s*\d+(?:\s*,\s*\d+)*\s*\])"
)

MANUAL_TRANSLATIONS = {
    "Abstract": "摘要", "Introduction": "引言", "Conclusions": "结论",
    "Conclusion": "结论", "Acknowledgements": "致谢", "Acknowledgments": "致谢",
    "References": "参考文献", "Bibliography": "参考文献", "Appendix": "附录",
    "Appendices": "附录", "Supplementary Material": "补充材料", "Supplemental Material": "补充材料",
}


@dataclass
class TextBlock:
    bbox: pymupdf.Rect
    text: str
    font_size: float
    bold: bool
    centered: bool
    align: int
    first_line_indent: float
    heading_prefix: str = ""
    horizontal: bool = True
    near_column_start: bool = False
    translation_override: str | None = None
    protected: bool = False


def compact_cjk_spacing(text: str) -> str:
    protected: dict[str, str] = {}

    def protect_author(match: re.Match[str]) -> str:
        token = chr(0xE000 + len(protected))
        protected[token] = match.group(0)
        return token

    text = re.sub(
        r"\b[A-Z][A-Za-z'-]+ 等人 "
        r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]",
        protect_author,
        text,
    )
    text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[A-Za-z0-9\[])", "", text)
    text = re.sub(r"(?<=[A-Za-z0-9\]])\s+(?=[\u3400-\u9fff])", "", text)
    for token, original in protected.items():
        text = text.replace(token, original)
    return text


def clean_source_text(text: str) -> str:
    replacements = {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\u00ad": "",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"(?<=[A-Za-z])-\s+(?=[a-z])", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(
        r"\[\s*(\d+(?:\s*,\s*\d+)*)\s*\]",
        lambda match: "[" + re.sub(r"\s+", "", match.group(1)) + "]",
        text,
    )
    return text


def clean_translation(text: str) -> str:
    text = text.replace("。.", "。").replace("，,", "，")
    text = re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)
    text = re.sub(r"\s+([，。；：！？、])", r"\1", text)
    text = re.sub(r"([，。；：！？、])\s+", r"\1", text)
    text = re.sub(r"([（【])\s+", r"\1", text)
    text = re.sub(r"\s+([）】])", r"\1", text)
    text = re.sub(r"\s*\(\s*(\d+)\s*\)\s*", r"（\1）", text)
    text = re.sub(r"\[(\d+),\s*\[(\d+)\]", r"[\1, \2]", text)
    text = re.sub(
        r"(等人|等)[。．.]\s*(\[\s*\d+(?:\s*,\s*\d+)*\s*\])",
        r"\1 \2",
        text,
    )
    text = re.sub(
        r"\b([A-Z][A-Za-z'-]+)\s+et\s+al\.", r"\1 等人", text
    )
    text = re.sub(r"例如[。.．]\s*例如[，,]?", "例如，", text)
    text = re.sub(
        r"\b([A-Z][A-Za-z'-]+)\s*等人\s*"
        r"(\[\s*\d+(?:\s*,\s*\d+)*\s*\])",
        r"\1 等人 \2",
        text,
    )
    text = re.sub(
        r"(\b[A-Z][A-Za-z'-]+ 等人 "
        r"\[\s*\d+(?:\s*,\s*\d+)*\s*\])\s*"
        r"(?=[A-Za-z\u3400-\u9fff])",
        r"\1 ",
        text,
    )
    return compact_cjk_spacing(text).strip()


def validate_translation(source: str, translated: str) -> str:
    from collections import Counter
    if not isinstance(translated, str) or not translated.strip():
        raise ValueError("translation must not be empty")
    if re.search(r"XQZ\d+ZQX", translated):
        raise ValueError("translation contains unresolved placeholders")
    if re.search(r"[A-Za-z]{3}", source) and not re.search(r"[\u3400-\u9fff]", translated):
        raise ValueError("translation contains no Chinese text; review this block manually")
    citation = r"\[\s*\d+(?:\s*[,;–−-]\s*\d+)*\s*\]"
    extract = lambda text: Counter(re.sub(r"\s+", "", v) for v in re.findall(citation, text))
    if extract(source) != extract(translated):
        raise ValueError("translation changes numeric citations")
    return translated.strip()


def translate_text(text: str, translator, cache_dir: Path, translations: dict | None = None) -> str:
    source = clean_source_text(text)
    if translations and source in translations:
        return validate_translation(source, translations[source])
    if source in MANUAL_TRANSLATIONS:
        return MANUAL_TRANSLATIONS[source]
    # Hash the complete source, including citations and terms hidden by placeholders.
    digest = hashlib.sha256(("public-v1|en|zh-CN|" + source).encode("utf-8")).hexdigest()
    cache_path = cache_dir / f"{digest}.txt"
    if cache_path.exists():
        return validate_translation(source, cache_path.read_text(encoding="utf-8"))
    if translator is None:
        raise ValueError(f"missing offline translation: {source[:160]}")
    protected = {}

    def protect(match):
        token = f"XQZ{len(protected)}ZQX"
        protected[token] = match.group(0)
        return token

    def protect_author(match):
        token = f"XQZ{len(protected)}ZQX"
        protected[token] = f"{match.group(1)} 等人 {match.group(2)}"
        return token

    protected_source = AUTHOR_CITATION_PATTERN.sub(protect_author, source)
    protected_source = PROTECTED_PATTERN.sub(protect, protected_source)
    chunks = []
    while len(protected_source) > 4000:
        boundary = protected_source.rfind(" ", 0, 4000)
        if boundary <= 0:
            raise ValueError("unbreakable translation input exceeds 4000 characters")
        chunks.append(protected_source[:boundary])
        protected_source = protected_source[boundary:].lstrip()
    chunks.append(protected_source)
    outputs = []
    for chunk in chunks:
        value = translator.translate(chunk)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("translation service returned an empty response")
        outputs.append(value)
    translated = " ".join(outputs)
    for token, original in protected.items():
        if translated.count(token) != 1:
            raise ValueError(f"translation service changed protected token {token}")
        translated = translated.replace(token, original)
    translated = validate_translation(source, clean_translation(translated))
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(".tmp")
    temporary.write_text(translated, encoding="utf-8")
    temporary.replace(cache_path)
    return translated


def block_from_pdf(block: dict, page_width: float) -> TextBlock | None:
    if block.get("type") != 0:
        return None
    spans = [span for line in block["lines"] for span in line["spans"]]
    if not spans:
        return None
    text = clean_source_text(" ".join(span["text"] for span in spans))
    if not text:
        return None

    sizes = [float(span["size"]) for span in spans if span["text"].strip()]
    bold_characters = sum(
        len(span["text"].strip())
        for span in spans
        if any(
            token in span["font"].lower()
            for token in ("bold", "medi", "demi")
        )
    )
    total_characters = max(1, sum(len(span["text"].strip()) for span in spans))
    bold = bold_characters / total_characters >= 0.58
    heading_prefix_parts: list[str] = []
    if re.match(r"^\d+(?:\.\d+)*\.?\s+[A-Z]", text):
        for span in spans:
            span_text = span["text"]
            span_is_bold = any(
                token in span["font"].lower()
                for token in ("bold", "medi", "demi")
            )
            if not span_is_bold and heading_prefix_parts:
                break
            if span_is_bold:
                heading_prefix_parts.append(span_text)
    heading_prefix = clean_source_text(" ".join(heading_prefix_parts))
    bbox = pymupdf.Rect(block["bbox"])
    x_ratio = bbox.x0 / max(page_width, 1.0)
    near_column_start = x_ratio <= 0.23 or 0.49 <= x_ratio <= 0.56
    text_lines = [
        line
        for line in block["lines"]
        if any(span["text"].strip() for span in line["spans"])
    ]
    horizontal = all(
        abs(float(line.get("dir", (1.0, 0.0))[0]) - 1.0) < 0.01
        and abs(float(line.get("dir", (1.0, 0.0))[1])) < 0.01
        for line in text_lines
    )
    line_boxes = [pymupdf.Rect(line["bbox"]) for line in text_lines]
    if bbox.x1 <= page_width / 2:
        expected_center = page_width * 0.275
    elif bbox.x0 >= page_width / 2:
        expected_center = page_width * 0.6975
    else:
        expected_center = page_width / 2
    line_centers = [(line.x0 + line.x1) / 2 for line in line_boxes]
    left_edges = [line.x0 for line in line_boxes]
    left_aligned_multiline = (
        len(left_edges) > 1 and max(left_edges) - min(left_edges) <= 2.5
    )
    geometrically_centered = (
        bool(line_centers)
        and not left_aligned_multiline
        and all(
            abs(center - expected_center) < page_width * 0.035
            for center in line_centers
        )
    )
    caption_like = bool(
        re.match(r"^(?:Figure|Fig\.|Table)\s+\d+", text, re.IGNORECASE)
    )
    # Fully justified body text also has line centers close to the column
    # center. Only headings and captions may inherit geometric centering.
    centered = geometrically_centered and (
        caption_like or (not near_column_start and (bold or (max(sizes) if sizes else 0.0) >= 11.0))
    )
    first_line_indent = 0.0
    if len(text_lines) >= 2:
        first_x0 = float(text_lines[0]["bbox"][0])
        common_x0 = statistics.median(
            float(line["bbox"][0]) for line in text_lines[1:]
        )
        measured_indent = first_x0 - common_x0
        if 3.0 <= abs(measured_indent) <= 24.0:
            first_line_indent = measured_indent
    return TextBlock(
        bbox=bbox,
        text=text,
        font_size=max(sizes) if sizes else 9.0,
        bold=bold,
        centered=centered,
        align=pymupdf.TEXT_ALIGN_CENTER if centered else pymupdf.TEXT_ALIGN_LEFT,
        first_line_indent=first_line_indent,
        heading_prefix=heading_prefix,
        horizontal=horizontal,
        near_column_start=near_column_start,
    )


def normalized_title(text: str) -> str:
    return re.sub(r"\s+", " ", clean_source_text(text)).strip().casefold()


def split_title_lines(title: str, line_count: int) -> str:
    # Keep editorial line breaks; character-count splitting can divide Chinese words.
    return title


def merge_manifest_title_blocks(
    blocks: list[TextBlock],
    title_en: str,
    title_zh: str,
) -> list[TextBlock]:
    if not title_en or not title_zh:
        return blocks
    expected = normalized_title(title_en)
    for start in range(len(blocks)):
        for end in range(start + 1, min(len(blocks), start + 4) + 1):
            matched = blocks[start:end]
            combined = normalized_title(" ".join(block.text for block in matched))
            if combined != expected:
                continue
            bbox = pymupdf.Rect(matched[0].bbox)
            for block in matched[1:]:
                bbox.include_rect(block.bbox)
            merged = TextBlock(
                bbox=bbox,
                text=title_en,
                font_size=max(block.font_size for block in matched),
                bold=any(block.bold for block in matched),
                centered=True,
                align=pymupdf.TEXT_ALIGN_CENTER,
                first_line_indent=0.0,
                horizontal=all(block.horizontal for block in matched),
                near_column_start=False,
                translation_override=split_title_lines(title_zh, len(matched)),
            )
            return blocks[:start] + [merged] + blocks[end:]
    return blocks


def is_caption(text: str) -> bool:
    return bool(re.match(r"^(?:Figure|Fig\.|Table)\s+\d+", text, re.IGNORECASE))


def is_reference_heading(text: str) -> bool:
    value = clean_source_text(text).strip(" .:")
    return bool(
        re.fullmatch(
            r"(?:(?:\d+(?:\.\d+)*|[IVX]+)[.)]?\s+)?"
            r"(?:references|bibliography)",
            value,
            re.IGNORECASE,
        )
    )


def is_post_reference_heading(text: str) -> bool:
    value = clean_source_text(text).strip(" .:")
    return bool(
        re.fullmatch(
            r"(?:appendix|appendices|supplementary material|supplemental material)"
            r"(?:\s+[A-Z0-9]+(?:[.:]\s*.*|\s+.*)?|\s*[:.]\s+.*)?",
            value,
            re.IGNORECASE,
        )
        or re.match(
            r"^note\s*:\s*appendices\s+are\s+supporting\s+material\b",
            value,
            re.IGNORECASE,
        )
    )


def region_at_or_after_heading(
    bbox: pymupdf.Rect,
    boundary: pymupdf.Rect,
    page_width: float,
) -> bool:
    heading_in_left_column = boundary.x1 < page_width * 0.58
    heading_in_right_column = boundary.x0 > page_width * 0.48
    if heading_in_left_column:
        return bbox.x0 > page_width * 0.48 or bbox.y0 >= boundary.y0
    if heading_in_right_column:
        return bbox.x0 > page_width * 0.48 and bbox.y0 >= boundary.y0
    return bbox.y0 >= boundary.y0


def is_heading(block: TextBlock) -> bool:
    text = block.text
    if text in MANUAL_TRANSLATIONS:
        return True
    letters = sum(char.isalpha() for char in text)
    visible = max(1, sum(not char.isspace() for char in text))
    symbols = sum(not char.isalnum() and not char.isspace() for char in text)
    heading_keyword = bool(
        re.search(
            r"\b(?:introduction|conclusions?|acknowledgements?|glossary|"
            r"background|related work|methodology|evaluation|experiments?|"
            r"results?|discussion|training|architecture|appendix|appendices|"
            r"supplementary material|supplemental material)\b",
            text,
            re.IGNORECASE,
        )
    )
    large_heading = (
        block.font_size >= 11.0
        and len(text) <= 160
        and letters >= 4
        and symbols / visible < 0.25
        and (
            block.bold
            or block.centered
            or block.near_column_start
            or heading_keyword
        )
    )
    numbered_heading = bool(
        re.match(
            r"^(?:\d+(?:\.\d+)*\.?|(?:[IVXLC]+|[A-Z])\.)\s+[A-Z]",
            text,
        )
        and len(text) <= 80
        and len(text.split()) <= 10
        and (block.near_column_start or block.bold or heading_keyword)
    )
    return bool(
        large_heading
        or numbered_heading
        or text in {
            "Conclusions",
            "Acknowledgements",
            "Acknowledgments",
            "References",
            "Bibliography",
            "Appendix",
            "Appendices",
            "Supplementary Material",
            "Supplemental Material",
            "Contents",
        }
    )


def polish_block_translation(block: TextBlock, text: str) -> str:
    if block.text.startswith("‚"):
        text = re.sub(r"^[，,、]\s*", "• ", text)
    if block.text.startswith(". "):
        text = re.sub(r"^[。．.]\s*", "", text)
    if is_heading(block):
        source_number = re.match(
            r"^((?:\d+(?:\.\d+)*)\.?|(?:[IVXLC]+|[A-Z])\.)\s+",
            block.text,
        )
        if source_number:
            text = re.sub(
                r"^\s*(?:\d+(?:\.\d+)*|[IVXLC]+|[A-Z]|"
                r"[一二三四五六七八九十百]+)(?:[.、．])?\s*",
                "",
                text,
            )
            text = f"{source_number.group(1).rstrip('.')}. {text}"
    if is_caption(block.text):
        source_caption = re.match(
            r"^(Figure|Fig\.|Table)\s+(\d+)\.",
            block.text,
            re.IGNORECASE,
        )
        if source_caption:
            label = "表" if source_caption.group(1).lower() == "table" else "图"
            text = re.sub(
                r"^(?:图|表)\s*\d+\s*[。.．]?\s*", "", text
            )
            text = f"{label} {source_caption.group(2)} {text}"
    text = re.sub(r"\s*×\s*", " × ", text)
    return text.strip()


def should_translate(
    block: TextBlock,
    page_number: int,
    page_width: float,
    page_height: float,
    paper_id: str,
    references_mode: str,
    reference_boundary: dict,
    skip_translation: bool,
) -> bool:
    text = block.text
    bbox = block.bbox

    if skip_translation or block.protected:
        return False
    if not block.horizontal:
        return False

    if preserved_reference_region(block.bbox, text, references_mode, reference_boundary, page_width):
        return False
    if is_reference_heading(text) or block.translation_override is not None:
        return True

    # Preserve running page numbers, author identity, e-mail addresses, and the
    # open-access watermark. They are metadata rather than reading content.
    if bbox.y0 < page_height * 0.04 or bbox.y0 > page_height * 0.93:
        return False
    if (
        bbox.y0 < page_height * 0.10
        and bbox.width > page_width * 0.45
        and bbox.height < page_height * 0.04
    ):
        return False
    if (
        page_number > 1
        and bbox.y0 < page_height * 0.10
        and re.match(rf"^[:;,.]?\s*{page_number}\s+[A-Z]", text)
    ):
        return False
    if bbox.y0 > page_height * 0.78 and block.font_size < 7.5:
        return False
    if "@" in text:
        return False
    if re.match(r"^arXiv:\d", text, re.IGNORECASE):
        return False
    if "Publication date:" in text:
        return False
    if page_number == 1 and re.search(
        r"\b(?:University|Institute|Department|Laboratory|School of|College|"
        r"Corporation|Research Center)\b",
        text,
        re.IGNORECASE,
    ):
        return False
    if page_number == 1 and re.search(
        r"Permission to make|ACM Reference Format|Copyright|All rights reserved",
        text,
        re.IGNORECASE,
    ):
        return False


    # Preserve table cells and labels inside the vector architecture diagram.
    # Their alignment depends on the source artwork and cannot be reflowed as
    # prose without changing the figure itself.

    if is_caption(text) or is_heading(block):
        return True
    if re.match(r"^ACKNOWLEDGMENTS?\b", text, re.IGNORECASE):
        return True

    letters = sum(char.isalpha() for char in text)
    digits = sum(char.isdigit() for char in text)
    symbols = sum(not char.isalnum() and not char.isspace() for char in text)
    visible = max(1, sum(not char.isspace() for char in text))

    # Small labels, mathematical fragments, and table cells are kept intact.
    if block.font_size < 7.0:
        return False
    if letters < 18 or len(text.split()) < 4:
        return False
    if digits / visible > 0.22 or symbols / visible > 0.24:
        return False
    return True


def choose_font_size(
    block: TextBlock,
    text: str,
    font_path: pymupdf.Font,
    font_name: str,
) -> tuple[float, float]:
    heading = is_heading(block)
    line_height = 1.18 if heading else 1.28
    initial_size = min(block.font_size * 0.82, 8.2)
    if is_caption(block.text):
        initial_size = min(block.font_size * 0.86, 8.2)
    return max(5.3, round(initial_size, 2)), line_height


def insert_single_line(
    page: pymupdf.Page,
    block: TextBlock,
    text: str,
    font_path: pymupdf.Font,
    font_name: str,
) -> bool:
    font = font_path
    font_size = min(block.font_size, 13.2)
    usable_width = max(5, block.bbox.width - 1.0)
    while font_size >= 5.2:
        text_width = font.text_length(text, fontsize=font_size)
        if text_width <= usable_width:
            x = block.bbox.x0 + 0.4
            if block.centered:
                x = (block.bbox.x0 + block.bbox.x1 - text_width) / 2
            baseline = block.bbox.y1 - max(0.6, font_size * 0.08)
            page.insert_text(
                pymupdf.Point(x, baseline),
                text,
                fontname=font_name,
                fontsize=font_size,
                color=(0, 0, 0),
            )
            return True
        font_size -= 0.25
    return False


def insert_manifest_title(
    page: pymupdf.Page,
    block: TextBlock,
    text: str,
    font_name: str,
) -> bool:
    target = pymupdf.Rect(block.bbox)
    target.x0 += 0.4
    target.x1 -= 0.4
    target.y1 += 1.2
    font_size = min(block.font_size, 24.0)
    font = FONT_BOLD if font_name == FONT_BOLD_NAME else FONT_REGULAR
    widest = max(font.text_length(line, fontsize=1) for line in text.splitlines())
    if widest:
        font_size = min(font_size, (target.width - 0.5) / widest)
    result = -1.0
    while result < 0 and font_size >= 8.0:
        result = page.insert_textbox(
            target,
            text,
            fontname=font_name,
            fontsize=font_size,
            lineheight=1.0,
            align=pymupdf.TEXT_ALIGN_CENTER,
            color=(0, 0, 0),
        )
        if result < 0:
            font_size -= 0.25
    return result >= 0


def rich_text_html(text: str, bold_lead: bool = False) -> str:
    html = escape(text).replace("\n", "<br>")
    for heading in ("致谢", "摘要", "结论"):
        prefix = heading + "<br>"
        if html.startswith(prefix):
            html = f"<strong>{heading}</strong><br>" + html[len(prefix):]
            break
    if bold_lead:
        lead = re.match(r"^(.+?[。！？：])", html)
        if lead:
            html = f"<strong>{lead.group(1)}</strong>{html[lead.end():]}"
    html = re.sub(
        r"(?<![A-Za-z0-9])(?:Lite-Mono(?:-tiny|-small|-8M)?|MonoViT(?:-tiny)?|"
        r"Monodepth2|R-MSFM\d?|DepthNet|PoseNet|ESPNetv2|Transformer|"
        r"ResNet(?:18|50)?|Make3D|ImageNet|KITTI|CDC|LGFI|MHSA|FLOPs?)"
        r"(?![A-Za-z0-9])",
        lambda match: f'<span class="term">{match.group(0)}</span>',
        html,
    )
    html = re.sub(
        r"(?<![A-Za-z0-9])([HW])/(\d+)",
        r'<span class="math"><i>\1</i>/\2</span>',
        html,
    )
    html = re.sub(
        r"(?<![A-Za-z0-9])([Id])hat_([A-Za-z0-9]+)(?![A-Za-z0-9])",
        r'<span class="math"><i>\1&#770;</i><sub>\2</sub></span>',
        html,
    )
    html = re.sub(
        r"(?<![A-Za-z0-9])([A-Za-z]+)_([A-Za-z0-9]+)(?![A-Za-z0-9])",
        r'<span class="math"><i>\1</i><sub>\2</sub></span>',
        html,
    )
    html = re.sub(
        r"(?<![A-Za-z0-9])(\d+)e\^\(-(\d+)\)",
        r'<span class="math">\1e<sup>-\2</sup></span>',
        html,
    )
    html = re.sub(
        r"1\.25\^([23])",
        r'<span class="math">1.25<sup>\1</sup></span>',
        html,
    )
    html = re.sub(
        r"(?<![A-Za-z0-9])([xyw])\[([a-z])\]",
        r'<span class="math"><i>\1</i>[<i>\2</i>]</span>',
        html,
    )
    html = re.sub(
        r"(?P<space>\s*)"
        r"(?P<citation>\[\s*\d+(?:\s*,\s*\d+)*\s*\])",
        lambda match: (
            ("&#160;" if match.group("space") else "&#8288;")
            + f'<span class="citation">{match.group("citation")}</span>'
        ),
        html,
    )
    html = re.sub(
        r"(?<=[\u3400-\u9fffA-Za-z0-9%×）】\]>])([，。；：！？、）】])",
        r"&#8288;\1",
        html,
    )
    return html


def caption_rich_text_html(text: str) -> str:
    match = re.match(r"^((?:图|表)\s+\d+\s+)([^。]+。)(.*)$", text)
    if not match:
        return rich_text_html(text)
    label, title, remainder = match.groups()
    return (
        rich_text_html(label)
        + f"<strong>{rich_text_html(title)}</strong>"
        + rich_text_html(remainder)
    )


def insert_caption(
    page: pymupdf.Page,
    block: TextBlock,
    text: str,
    font_size: float,
    line_height: float,
) -> tuple[bool, float]:
    alignment = "center" if block.centered else "left"
    css = f"""
        @font-face {{
            font-family: SimSunLocal;
            src: url('regular.otf');
        }}
        @font-face {{
            font-family: TimesLocal;
            src: url('latin.otf');
        }}
        @font-face {{
            font-family: BoldLocal;
            src: url('bold.otf');
        }}
        p {{
            font-family: TimesLocal, SimSunLocal;
            font-size: {font_size:.2f}pt;
            line-height: {line_height:.3f};
            text-align: {alignment};
            text-justify: inter-character;
            letter-spacing: 0;
            word-spacing: 0;
            text-indent: 0;
            margin: 0;
            padding: 0;
        }}
        strong {{
            font-family: BoldLocal, TimesLocal, SimSunLocal;
            font-weight: normal;
        }}
        .math {{
            font-family: TimesLocal, SimSunLocal;
            white-space: nowrap;
        }}
        .citation, .term {{
            white-space: nowrap;
        }}
        sub, sup {{
            font-size: 72%;
            line-height: 0;
        }}
    """
    target = pymupdf.Rect(block.bbox)
    target.x0 += 0.3
    target.x1 -= 0.3
    target.y1 += 0.5
    spare_height, scale = page.insert_htmlbox(
        target,
        f"<p>{caption_rich_text_html(text)}</p>",
        css=css,
        archive=FONT_ARCHIVE,
        scale_low=0.72,
        overlay=True,
    )
    return spare_height >= 0, scale


def insert_justified_paragraph(
    page: pymupdf.Page,
    block: TextBlock,
    text: str,
    font_size: float,
    line_height: float,
) -> tuple[bool, float]:
    hanging_indent = max(0.0, -block.first_line_indent)
    css = f"""
        @font-face {{
            font-family: SimSunLocal;
            src: url('regular.otf');
        }}
        @font-face {{
            font-family: TimesLocal;
            src: url('latin.otf');
        }}
        @font-face {{
            font-family: BoldLocal;
            src: url('bold.otf');
        }}
        p {{
            font-family: TimesLocal, SimSunLocal;
            font-size: {font_size:.2f}pt;
            line-height: {line_height:.3f};
            text-align: justify;
            text-justify: auto;
            letter-spacing: 0;
            word-spacing: 0;
            text-indent: {block.first_line_indent:.2f}pt;
            margin: 0;
            padding: 0 0 0 {hanging_indent:.2f}pt;
            box-sizing: border-box;
        }}
        .math {{
            font-family: TimesLocal, SimSunLocal;
            white-space: nowrap;
        }}
        .citation, .term {{
            white-space: nowrap;
        }}
        strong {{
            font-family: BoldLocal, TimesLocal, SimSunLocal;
            font-weight: normal;
        }}
        sub, sup {{
            font-size: 72%;
            line-height: 0;
        }}
    """
    target = pymupdf.Rect(block.bbox)
    target.x0 += 0.3
    target.x1 -= 0.3
    target.y1 += 0.5
    spare_height, scale = page.insert_htmlbox(
        target,
        f"<p>{rich_text_html(text, bold_lead=bool(block.heading_prefix))}</p>",
        css=css,
        archive=FONT_ARCHIVE,
        scale_low=0.72,
        overlay=True,
    )
    return spare_height >= 0, scale


def translate_page(
    page: pymupdf.Page,
    page_number: int,
    translator: GoogleWebTranslator | None,
    cache_dir: Path,
    paper_id: str,
    references_mode: str,
    reference_boundary: dict,
    skip_translation: bool,
    title_en: str = "",
    title_zh: str = "",
    translations: dict | None = None,
    preserve_regions: list[dict] | None = None,
) -> tuple[int, list[str]]:
    blocks: list[TextBlock] = []
    page_blocks: list[TextBlock] = []
    for raw_block in page.get_text("dict", sort=True)["blocks"]:
        block = block_from_pdf(raw_block, page.rect.width)
        if block:
            block.protected = protected_block(page, block, preserve_regions or [], page_number)
            page_blocks.append(block)
    if title_en and not skip_translation:
        page_blocks = merge_manifest_title_blocks(page_blocks, title_en, title_zh)
    for block in page_blocks:
        if should_translate(block, page_number, page.rect.width, page.rect.height,
                            paper_id, references_mode, reference_boundary, skip_translation):
            blocks.append(block)

    translated: list[tuple[TextBlock, str]] = []
    for block in blocks:
        source_text = block.text
        chinese = block.translation_override
        if chinese is None:
            chinese = translate_text(source_text, translator, cache_dir, translations)
        if block.translation_override is None:
            chinese = polish_block_translation(block, chinese)
        translated.append((block, chinese.strip()))

    for block in [item[0] for item in translated]:
        redact = pymupdf.Rect(block.bbox)
        redact.x0 -= 0.7
        redact.y0 -= 0.4
        redact.x1 += 0.7
        redact.y1 += 0.6
        page.add_redact_annot(redact, fill=False)
    if translated:
        page.apply_redactions(images=0, graphics=0)

    page.insert_font(fontname=FONT_NAME, fontbuffer=FONT_REGULAR.buffer)
    page.insert_font(fontname=FONT_BOLD_NAME, fontbuffer=FONT_BOLD.buffer)

    overflow: list[str] = []
    for block, chinese in translated:
        font_path = FONT_BOLD if block.bold or is_heading(block) else FONT_REGULAR
        font_name = FONT_BOLD_NAME if block.bold or is_heading(block) else FONT_NAME

        if block.translation_override is not None:
            if not insert_manifest_title(page, block, chinese, font_name):
                overflow.append(block.text[:100])
            continue

        if is_heading(block) and "\n" not in chinese:
            if not insert_single_line(
                page, block, chinese, font_path, font_name
            ):
                overflow.append(block.text[:100])
            continue

        font_size, line_height = choose_font_size(
            block, chinese, font_path, font_name
        )


        if is_caption(block.text):
            inserted, scale = insert_caption(
                page,
                block,
                chinese,
                font_size,
                line_height,
            )
            if not inserted or scale < 0.72:
                overflow.append(block.text[:100])
            continue

        if block.align == pymupdf.TEXT_ALIGN_LEFT:
            inserted, scale = insert_justified_paragraph(
                page,
                block,
                chinese,
                font_size,
                line_height,
            )
            if not inserted or scale < 0.72:
                overflow.append(block.text[:100])
            continue

        target = pymupdf.Rect(block.bbox)
        target.x0 += 0.4
        target.x1 -= 0.4
        target.y1 += 1.0 if is_heading(block) else 0.3
        result = -1.0
        while result < 0 and font_size >= 5.0:
            result = page.insert_textbox(
                target,
                chinese,
                fontname=font_name,
                fontsize=font_size,
                lineheight=line_height,
                align=block.align,
                color=(0, 0, 0),
            )
            if result < 0:
                font_size -= 0.25
        if result < 0:
            overflow.append(block.text[:100])
    return len(translated), overflow


def find_reference_heading_block(page: pymupdf.Page) -> pymupdf.Rect | None:
    for raw_block in page.get_text("dict", sort=True)["blocks"]:
        block = block_from_pdf(raw_block, page.rect.width)
        if block and is_reference_heading(block.text):
            return pymupdf.Rect(block.bbox)
    return None


def find_post_reference_heading_block(page: pymupdf.Page) -> pymupdf.Rect | None:
    for raw_block in page.get_text("dict", sort=True)["blocks"]:
        block = block_from_pdf(raw_block, page.rect.width)
        if block and is_post_reference_heading(block.text):
            return pymupdf.Rect(block.bbox)
    return None


def build(
    source: Path,
    output: Path,
    cache_dir: Path,
    paper_id: str = "generic",
    title_en: str = "",
    title_zh: str = "",
    skip_first_pages: int = 0,
    translator=None,
    translations: dict | None = None,
    preserve_regions: list[dict] | None = None,
) -> dict:
    import tempfile
    config = validate_config({
        "id": paper_id, "source": str(source), "output": str(output),
        "title_en": title_en, "title_zh": title_zh, "skip_first_pages": skip_first_pages,
        "preserve_regions": preserve_regions or [],
    })
    cache_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = None
    try:
        with pymupdf.open(source) as source_doc, pymupdf.open() as output_doc:
            if source_doc.needs_pass or not source_doc.page_count:
                raise ValueError("source must be a non-empty, unencrypted PDF")
            if skip_first_pages >= source_doc.page_count:
                raise ValueError("skip_first_pages must leave at least one page to translate")
            contexts = reference_contexts(source_doc)
            page_stats = []
            for page_index, (mode, boundaries) in enumerate(contexts):
                output_doc.insert_pdf(source_doc, from_page=page_index, to_page=page_index)
                output_doc.insert_pdf(source_doc, from_page=page_index, to_page=page_index)
                chinese_page = output_doc[-1]
                rotation = chinese_page.rotation
                chinese_page.set_rotation(0)
                skipped = page_index < skip_first_pages
                if not skipped and not chinese_page.get_text("text").strip():
                    raise ValueError(f"page {page_index + 1} has no text layer; OCR or manual review is required")
                if page_index == skip_first_pages and title_en:
                    blocks = [block_from_pdf(b, chinese_page.rect.width)
                              for b in chinese_page.get_text("dict", sort=True)["blocks"]]
                    merged = merge_manifest_title_blocks([b for b in blocks if b], title_en, title_zh)
                    if not any(b.translation_override is not None for b in merged):
                        raise ValueError("reviewed title does not match extracted title blocks on the first translated page")
                count, overflow = translate_page(
                    chinese_page, page_index + 1, translator, cache_dir, paper_id, mode, boundaries,
                    skipped, title_en if page_index == skip_first_pages else "",
                    title_zh if page_index == skip_first_pages else "", translations, preserve_regions,
                )
                chinese_page.set_rotation(rotation)
                page_stats.append({"source_page": page_index + 1, "translated_blocks": count,
                                   "overflow": overflow, "references_mode": mode, "skipped": skipped})
            result = {"source_pages": source_doc.page_count, "output_pages": output_doc.page_count,
                      "paper_id": paper_id, "output": str(output), "page_stats": page_stats,
                      "errors": [], "written": False}
            for stats in page_stats:
                if stats["overflow"]:
                    result["errors"].append(f"page {stats['source_page']}: text overflow")
            if not sum(s["translated_blocks"] for s in page_stats):
                result["errors"].append("no translatable blocks found; review the source layout")
            if result["errors"]:
                return result
            metadata = source_doc.metadata.copy()
            metadata.update({"title": f"{title_zh} / {title_en}" if title_en else source.stem,
                             "subject": "English source pages interleaved with Chinese replicas",
                             "creator": "translate-academic-pdf-zh"})
            output_doc.set_metadata(metadata)
            toc = source_doc.get_toc()
            if toc:
                output_doc.set_toc([[level, title, (page - 1) * 2 + 1 if page > 0 else page]
                                    for level, title, page in toc])
            with tempfile.NamedTemporaryFile(prefix="bilingual-", suffix=".pdf", dir=output.parent,
                                             delete=False) as temp:
                temporary_output = Path(temp.name)
            output_doc.save(temporary_output, garbage=4, deflate=True)
        temporary_output.replace(output)
        result["written"] = True
        return result
    finally:
        if temporary_output is not None:
            temporary_output.unlink(missing_ok=True)


def export_translations(config: dict) -> dict[str, str]:
    values = {}
    with pymupdf.open(config["source"]) as document:
        if document.needs_pass:
            raise ValueError("encrypted source is not supported")
        for index, (mode, boundaries) in enumerate(reference_contexts(document)):
            page = document[index]
            page.set_rotation(0)
            for raw in page.get_text("dict", sort=True)["blocks"]:
                block = block_from_pdf(raw, page.rect.width)
                if block is None:
                    continue
                block.protected = protected_block(page, block, config.get("preserve_regions", []), index + 1)
                if should_translate(block, index + 1, page.rect.width, page.rect.height, config["id"],
                                    mode, boundaries, index < config.get("skip_first_pages", 0)):
                    values[block.text] = MANUAL_TRANSLATIONS.get(block.text, "")
    if config.get("title_en"):
        values[clean_source_text(config["title_en"])] = config["title_zh"]
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Build layout-preserving bilingual PDF drafts; offline by default.")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--paper-id", default="generic")
    parser.add_argument("--title-en", default="")
    parser.add_argument("--title-zh", default="")
    parser.add_argument("--skip-first-pages", type=int, default=0)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--id", action="append", dest="ids")
    parser.add_argument("--output-tag", default="")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path("tmp/pdfs/translation_cache"))
    parser.add_argument("--translations", type=Path, help="reviewed English-to-Chinese JSON mapping (single PDF)")
    parser.add_argument("--allow-network", action="store_true", help="send uncached prose to Google's web service")
    parser.add_argument("--export-text", type=Path, help="export untranslated blocks as JSON instead of building")
    args = parser.parse_args()
    try:
        if args.manifest:
            if args.source or args.output or args.translations:
                raise ValueError("--manifest cannot be combined with --source, --output or --translations")
            configs = load_manifest(args.manifest, args.ids, args.output_tag)
        else:
            if not args.source or not args.output:
                raise ValueError("--source and --output are required without --manifest")
            if args.ids:
                raise ValueError("--id requires --manifest; use --paper-id for a single PDF")
            config = {"id": args.paper_id, "source": str(args.source), "output": str(args.output),
                      "title_en": args.title_en, "title_zh": args.title_zh,
                      "skip_first_pages": args.skip_first_pages}
            config["output"] = str(output_path_for(config, args.output_tag))
            if args.translations:
                config["translations"] = str(args.translations)
            configs = [validate_config(config)]
        protected_paths = {Path(c[k]).resolve() for c in configs for k in ("source", "output", "translations") if k in c}
        if args.manifest:
            protected_paths.add(args.manifest.resolve())
        for candidate in (args.report, args.export_text):
            if candidate and candidate.resolve() in protected_paths:
                raise ValueError("report/export path must not overwrite a source, output, manifest or translations")
        if args.export_text:
            if len(configs) != 1:
                raise ValueError("--export-text requires exactly one paper; select it with --id")
            if args.export_text.exists():
                raise ValueError("export destination already exists; use a new path to preserve reviewed translations")
            write_json(args.export_text, export_translations(configs[0]))
            return
        translator = GoogleWebTranslator() if args.allow_network else None
        results = []
        for config in configs:
            result = build(Path(config["source"]), Path(config["output"]), args.cache_dir / config["id"],
                           config["id"], config.get("title_en", ""), config.get("title_zh", ""),
                           config.get("skip_first_pages", 0), translator,
                           load_translations(config.get("translations")), config.get("preserve_regions", []))
            results.append(result)
        if args.report:
            write_json(args.report, results)
        print(json.dumps(results, ensure_ascii=True, indent=2))
        if any(r["errors"] for r in results):
            raise SystemExit(1)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.exit(1, f"error: {exc}\n")


if __name__ == "__main__":
    main()
