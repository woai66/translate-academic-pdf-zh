---
name: translate-academic-pdf-zh
description: Translate English academic PDFs into interleaved English-Chinese review copies while preserving page layout, figures, and equations. Use for scholarly PDFs with a text layer, manuscript-specific layout repairs, and full-page bilingual QA; scanned pages require OCR first.
---

# Academic PDF translation

Create an interleaved bilingual PDF: each unchanged English source page followed by a Chinese replica.
This is a model-assisted translation and editorial workflow, not a claim of automatic publication quality.

Read [references/quality-standard.md](references/quality-standard.md) before processing a paper.
Resolve script paths relative to this skill directory, and run them using the project's Python environment.
Python 3.11+ and the packages in [requirements.txt](requirements.txt) are required. Final rendering uses Poppler.

## Inspect and prepare

1. Keep source PDFs unchanged. Inspect extracted text and page renders before selecting translation regions.
2. Prefer intermediates under `tmp/pdfs/` and final PDFs under `output/pdf/`; respect user-specified paths.
3. Use a manifest for both single-paper and batch workflows so every QA stage checks the same files.
   Manifest paths are relative to the manifest file; CLI paths are relative to the working directory.
4. Supply the exact extracted `title_en` and a reviewed `title_zh`. Preserve deliberate Chinese line breaks with `\n`.
5. Use `skip_first_pages` only for intentional cover sheets. Use `preserve_regions` for complex diagrams,
   pseudocode, tables, or formulas that the text-block classifier cannot safely distinguish from prose.
6. Check scan-only pages, multi-column order, references/appendix boundaries, and blocks mixing equations with prose.
   Unsupported pages require OCR or a narrow layout repair before delivery.

## Translate and generate

The default workflow uses local, reviewed translations. Do the actual English-to-Chinese translation as the model,
or use translations provided by the user. Preserve the source keys in the exported mapping.

```sh
python <skill-dir>/scripts/layout_preserving_bilingual_pdf.py --manifest manifest.json --id paper-a --export-text tmp/pdfs/paper-a-source.json
```

Read the exported source blocks in page context. Fill every applicable value with complete Chinese text and save a
separate reviewed JSON file at the manifest's `translations` path. An empty value is unfinished work.
Review terminology, citations, numerical values, and sentences split between blocks/columns/pages.
Do not fabricate text to join fragments; use the adjacent source context.

```sh
python <skill-dir>/scripts/layout_preserving_bilingual_pdf.py --manifest manifest.json --cache-dir tmp/pdfs/cache --report tmp/pdfs/generation.json
```

The optional `--allow-network` switch sends uncached prose to Google's experimental web backend.
Use it only when external translation of this material is within the user's authorized scope.
Explain that data flow if the user has not selected it; prefer the default model-authored mapping.
Network errors and rate limits stop the run without automatic retries. Do not silently switch to another service.

Require `written: true`, no generation errors, and empty `overflow` lists. An existing output file after a failed run
may be from an older build; do not deliver it as the new result.

## Validate and inspect

```sh
python <skill-dir>/scripts/qa_bilingual_pdfs.py --manifest manifest.json --report tmp/pdfs/structure.json
python <skill-dir>/scripts/qa_translation_content.py --manifest manifest.json --report tmp/pdfs/content.json
python <skill-dir>/scripts/render_pdf_pages.py --manifest manifest.json --render-root tmp/pdfs/render-v1
python <skill-dir>/scripts/qa_rendered_pages.py --manifest manifest.json --render-root tmp/pdfs/render-v1 --report tmp/pdfs/pixel.json
```

Use the same `--id` filters and `--output-tag` in every stage when supplied.
Pass `--pdftoppm /path/to/pdftoppm` if Poppler is not on PATH.
The render directory must be fresh; pixel QA checks its fingerprint against the current output PDF.

Require zero errors and warnings. Inspect every rendered page and compare it with the source.
Check titles, equations, figure labels, table values, rotated pages, citations, acknowledgments, and reference/appendix
transitions at full resolution. Automated checks share some region heuristics and can miss the same misclassification.

Fix reviewed translations or narrowly scoped regions, rebuild, and use a new render directory after changes.
If a warning is a proven false positive, document the evidence for that paper; do not weaken general checks to hide it.
Do not claim semantic or layout perfection from zero automated warnings alone.

## Deliver

Deliver the requested final PDFs and a concise count of papers/pages plus the QA and visual-review results.
State remaining issues honestly. Keep caches, renders, and internal reports out of the deliverables unless requested.
