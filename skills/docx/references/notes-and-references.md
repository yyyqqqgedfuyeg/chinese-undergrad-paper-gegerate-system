# Native footnotes and cross-references

Use when adding styled footnotes or body references to tables, notes, and bibliography entries in an existing DOCX. Preserve the existing template, including custom styles, headers, media and sections. `notes_references.py` makes targeted package edits; it does not clean or replace the source style library.

## Supported operation

```bash
.venv/bin/python skills/docx/scripts/notes_references.py apply SOURCE.docx PLAN.json OUTPUT.docx --report REPORT.json
.venv/bin/python skills/docx/scripts/notes_references.py inspect OUTPUT.docx
```

The plan requires the exact source SHA256, `footnote_style`, and ordered `blocks`. Blocks insert before the final section properties, or before one exact, unique body paragraph selected with `insert_before`. Existing text is retained. For capability experiments add a clearly labelled test section; do not present demonstration citations as real sources.

Example plan (replace the hash and adapt style IDs from the actual source):

```json
{
  "source_sha256": "SHA256_OF_SOURCE",
  "footnote_style": {"east_asia_font": "宋体", "latin_font": "Times New Roman", "size_pt": 9, "marker_size_pt": 9, "line": 240},
  "blocks": [
    {"type": "paragraph", "style": "PaperBody", "inlines": ["这句话需要解释", {"footnote": {"bookmark": "Note_Method", "text": "测试脚注：解释该方法的使用条件。"}}, "。"]},
    {"type": "paragraph", "style": "PaperBody", "inlines": ["结果见", {"ref": "Table_Result"}, "，依据见文献", {"ref": "Bib_Method", "superscript": true}, "；再次引用脚注", {"ref": "Note_Method", "superscript": true}, "。"]},
    {"type": "caption", "style": "PaperTableCaption", "bookmark": "Table_Result", "sequence": "TestTable", "prefix": "表", "text": "测试结果"},
    {"type": "table", "style": "PaperTable1", "text_style": "PaperBody", "column_widths": [2400, 2400], "rows": [["指标", "数值"], ["正确率", "99%"]]},
    {"type": "caption", "style": "PaperReference", "bookmark": "Bib_Method", "sequence": "TestReference", "prefix": "[", "suffix": "]", "text": "演示作者. 演示条目（仅能力测试，不是真实文献）."}
  ]
}
```

Style IDs in an actual source may differ. Inspect `word/styles.xml` or its style catalogue. Do not assume the example IDs exist. Use a new SEQ identifier for this insertion; the helper rejects identifiers already present because it does not evaluate pre-existing sequence switches. Bibliography entries are numbered bookmark targets, not Word citation-manager records; they do not fetch sources or guarantee a citation standard.

Footnotes are native `word/footnotes.xml` entries with unique positive IDs, separator entries, a content-type declaration, and a document relationship. The original body contains `footnoteReference`; each note contains `footnoteRef`. Repeated references to the same note use `NOTEREF`, not duplicate native footnote markers. `NOTEREF` targets a bookmark enclosing the body marker, not the note text. `REF` targets the table label/number or bibliography number; its cached value already includes the caption prefix (e.g. 表 or [), so do not duplicate that prefix in preceding prose; `\\h` adds navigation, and optional superscript controls citation display.

The helper adds visible custom styles “论文脚注正文” (`PaperFootnoteText`) and “论文脚注标记” (`PaperFootnoteReference`), applies them to notes and markers, and leaves the existing styles intact. Notes inherit font and size from the styles so they remain editable. The example 9 pt and single spacing are test choices, not a school requirement. Existing footnote style IDs cause a stop rather than silent overwrite. Initial note caches support decimal, continuous numbering starting at 1; other numbering modes require an office engine and a matching workflow.

## Validation and update semantics

1. Inspect the package: paired unique bookmark IDs/names, valid reference targets, note IDs/markers, actual style applications, content type and relationship. Missing targets must fail.
2. Run the skill's Office XSD validator on the generated DOCX. Preserve unrelated original package parts and source body elements.
3. Render with installed fonts and inspect the footnote page: note text belongs at the foot of the page, marks are superscript, and tables/citations are legible.
4. To test dynamic references, insert an earlier table caption, bibliography entry and footnote. Update fields with Word or LibreOffice UNO, save a separate DOCX/PDF, and confirm each original target and repeated reference changes consistently (e.g. 1 → 2). Inspect saved reference fields/bookmarks and PDF internal links. Recheck styles after conversion, as office engines may rewrite them.

Cached field text is only the initial display. A refresh-on-open flag or a successful PDF conversion is insufficient evidence that all references updated. Do not claim Microsoft Word UI behavior was tested if only LibreOffice was available. Keep generated source DOCX and the office-roundtrip DOCX separate and record limits, including font substitution and any rewritten fields.

Official field/reference behavior: [Microsoft: Create a cross-reference](https://support.microsoft.com/en-au/word/create-a-cross-reference), [Microsoft: Update fields](https://support.microsoft.com/en-au/word/update-fields).

## Linux compatibility observed in real testing

The installed LibreOffice imports `REF`/`SEQ`, but retains our `NOTEREF` as an unevaluated field; changing simple fields to complex fields did not fix it. Its DOCX export also collapses bookmarks surrounding footnote markers and rewrites style IDs. Do not deliver that roundtrip DOCX as a lossless replacement for the authored file.

For this helper's supported number fields, refresh caches directly before rendering:

```bash
.venv/bin/python skills/docx/scripts/notes_references.py refresh INPUT.docx REFRESHED.docx --report CACHE_REPORT.json
```

This computes decimal sequence numbers in document order, note display numbers from native body markers (not their internal IDs), bookmark contents, and forward/repeated references. It preserves the native Word fields, original style definitions and all other package parts. `NOTEREF` also carries an explicit internal hyperlink in the authored document. The installed LibreOffice still drops navigation around the unevaluated field; use the PDF adapter below rather than claim that the outer hyperlink alone fixes it.

The cache updater supports simple `SEQ identifier \* ARABIC`, `REF bookmark \h` and `NOTEREF bookmark \h \f` with decimal continuous footnotes starting at 1. Unsupported switches fail, rather than guess. Complex source fields, TOC and page numbers are not evaluated. Record cache updates separately from office-engine updates. Verify numbering mutations on the refreshed authored DOCX and its rendered PDF. Native Word field updates require a separate Word validation environment.

For Linux PDF export, create a disposable render input **after refreshing caches**:

```bash
.venv/bin/python skills/docx/scripts/notes_references.py pdf-input REFRESHED.docx PDF_INPUT.docx --report PDF_ADAPTER.json
```

The adapter replaces only the render copy's unevaluated NOTEREF fields with internal hyperlinks carrying their current numbers, and anchors those destinations on adjacent body text. LibreOffice still does not export these note links reliably by itself. The UNO render helper uses the adapter report to replace those render-only links with native LibreOffice footnote cross-reference objects, then refreshes fields and exports PDF:

```bash
/usr/bin/python3 skills/docx/scripts/office/render_references.py PDF_INPUT.docx RENDER_DIR --note-map PDF_ADAPTER.json
```

System Python must have the `uno` module and LibreOffice installed. This helper starts an isolated office profile, disables macros, exports named destinations using typed UNO filter data, and records field results and note-reference bridges. Discard its office-roundtrip DOCX. Deliver REFRESHED.docx as the editable document: it retains native Word fields and named styles. Validate the render input with XSD and check PDF note-reference links independently. This is an export translation, not evidence that LibreOffice evaluated NOTEREF. Tables/bibliography retain REF/SEQ for office evaluation.
