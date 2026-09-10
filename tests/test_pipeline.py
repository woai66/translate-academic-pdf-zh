from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import pymupdf
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import layout_preserving_bilingual_pdf as pipeline
import qa_bilingual_pdfs as structural
import qa_translation_content as content
import qa_rendered_pages as pixels
from workflow_support import GoogleWebTranslator, load_manifest, reference_contexts, write_json


def fixture(directory: Path) -> dict:
    source = directory / "source.pdf"
    translations = {
        "A Practical Study of Translation": "翻译方法的实用研究",
        "1. Introduction": "1. 引言",
        "We evaluate the method with 12 samples and compare the results with earlier studies [1,2].":
            "我们使用12个样本评估该方法，并将结果与已有研究[1,2]进行比较。",
        "Figure 1. A synthetic illustration for testing layout preservation.": "图1. 用于测试版式保留的自制示意图。",
        "Conclusions": "结论",
        "The method preserves the original layout and supports careful human review of every translated page.":
            "该方法保留原始版式，并支持逐页人工核查译文。",
        "References": "参考文献",
        "Appendix A. Further Details": "附录A. 更多细节",
        "Additional experiments confirm that the measured value remains 42 under the same conditions [1].":
            "补充实验表明，在相同条件下，测量值仍为42[1]。",
        "Supplementary experiments use the same procedure and retain all numerical values for comparison.":
            "补充实验使用相同流程，并保留所有数值以供比较。",
    }
    with pymupdf.open() as doc:
        p = doc.new_page(width=600, height=800)
        p.insert_text((130, 85), "A Practical Study", fontsize=20, fontname="hebo")
        p.insert_text((150, 115), "of Translation", fontsize=20, fontname="hebo")
        p.insert_text((50, 160), "1. Introduction", fontsize=12, fontname="hebo")
        p.insert_textbox((50, 180, 290, 260), list(translations)[2], fontsize=10)
        p.insert_text((180, 290), "E = m c^2", fontsize=10)
        image = Image.new("RGB", (120, 70), (36, 105, 138))
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        p.insert_image((80, 340, 260, 445), stream=stream.getvalue())
        p.insert_textbox((50, 470, 290, 520), list(translations)[3], fontsize=9)
        p = doc.new_page(width=600, height=800)
        p.insert_text((50, 100), "Conclusions", fontsize=12, fontname="hebo")
        p.insert_textbox((50, 125, 285, 195), list(translations)[5], fontsize=10)
        p.insert_text((50, 245), "References", fontsize=12, fontname="hebo")
        p.insert_textbox((50, 270, 285, 335), "[1] A. Author. A fictional test reference. Example Journal, 2026.", fontsize=9)
        p.insert_textbox((320, 90, 555, 155), "[2] B. Author. A second fictional reference. Example Journal, 2025.", fontsize=9)
        p.insert_text((320, 225), "Appendix A. Further Details", fontsize=12, fontname="hebo")
        p.insert_textbox((320, 250, 555, 330), list(translations)[8], fontsize=10)
        p = doc.new_page(width=600, height=800)
        p.insert_textbox((50, 140, 290, 220), list(translations)[9], fontsize=10)
        p.draw_rect((50, 290, 285, 375), color=(0.2, 0.4, 0.6))
        p.insert_text((65, 325), "Protected diagram label with several words", fontsize=9)
        p.insert_text((65, 355), "1.25 2.50 3.75 5.00 6.25 7.50", fontsize=9)
        p.set_rotation(90)
        doc.set_toc([[1, "Introduction", 1], [1, "References and appendix", 2]])
        doc.save(source)
    config = {"id": "synthetic", "source": str(source), "output": str(directory / "bilingual.pdf"),
              "title_en": "A Practical Study of Translation", "title_zh": "翻译方法的实用研究",
              "translations": str(directory / "translations.json"),
              "preserve_regions": [{"page": 3, "bbox": [45, 285, 290, 380]}]}
    write_json(Path(config["translations"]), translations)
    write_json(directory / "manifest.json", {"papers": [config]})
    return config


