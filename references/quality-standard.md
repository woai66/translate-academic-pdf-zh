# Layout-preserving translation standard

## Acceptance

- Pair each English page with its Chinese replica, in source order. The total page count is exactly doubled.
- Preserve source page dimensions, crop boxes, orientation, visible images, formulas, and table values.
- Translate prose inside its original region. Keep intentional paragraph spacing and source indentation.
- Supply a reviewed Chinese title. Preserve editorial line breaks; do not insert arbitrary breaks by character count.
- Keep non-horizontal text, embedded image labels, and designated preservation regions unchanged.
- Preserve all numeric citations, names, units, URLs, and scientific meaning. Read fragments in their full-page context.
- Keep author citations together, e.g. `Varma 等人 [35]`, without a spurious sentence stop after the author's name.
- Use natural Chinese punctuation. Avoid isolated citation lines and punctuation at the beginning of a Chinese line.
- Review paragraph justification, short caption alignment, and text size visually. Automatic text-block geometry is imperfect.

## References and back matter

Translate the heading References/Bibliography as 参考文献, while preserving reference entries in English.
Conclusions and acknowledgments before the reference boundary remain translatable even on a shared page.

Resume translation at an Appendix, Appendices, Supplementary Material, or Supplemental Material boundary.
Numbered appendices such as `Appendix A` and same-page reference-to-appendix transitions are supported.
Determine boundaries in column reading order, not only by their vertical positions.
A merged heading/reference block or an unusual three-column layout requires manual inspection and a scoped repair.

## Manifest

```json
{
  "papers": [
    {
      "id": "paper-a",
      "source": "input/paper.pdf",
      "output": "output/pdf/paper_bilingual.pdf",
      "title_en": "Exact English Title",
      "title_zh": "经过审校的中文题名",
      "translations": "tmp/pdfs/paper-a.translations.json",
      "skip_first_pages": 0,
      "preserve_regions": [
        {"page": 4, "bbox": [45, 210, 290, 440]}
      ]
    }
  ]
}
```

Paths are relative to this manifest, or absolute. IDs contain only letters, digits, underscores and hyphens, start with
a letter/digit, and are at most 100 characters. IDs and output paths must be unique. No output may overwrite a source.

Both titles must be supplied together. The English title must match up to four consecutive extracted blocks on the
first non-skipped page. Use reviewed `\n` breaks inside the Chinese title if its natural wrapping is unsuitable.

Preservation coordinates use unrotated PDF points and 1-based source page numbers.
The entire intersecting text block is preserved; verify that the region does not also suppress nearby prose.

Translations are a UTF-8 JSON object whose keys are exported normalized English text blocks and whose values are
Chinese translations. Blank values count as missing. Reviewed mappings take precedence over caches.
The public cache format includes the complete source and intentionally does not reuse the old private corpus cache.

## Required checks

1. Generation: no errors, no overflow, and `written: true`. Failure must not replace an existing final PDF.
2. Structural: correct pairing and geometry, unchanged English-page render/text, preserved image positions/content,
   preserved nontranslated text, and no empty translation regions.
3. Content: no missing Chinese, unresolved placeholders, long English residue, or changed numeric citations.
   Numerical-data warnings require source comparison; a zero count cannot prove semantic accuracy.
4. Pixel: exact numbered-page sequence, no unexpected blank pages, paired image sizes, at least 96 DPI,
   and a matching PDF fingerprint from `render_pdf_pages.py`.
5. Visual/editorial: inspect all pages, not only automated findings. Recheck all affected pages after corrections.

Zero automated errors/warnings is a delivery gate, not a universal guarantee.
The region classifier is shared by generation and some QA. Inspect the source independently for missed prose,
small text, complex math, overlapping blocks, table headers, footnotes, and mixed heading/body regions.

## Scope and failure handling

Scan-only pages require OCR outside this skill. Password-protected sources must be unlocked before processing.
Irregular columns, mixed equation/prose blocks, forms, cross-page interactive links, signatures, and PDF/A preservation
are not covered by the generic layout pipeline. Do not imply that they passed checks which do not test them.

The optional Google web backend is experimental and requires a reachable external service.
Local reviewed translations are the reproducible default. No uploaded documents or original-paper excerpts belong
in the public repository's test fixtures.
