"""Page-level routing for the declared Japanese balance-sheet baseline.

This router recommends actions. It does not execute OCR, a VLM, or human review.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

import pdfplumber

from parse import ExtractionError, extract_page
from validate import validate_document

# Explicit vocabulary for this narrow assets-only baseline. Unknown readable
# sections need structural interpretation; they are not evidence of failed OCR.
SUPPORTED_SECTIONS = {"資産の部", "流動資産", "固定資産", "有形固定資産", "無形固定資産", "投資その他の資産"}


def preflight(page):
    if not page.chars:
        if page.images:
            return "ocr_required", "Image content exists but there is no extractable text layer"
        return "structure_review", "No extractable text or image evidence; inspect blank/vector-only page"
    text = "".join(c.get("text", "") for c in page.chars)
    if any(ch in text for ch in ["\ufffd", "\x00"]) or re.search(r"\(cid:\d+\)", text) or any(
        "\ue000" <= ch <= "\uf8ff" for ch in text
    ):
        return "extraction_review", "Suspicious decoded glyphs; try alternate text extraction, then OCR if needed"
    if not re.search(r"[\u3400-\u9fff]", text):
        return "extraction_review", "No decoded CJK for expected Japanese input; inspect encoding or document type"
    return None


def route_page(page, page_index, source_sha256):
    result = dict(page_index=page_index, decision=None, reasons=[], row_count=None,
                  validation_summary=None, structural_issues=[], extraction_error_code=None)
    signal = preflight(page)
    if signal:
        result.update(decision=signal[0], reasons=[signal[1]])
        return result
    try:
        extracted = extract_page(page, page_index)
    except ExtractionError as exc:
        result.update(decision=exc.code, reasons=[str(exc)], extraction_error_code=exc.code)
        return result
    result["row_count"] = len(extracted["rows"])
    unknown = [r["label_raw"] for r in extracted["rows"]
               if r["kind"] == "section" and r["label"] not in SUPPORTED_SECTIONS]
    if unknown:
        result.update(decision="structure_review", reasons=["Readable but unsupported section labels: " + ", ".join(unknown)])
        return result
    periods = [c["period"] for c in extracted["metadata"]["columns"]]
    if len(set(periods)) != 2 or periods != sorted(periods):
        result.update(decision="structure_review", reasons=["Expected distinct previous/current periods in ascending column order"])
        return result
    document = dict(schema_version="1.0.0", source=dict(sha256=source_sha256), pages=[extracted])
    try:
        validation = validate_document(document)
    except (ValueError, KeyError, TypeError) as exc:
        result.update(decision="structure_review", reasons=[f"Invalid extracted relationships: {exc}"])
        return result
    summary = validation["summary"]
    result.update(validation_summary=summary, structural_issues=validation["structural_issues"])
    if validation["structural_issues"]:
        result.update(decision="structure_review", reasons=["Could not interpret all section/net relationships"])
    elif summary["requires_review"]:
        result.update(decision="human_review", reasons=[
            "Arithmetic residual exceeds the assumed tolerance or a depreciation sign is unexpected",
            "Compare an alternate extractor/source page before deciding whether the issue is extraction or source data"])
    else:
        result.update(decision="accept_with_diagnostics", reasons=[
            "Supported text/table structure; no arithmetic review trigger detected",
            "Acceptance does not prove correctness; inspect nonzero residuals and incomplete check coverage"])
    return result


def route_document(path):
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    pages = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, 1):
            pages.append(route_page(page, index, digest))
    if not pages:
        raise ValueError("PDF contains no pages")
    counts = dict(Counter(p["decision"] for p in pages))
    return dict(router_version="1.0.0", source=dict(filename=path.name, sha256=digest),
                scope="Heuristic routing for the declared assets-only baseline; no OCR/VLM executed",
                summary=dict(pages=len(pages), decisions=counts,
                             action_required=any(p["decision"] != "accept_with_diagnostics" for p in pages)),
                pages=pages)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("outputs/routing.json"))
    args = parser.parse_args()
    try:
        report = route_document(args.input)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, OSError) as exc:
        print(f"Routing failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"]))
    return 1 if report["summary"]["action_required"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
