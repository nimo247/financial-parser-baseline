"""Arithmetic diagnostics for the baseline table; never changes source amounts.

Relations come from section/subtotal and gross/depreciation/net structure, not
sample row IDs, expected amounts, or reference annotations. Tolerances are an
explicit presentation assumption, not evidence of why a residual occurred.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys


def _validate_graph(rows):
    index = {row["id"]: row for row in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate row IDs")
    children = {row["id"]: [] for row in rows}
    seen = set()
    for row in rows:
        parent_id = row["parent_id"]
        if parent_id is None:
            if row["depth"] != 0 or row["path"] != [row["label"]]:
                raise ValueError(f"Invalid root hierarchy at {row['id']}")
        else:
            if parent_id not in seen:
                raise ValueError(f"Missing, cyclic, or out-of-order parent at {row['id']}")
            parent = index[parent_id]
            if row["depth"] != parent["depth"] + 1 or row["path"] != parent["path"] + [row["label"]]:
                raise ValueError(f"Inconsistent parent/path/depth at {row['id']}")
            children[parent_id].append(row)
        seen.add(row["id"])
    return index, children


def _section_total(section, children):
    label = section["label"]
    total_label = (label[:-2] if label.endswith("の部") else label) + "合計"
    candidates = [r for r in children[section["id"]]
                  if r["kind"] == "subtotal" and r["label"] == total_label]
    if len(candidates) != 1:
        raise ValueError(f"Expected one explicit subtotal {total_label!r}")
    if children[candidates[0]["id"]]:
        raise ValueError("Subtotal unexpectedly has child rows")
    return candidates[0]


def _relations(rows, children):
    relations, issues = [], []
    for section in [r for r in rows if r["kind"] == "section"]:
        try:
            target = _section_total(section, children)
            operands = []
            for child in children[section["id"]]:
                if child["id"] == target["id"]:
                    continue
                if child["kind"] == "section":
                    operands.append(_section_total(child, children))
                elif child["kind"] == "item":
                    descendants = children[child["id"]]
                    if descendants:
                        nets = [r for r in descendants if r["kind"] == "net"]
                        adjustments = [r for r in descendants if r["kind"] != "net"]
                        if len(nets) != 1 or not adjustments or any(
                            r["kind"] != "item" or r["label"] != "減価償却累計額" for r in adjustments
                        ):
                            raise ValueError(f"Unsupported gross/net grouping at {child['label']!r}")
                        operands.append(nets[0])
                    else:
                        operands.append(child)
                else:
                    raise ValueError(f"Unexpected direct child {child['label']!r}")
            if not operands:
                raise ValueError("Subtotal has no identifiable components")
            relations.append(dict(relation="section_sum", target=target, operands=operands))
        except ValueError as exc:
            issues.append(dict(row_id=section["id"], path=section["path"], reason=str(exc)))
    index = {r["id"]: r for r in rows}
    for net in [r for r in rows if r["kind"] == "net"]:
        try:
            gross = index.get(net["parent_id"])
            if not gross or gross["kind"] != "item":
                raise ValueError("Net row has no gross item parent")
            siblings = children[gross["id"]]
            adjustments = [r for r in siblings if r["id"] != net["id"]]
            if len([r for r in siblings if r["kind"] == "net"]) != 1 or not adjustments or any(
                r["kind"] != "item" or r["label"] != "減価償却累計額" for r in adjustments
            ):
                raise ValueError("Expected one net row and signed accumulated-depreciation rows")
            if any(children[r["id"]] for r in siblings):
                raise ValueError("Nested adjustments/net rows are unsupported")
            relations.append(dict(relation="gross_plus_signed_depreciation", target=net,
                                  operands=[gross] + adjustments))
        except ValueError as exc:
            issues.append(dict(row_id=net["id"], path=net["path"], reason=str(exc)))
    return relations, issues


def _observation(row, column_id, dash_policy):
    cell = row["cells"][column_id]
    status, value = cell["status"], cell["value"]
    if status not in {"number", "blank", "dash"}:
        raise ValueError(f"Unknown cell status at {row['id']}/{column_id}")
    if status == "number" and (type(value) is not int):
        raise ValueError(f"Numeric cell is not an integer at {row['id']}/{column_id}")
    if status != "number" and value is not None:
        raise ValueError(f"Non-numeric cell has a value at {row['id']}/{column_id}")
    assumed_zero = status == "dash" and dash_policy == "assume-zero"
    return dict(row_id=row["id"], path=row["path"], raw=cell["raw"], status=status,
                value=value, arithmetic_value=0 if assumed_zero else value,
                assumed_zero=assumed_zero)


def _check(relation, column, page_index, dash_policy):
    target = _observation(relation["target"], column["id"], "skip")
    terms = [_observation(row, column["id"], dash_policy) for row in relation["operands"]]
    check = dict(page_index=page_index, period=column["period"], column_id=column["id"],
                 relation=relation["relation"], target=target, operands=terms,
                 tolerance=len(terms), computed=None, reported=target["value"], residual=None,
                 status="not_evaluated", assumptions=[], reason=None)
    if any(t["assumed_zero"] for t in terms):
        check["assumptions"].append("Explicit dash operands provisionally treated as zero by user-selected policy")
    if target["status"] != "number" or any(t["arithmetic_value"] is None for t in terms):
        check["reason"] = "An operand or reported result is blank/dash without a numeric interpretation"
        return check
    computed = sum(t["arithmetic_value"] for t in terms)
    residual = target["value"] - computed
    check.update(computed=computed, residual=residual,
                 status="exact" if residual == 0 else "within_tolerance" if abs(residual) <= len(terms)
                 else "beyond_tolerance")
    if residual:
        check["reason"] = "Nonzero residual; cause unverified; reported values preserved"
    if relation["relation"] == "gross_plus_signed_depreciation" and any(
        t["arithmetic_value"] > 0 for t in terms[1:]
    ):
        check["sign_issue"] = "Accumulated depreciation unexpectedly positive; inspect source/sign assignment"
    return check


def validate_document(document, dash_policy="skip"):
    if dash_policy not in {"skip", "assume-zero"}:
        raise ValueError("Unknown dash policy")
    if document.get("schema_version") != "1.0.0":
        raise ValueError("Unsupported extraction schema version")
    checks, structural_issues = [], []
    for page in document["pages"]:
        _, children = _validate_graph(page["rows"])
        relations, issues = _relations(page["rows"], children)
        structural_issues.extend(dict(page_index=page["page_index"], **issue) for issue in issues)
        for relation in relations:
            for column in page["metadata"]["columns"]:
                checks.append(_check(relation, column, page["page_index"], dash_policy))
    counts = Counter(c["status"] for c in checks)
    requires_review = bool(structural_issues or counts["beyond_tolerance"] or
                           any("sign_issue" in c for c in checks) or not checks)
    return dict(validation_version="1.0.0", source_sha256=document["source"]["sha256"],
        policy=dict(dash_policy=dash_policy, residual_definition="reported minus sum of signed operands",
            tolerance_rule="n displayed-unit integers for n operands; inclusive absolute bound",
            derivation="Assume each of n operands and the result differs from an exact quantity by less than one displayed unit. The residual magnitude is less than n+1; because it is integer-valued, it is at most n.",
            qualification="Conditional conservative presentation bound; the filing's rounding/truncation method and cause of residuals are unverified. It cannot detect all extraction errors.",
            nonzero_residuals="Always reported, even within tolerance; never corrected"),
        summary=dict(checks=len(checks), exact=counts["exact"], within_tolerance=counts["within_tolerance"],
            beyond_tolerance=counts["beyond_tolerance"], not_evaluated=counts["not_evaluated"],
            complete=bool(checks) and not counts["not_evaluated"] and not structural_issues,
            requires_review=requires_review), structural_issues=structural_issues, checks=checks)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("outputs/table.json"))
    parser.add_argument("--output", type=Path, default=Path("outputs/validation.json"))
    parser.add_argument("--dash-policy", choices=["skip", "assume-zero"], default="skip")
    args = parser.parse_args()
    try:
        document = json.loads(args.input.read_text(encoding="utf-8"))
        report = validate_document(document, args.dash_policy)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report["summary"]))
    return 1 if report["summary"]["requires_review"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
