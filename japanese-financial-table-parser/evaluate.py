"""Reference comparison only. Arithmetic diagnostics run separately in validate.py."""
import argparse
from collections import Counter
import json
from pathlib import Path


def evaluate(document, reference):
    if document["source"]["sha256"] != reference["source_sha256"]:
        raise ValueError("Reference belongs to a different source PDF")
    if len(document["pages"]) != 1:
        raise ValueError("This reference covers exactly one page")
    page = document["pages"][0]
    actual = page["rows"]
    expected = reference["rows"]
    if len({r["id"] for r in actual}) != len(actual):
        raise ValueError("Duplicate actual row IDs")
    actual_by_id = {r["id"]: r for r in actual}
    expected_by_id = {r["id"]: r for r in expected}
    row_ids = sorted(set(actual_by_id) | set(expected_by_id))
    counts, errors = Counter(), []
    periods = [c["period"] for c in page["metadata"]["columns"]]
    periods_ok = periods == reference["metadata"]["periods"]
    for key, value in reference["metadata"].items():
        found = page["page_index"] if key == "page_index" else periods if key == "periods" else page["metadata"].get(key)
        if found != value:
            errors.append(dict(scope="metadata", field=key, expected=value, actual=found))
    for row_id in row_ids:
        a, e = actual_by_id.get(row_id), expected_by_id.get(row_id)
        for field in ["label_raw", "label", "path", "parent_id", "depth", "kind"]:
            counts[field + "_total"] += 1
            if a and e and a.get(field) == e.get(field):
                counts[field + "_correct"] += 1
            else:
                errors.append(dict(scope="row", row_id=row_id, field=field,
                                   expected=e.get(field) if e else None, actual=a.get(field) if a else None))
        for col in sorted(set(a["cells"] if a else {}) | set(e["cells"] if e else {})):
            ac = a["cells"].get(col) if a else None
            ec = e["cells"].get(col) if e else None
            group = ec["status"] if ec else "unexpected"
            counts["cells_total"] += 1
            counts[group + "_total"] += 1
            matched = bool(a and e and ac and ec and periods_ok and a["path"] == e["path"]
                           and all(ac[k] == ec[k] for k in ["value", "status", "negative_zero"]))
            if matched:
                counts["cells_correct"] += 1
                counts[group + "_correct"] += 1
            else:
                errors.append(dict(scope="cell", row_id=row_id, column=col, expected=ec, actual=ac))
            if ac and ec and ac["raw"] == ec["raw"]:
                counts["raw_correct"] += 1
            if ec and (ec["raw"].startswith("△")):
                counts["negative_marker_total"] += 1
                if ac and ac["raw"].startswith("△") and all(ac[k] == ec[k] for k in ["value", "status", "negative_zero"]):
                    counts["negative_marker_correct"] += 1
    def metric(correct, total):
        return dict(correct=counts[correct], total=counts[total],
                    accuracy=counts[correct] / counts[total] if counts[total] else None)
    metrics = {field: metric(field + "_correct", field + "_total")
               for field in ["label_raw", "label", "path", "parent_id", "depth", "kind"]}
    metrics.update({"cell_semantics": metric("cells_correct", "cells_total"),
                    "raw_cell_text": metric("raw_correct", "cells_total"),
                    "negative_marker": metric("negative_marker_correct", "negative_marker_total")})
    for status in ["number", "dash", "blank"]:
        metrics[status] = metric(status + "_correct", status + "_total")
    order_ok = [r["id"] for r in actual] == [r["id"] for r in expected]
    return dict(scope="Single supplied page; development-set comparison, not held-out generalization",
                alignment_policy="Sequential row-ID matching; insertions/deletions with renumbering can cause cascading mismatches. Sequence alignment is not implemented.",
                reference_provenance=reference["provenance"], expected_rows=len(expected), actual_rows=len(actual),
                row_order_matches=order_ok, periods_match=periods_ok, metrics=metrics, errors=errors,
                passed=not errors and order_ok)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actual", type=Path, default=Path("outputs/table.json"))
    parser.add_argument("--reference", type=Path, default=Path("reference/expected.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/evaluation.json"))
    args = parser.parse_args()
    report = evaluate(json.loads(args.actual.read_text(encoding="utf-8")),
                      json.loads(args.reference.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(dict(passed=report["passed"], rows=report["actual_rows"],
                          cells=report["metrics"]["cell_semantics"], errors=len(report["errors"]))))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