def build_fixture(directory: Path):
    config = fixture(directory)
    result = pipeline.build(Path(config["source"]), Path(config["output"]), directory / "cache",
                            config["id"], config["title_en"], config["title_zh"],
                            translations=json.loads(Path(config["translations"]).read_text(encoding="utf-8")),
                            preserve_regions=config["preserve_regions"])
    return config, result


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_offline_end_to_end(self):
        config, result = build_fixture(self.root)
        self.assertTrue(result["written"], result)
        self.assertEqual(result["output_pages"], 6)
        self.assertFalse(result["errors"])
        for qa in (structural.qa_paper, content.qa_paper):
            report = qa(config)
            self.assertEqual(report["errors"], [], report)
            self.assertEqual(report["warnings"], [], report)
        with pymupdf.open(config["output"]) as doc:
            self.assertEqual(doc[5].rotation, 90)
            self.assertIn("42", doc[3].get_text())
            self.assertIn("补充实验", doc[5].get_text())
            self.assertIn("fictional", doc[3].get_text())
            self.assertIn("E = m c^2", doc[1].get_text())
            self.assertEqual(doc.get_toc()[1][2], 3)

    def test_cache_does_not_mix_citations(self):
        class Translator:
            calls = 0
            def translate(inner, text):
                inner.calls += 1
                return "已核查的中文译文 " + " ".join(re.findall(r"XQZ\d+ZQX", text))
        translator = Translator()
        first = pipeline.translate_text("The method follows previous research [1].", translator, self.root)
        second = pipeline.translate_text("The method follows previous research [2].", translator, self.root)
        self.assertIn("[1]", first)
        self.assertIn("[2]", second)
        self.assertEqual(translator.calls, 2)
        self.assertEqual(pipeline.translate_text("The method follows previous research [1].", None, self.root), first)

    def test_missing_or_duplicated_placeholder_fails(self):
        for answer in ("中文译文", "中文 XQZ0ZQX XQZ0ZQX"):
            translator = type("Translator", (), {"translate": lambda _, text: answer})()
            with self.assertRaises(ValueError):
                pipeline.translate_text("Previous research confirms this result [7].", translator, self.root)
        self.assertEqual(list(self.root.glob("*.txt")), [])

    def test_offline_missing_entry_fails(self):
        with self.assertRaisesRegex(ValueError, "missing offline"):
            pipeline.translate_text("A previously unseen complete English sentence.", None, self.root)

    def test_changed_citation_in_reviewed_text_fails(self):
        with self.assertRaisesRegex(ValueError, "citations"):
            pipeline.validate_translation("A result is given in [1-3].", "结果见[1-4]。")

    def test_empty_reviewed_translation_fails(self):
        with self.assertRaises(ValueError):
            pipeline.translate_text("English source text.", None, self.root, {"English source text.": " "})

    def test_author_citation_is_preserved(self):
        translator = type("Translator", (), {"translate": lambda _, text: "方法参考 " + text.split()[0]})()
        result = pipeline.translate_text("Varma et al. [35] describe this method.", translator, self.root)
        self.assertIn("Varma 等人 [35]", result)

    def test_title_does_not_gain_arbitrary_line_breaks(self):
        title = "一种可靠的学术论文翻译方法"
        self.assertEqual(pipeline.split_title_lines(title, 2), title)

    def test_long_text_is_chunked(self):
        class Translator:
            calls = []
            def translate(inner, text):
                inner.calls.append(len(text))
                return "用于长段落测试的中文译文。"
        translator = Translator()
        pipeline.translate_text("A long sentence about a method. " * 220, translator, self.root)
        self.assertGreater(len(translator.calls), 1)
        self.assertLessEqual(max(translator.calls), 4000)

    def test_backend_failure_is_not_retried(self):
        translator = type("Translator", (), {"translate": lambda _, text: (_ for _ in ()).throw(RuntimeError("busy"))})()
        with patch.object(translator, "translate", wraps=translator.translate) as mocked:
            with self.assertRaises(RuntimeError):
                pipeline.translate_text("A complete English sentence.", translator, self.root)
            self.assertEqual(mocked.call_count, 1)

    def test_google_parser_and_request_timeout(self):
        from unittest.mock import MagicMock
        response = MagicMock(status_code=200, text='<div class="result-container">中文测试结果</div>')
        response.__enter__.return_value = response
        with patch("requests.get", return_value=response) as request:
            self.assertEqual(GoogleWebTranslator().translate("Synthetic text"), "中文测试结果")
            self.assertEqual(request.call_args.kwargs["timeout"], (10, 30))
            self.assertEqual(request.call_count, 1)

    def test_google_rate_limit_stops(self):
        from unittest.mock import MagicMock
        response = MagicMock(status_code=429)
        response.__enter__.return_value = response
        with patch("requests.get", return_value=response) as request:
            with self.assertRaisesRegex(RuntimeError, "429"):
                GoogleWebTranslator().translate("Synthetic text")
            self.assertEqual(request.call_count, 1)

    def test_connection_errors_do_not_expose_prose(self):
        import requests
        with patch("requests.get", side_effect=requests.ConnectionError("private source text")):
            with self.assertRaises(RuntimeError) as error:
                GoogleWebTranslator().translate("private source text")
            self.assertNotIn("private source text", str(error.exception))

    def test_reference_and_appendix_on_same_page(self):
        config = fixture(self.root)
        with pymupdf.open(config["source"]) as doc:
            modes = [mode for mode, _ in reference_contexts(doc)]
        self.assertEqual(modes, ["none", "between", "none"])

    def test_appendix_resumption_keeps_earlier_references(self):
        with pymupdf.open() as doc:
            p = doc.new_page(width=600, height=800)
            p.insert_text((50, 150), "References", fontsize=12)
            p = doc.new_page(width=600, height=800)
            p.insert_text((320, 250), "Appendix B", fontsize=12)
            mode, boundary = reference_contexts(doc)[1]
            self.assertEqual(mode, "resume")
            for bbox, expected in [((50, 400, 260, 430), False), ((320, 100, 550, 140), False),
                                   ((320, 300, 550, 350), True)]:
                block = pipeline.TextBlock(pymupdf.Rect(bbox), "This paragraph contains enough words to translate.",
                                           10, False, False, 0, 0)
                self.assertEqual(pipeline.should_translate(block, 2, 600, 800, "generic", mode, boundary, False), expected)

    def test_source_cannot_be_overwritten(self):
        config = fixture(self.root)
        source = Path(config["source"])
        before = hashlib.sha256(source.read_bytes()).digest()
        with self.assertRaisesRegex(ValueError, "different files"):
            pipeline.build(source, source, self.root / "cache")
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), before)

    def test_manifest_relative_paths_and_unknown_ids(self):
        fixture(self.root)
        manifest = self.root / "relative.json"
        write_json(manifest, {"papers": [{"id": "a", "source": "source.pdf", "output": "output.pdf"}]})
        configs = load_manifest(manifest, output_tag="_reviewed")
        self.assertEqual(configs[0]["output"], str(self.root / "output_reviewed.pdf"))
        with self.assertRaisesRegex(ValueError, "unknown"):
            load_manifest(manifest, ["missing"])

    def test_empty_manifest_and_unsafe_ids_fail(self):
        fixture(self.root)
        path = self.root / "invalid.json"
        for papers in ([], [{"id": "../escape", "source": "source.pdf", "output": "out.pdf"}]):
            write_json(path, {"papers": papers})
            with self.assertRaises(ValueError):
                load_manifest(path)

    def test_duplicate_output_fails(self):
        fixture(self.root)
        path = self.root / "duplicate.json"
        write_json(path, {"papers": [{"id": key, "source": "source.pdf", "output": "out.pdf"} for key in ("a", "b")]})
        with self.assertRaisesRegex(ValueError, "unique"):
            load_manifest(path)

    def test_scanned_input_fails_without_output(self):
        with pymupdf.open() as doc:
            doc.new_page()
            doc.save(self.root / "scan.pdf")
        with self.assertRaisesRegex(ValueError, "no text layer"):
            pipeline.build(self.root / "scan.pdf", self.root / "out.pdf", self.root / "cache")
        self.assertFalse((self.root / "out.pdf").exists())

    def test_overflow_does_not_replace_existing_output(self):
        config = fixture(self.root)
        output = Path(config["output"])
        output.write_bytes(b"existing output")
        with patch.object(pipeline, "translate_page", return_value=(1, ["overflow"])):
            result = pipeline.build(Path(config["source"]), output, self.root / "cache")
        self.assertFalse(result["written"])
        self.assertTrue(result["errors"])
        self.assertEqual(output.read_bytes(), b"existing output")

    def test_actual_text_overflow_fails(self):
        config = fixture(self.root)
        translations = json.loads(Path(config["translations"]).read_text(encoding="utf-8"))
        key = next(k for k in translations if k.startswith("We evaluate"))
        translations[key] = "过长的译文。" * 1000 + "12 [1,2]"
        result = pipeline.build(Path(config["source"]), Path(config["output"]), self.root / "cache",
                                title_en=config["title_en"], title_zh=config["title_zh"],
                                translations=translations, preserve_regions=config["preserve_regions"])
        self.assertTrue(result["errors"])
        self.assertFalse(Path(config["output"]).exists())

    def test_qa_rejects_truncated_and_changed_english_pages(self):
        config, result = build_fixture(self.root)
        self.assertTrue(result["written"], result)
        with pymupdf.open(config["output"]) as doc:
            doc[0].insert_text((50, 750), "Altered original", fontsize=10)
            doc.delete_page(-1)
            changed = self.root / "changed.pdf"
            doc.save(changed)
        config["output"] = str(changed)
        self.assertTrue(any("English original" in e for e in structural.qa_paper(config)["errors"]))
        self.assertTrue(any("page count" in e for e in content.qa_paper(config)["errors"]))

    def test_pixel_qa_detects_missing_numbers_and_blank_pages(self):
        Image.new("RGB", (100, 100), "white").save(self.root / "page-1.png")
        Image.new("RGB", (100, 100), "black").save(self.root / "page-3.png")
        result = pixels.inspect_paper("test", self.root, 2)
        self.assertTrue(any("page numbers" in e for e in result["errors"]))
        self.assertTrue(any("blank" in e for e in result["errors"]))

    def test_pixel_qa_rejects_stale_pdf_fingerprint(self):
        config, _ = build_fixture(self.root)
        directory = self.root / "render" / config["id"]
        directory.mkdir(parents=True)
        for number in range(1, 7):
            Image.new("RGB", (100, 100), "black").save(directory / f"page-{number}.png")
        write_json(directory / "render.json", {"sha256": "old-pdf", "dpi": 120})
        result = subprocess.run([sys.executable, str(ROOT / "scripts/qa_rendered_pages.py"),
                                 "--manifest", str(self.root / "manifest.json"),
                                 "--render-root", str(self.root / "render"),
                                 "--report", str(self.root / "pixel.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        report = json.loads((self.root / "pixel.json").read_text(encoding="utf-8"))
        self.assertIn("stale", " ".join(report["results"][0]["errors"]))

    def test_cli_output_tag_is_shared_by_generation_and_qa(self):
        fixture(self.root)
        base = ["--manifest", str(self.root / "manifest.json"), "--output-tag", "_tagged"]
        for script in ("layout_preserving_bilingual_pdf.py", "qa_bilingual_pdfs.py", "qa_translation_content.py"):
            command = [sys.executable, str(ROOT / "scripts" / script), *base,
                       "--report", str(self.root / (script + ".json"))]
            if script.startswith("layout"):
                command.extend(["--cache-dir", str(self.root / "cache")])
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
