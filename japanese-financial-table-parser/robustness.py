"""Generate synthetic PDF variants and exercise the real extraction/router path.

Expected routing outcomes include accepted corruptions to expose blind spots;
the scenario success rate is not extraction accuracy or error-detection recall.
PyMuPDF is a development-only fixture-generation dependency.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz

from parse import ExtractionError, parse_document
from route import route_document


def _save(doc, path):
    doc.save(path, garbage=4, deflate=True)
    doc.close()


def _replace(doc, old, new, *, shift=0, font="tiro", occurrence=0):
    page = doc[0]
    matches = page.search_for(old)
    if len(matches) <= occurrence:
        raise ValueError(f"Fixture edit could not locate {old!r}")
    rect = matches[occurrence]
    # No fill overlay: a new rectangle could itself change table detection.
    page.add_redact_annot(rect, fill=None, cross_out=False)
    page.apply_redactions(images=0, graphics=0)
    size = 9
    if font == "japan":
        x = rect.x0 + shift
    else:
        x = rect.x1 - fitz.get_text_length(new, fontname=font, fontsize=size) + shift
    page.insert_text((x, rect.y1 - 1.8), new, fontsize=size, fontname=font)


def _strip_drawings(source, destination):
    doc = fitz.open(source)
    for page in doc:
        page.add_redact_annot(page.rect, fill=None, cross_out=False)
        # Preserve text and images; remove intersecting vector graphics.
        page.apply_redactions(images=0, graphics=2, text=1)
    _save(doc, destination)


def generate_variants(source, directory):
    source, directory = Path(source), Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    variants = [dict(name="original", path=source, expected="accept_with_diagnostics",
                     content_should_match=True, category="control")]

    path = directory / "translated_page.pdf"
    with fitz.open(source) as original:
        bounds = original[0].rect
        doc = fitz.open()
        page = doc.new_page(width=bounds.width + 40, height=bounds.height + 20)
        page.show_pdf_page(fitz.Rect(20, 10, bounds.width + 20, bounds.height + 10), original, 0)
        _save(doc, path)
    variants.append(dict(name="translated_page", path=path, expected="accept_with_diagnostics",
                         content_should_match=True, category="geometry"))

    path = directory / "rasterized_scan.pdf"
    with fitz.open(source) as original:
        pixmap = original[0].get_pixmap(matrix=fitz.Matrix(150 / 72, 150 / 72), alpha=False)
        doc = fitz.open()
        page = doc.new_page(width=original[0].rect.width, height=original[0].rect.height)
        page.insert_image(page.rect, stream=pixmap.tobytes("png"))
        _save(doc, path)
    variants.append(dict(name="rasterized_scan", path=path, expected="ocr_required",
                         content_should_match=False, category="scan"))

    edits = [
        ("shifted_amount_alignment", "accept_with_diagnostics", True, "geometry",
         [("608,281", "608,281", {"shift": -18})]),
        ("digit_transposition", "human_review", False, "detectable_corruption",
         [("2,002,429", "2,002,492", {})]),
        ("unknown_section", "structure_review", False, "unsupported_structure",
         [("投資その他の資産", "未分類資産", {"font": "japan"})]),
        ("column_collision", "extraction_review", False, "unsupported_structure",
         [("608,281", "608,281", {"shift": -125.04})]),
        ("one_unit_error", "accept_with_diagnostics", False, "known_blind_spot",
         [("2,002,429", "2,002,430", {})]),
        ("compensating_errors", "accept_with_diagnostics", False, "known_blind_spot",
         [("2,002,429", "2,002,492", {}), ("2,019,476", "2,019,413", {})]),
    ]
    for name, expected, match, category, changes in edits:
        doc = fitz.open(source)
        for old, new, options in changes:
            _replace(doc, old, new, **options)
        path = directory / f"{name}.pdf"
        _save(doc, path)
        variants.append(dict(name=name, path=path, expected=expected,
                             content_should_match=match, category=category))

    doc = fitz.open(source)
    page = doc[0]
    matches = page.search_for("△1,640,253")
    if len(matches) != 1:
        raise ValueError("Could not locate unique depreciation sign for fixture")
    r = matches[0]
    # The original triangle occupies 9 points; keep the adjacent digit intact.
    page.add_redact_annot(fitz.Rect(r.x0 + .1, r.y0, r.x0 + 8.8, r.y1), fill=None, cross_out=False)
    page.apply_redactions(images=0, graphics=0)
    path = directory / "dropped_negative_sign.pdf"
    _save(doc, path)
    variants.append(dict(name="dropped_negative_sign", path=path, expected="human_review",
                         content_should_match=False, category="detectable_corruption"))
    for name, original_name, expected, match, category in [
        ("borderless", "original", "accept_with_diagnostics", True, "borderless_geometry"),
        ("borderless_shifted_amount", "shifted_amount_alignment", "accept_with_diagnostics", True, "borderless_geometry"),
        ("borderless_column_collision", "column_collision", "extraction_review", False, "unsupported_structure"),
    ]:
        origin = next(v["path"] for v in variants if v["name"] == original_name)
        path = directory / f"{name}.pdf"
        _strip_drawings(origin, path)
        variants.append(dict(name=name, path=path, expected=expected,
                             content_should_match=match, category=category))
    doc = fitz.open(source)
    page = doc[0]
    page.add_redact_annot(page.search_for("608,281")[0], fill=None, cross_out=False)
    page.apply_redactions(images=0, graphics=0)
    # Avoid creating a temporary fixture that could be mistaken for a scenario.
    for page in doc:
        page.add_redact_annot(page.rect, fill=None, cross_out=False)
        page.apply_redactions(images=0, graphics=2, text=1)
    path = directory / "borderless_missing_amount.pdf"
    _save(doc, path)
    variants.append(dict(name="borderless_missing_amount", path=path, expected="structure_review",
                         content_should_match=False, category="unsupported_structure"))
    return variants


def content_projection(document):
    """Ignore source hash/coordinates, compare extracted semantic content."""
    pages = []
    for page in document["pages"]:
        meta = page["metadata"]
        pages.append(dict(metadata={k: meta[k] for k in ["currency", "unit_raw", "unit_multiplier", "correction_marker_raw", "printed_page_number"]},
            periods=[c["period"] for c in meta["columns"]],
            rows=[{k: row[k] for k in ["label_raw", "path", "depth", "parent_id", "kind"]} |
                  {"cells": {col: {k: cell[k] for k in ["raw", "value", "status", "negative_zero"]}
                             for col, cell in row["cells"].items()}} for row in page["rows"]]))
    return pages


def run(source, output):
    source, output = Path(source), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    baseline = content_projection(parse_document(source))
    results = []
    for variant in generate_variants(source, output / "fixtures"):
        routed = route_document(variant["path"])
        decisions = [page["decision"] for page in routed["pages"]]
        content_matches = None
        if variant["content_should_match"]:
            try:
                content_matches = content_projection(parse_document(variant["path"])) == baseline
            except ExtractionError:
                content_matches = False
        matched = decisions == [variant["expected"]] and content_matches is not False
        routing_file = output / (variant["name"] + "_routing.json")
        routing_file.write_text(json.dumps(routed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        results.append(dict(scenario=variant["name"], category=variant["category"], fixture=str(variant["path"]),
                            fixture_availability="generated locally; not committed" if variant["name"].startswith("borderless") else "committed sample; regenerated on run",
                            expected_decision=variant["expected"], actual_decisions=decisions,
                            semantic_content_matches_original=content_matches,
                            expectation_met=matched, routing_report=str(routing_file)))
    report = dict(scope=f"{len(results)} synthetic scenarios from one source page; no OCR/VLM is executed",
                  fixture_policy="Existing sample PDFs remain committed. New borderless PDFs are generated locally by robustness.py and are not committed.",
                  warning="Expected accepted corruptions are included. Expectation agreement is not extraction accuracy or error-detection recall.",
                  summary=dict(scenarios=len(results), expectations_met=sum(r["expectation_met"] for r in results),
                               known_blind_spots=[r["scenario"] for r in results if r["category"] == "known_blind_spot"]),
                  scenarios=results)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/balance_sheet_after_correction.pdf"))
    parser.add_argument("--output", type=Path, default=Path("outputs/robustness"))
    args = parser.parse_args()
    report = run(args.input, args.output)
    print(json.dumps(report["summary"]))
    for result in report["scenarios"]:
        print(f"{result['scenario']}: {','.join(result['actual_decisions'])}; expectation_met={result['expectation_met']}")
    return 0 if all(r["expectation_met"] for r in report["scenarios"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
