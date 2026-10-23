"""Baseline for text-layer Japanese balance sheets with one 3-column table/page.

No reference data, expected amounts, row counts, or sample coordinates are read.
All source boxes are [x0, top, x1, bottom] in PDF points, origin top-left.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata
from statistics import median

import pdfplumber


class ExtractionError(ValueError):
    """Input outside the explicitly supported baseline."""

    def __init__(self, message, code="structure_review"):
        super().__init__(message)
        self.code = code


def normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def box(bounds):
    return [round(float(v), 4) for v in bounds] if bounds else None


def parse_cell(raw: str, source_bbox=None) -> dict:
    if "\n" in raw or "\r" in raw:
        raise ExtractionError(f"Multiple text lines in value cell {raw!r}")
    normalized = re.sub(r"\s+", "", normalize(raw))
    result = dict(raw=raw, normalized=normalized, value=None, status="blank",
                  negative_zero=False, source_bbox=box(source_bbox))
    if not normalized:
        return result
    if normalized in {"-", "−", "―", "—", "–", "ー"}:
        result["status"] = "dash"
        return result
    # Comma groups must be well formed. Reject decimals/footnotes instead of guessing.
    match = re.fullmatch(r"([△▲\-−]?)([0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", normalized)
    if not match:
        raise ExtractionError(f"Unrecognized value token {raw!r}", code="extraction_review")
    sign, digits = match.groups()
    value = int(digits.replace(",", ""))
    negative = bool(sign)
    result.update(status="number", value=-value if negative else value,
                  negative_zero=negative and value == 0)
    return result


def cluster_indents(positions, tolerance=2.0):
    anchors = []
    for x in sorted(positions):
        if not anchors or abs(x - anchors[-1]) > tolerance:
            anchors.append(x)
    return anchors


@dataclass
class CoordinateRegion:
    bbox: tuple
    cells: list | None = None


@dataclass
class CoordinateTable:
    bbox: tuple
    columns: list
    rows: list
    values: list

    def extract(self):
        return self.values


def _word_lines(words, tolerance=2.0):
    lines = []
    for word in sorted(words, key=lambda w: ((w["top"] + w["bottom"]) / 2, w["x0"])):
        center = (word["top"] + word["bottom"]) / 2
        if not lines or abs(center - lines[-1][0]) > tolerance:
            lines.append((center, [word]))
        else:
            lines[-1][1].append(word)
    return [sorted(line, key=lambda w: w["x0"]) for _, line in lines]


def coordinate_table(page):
    """Conservative borderless fallback: two headers, aligned single-line rows.

    Header centers seed column bands; body right-edge medians anchor amounts.
    No sample row count, amount, or page coordinate is used. Ambiguous fragments,
    crossing labels, missing columns, and outlying amounts request review.
    """
    words = page.extract_words(x_tolerance=2, y_tolerance=2)
    headers = sorted([w for w in words if w["text"] in {"前連結会計年度", "当連結会計年度"}],
                     key=lambda w: w["x0"])
    if len(headers) != 2 or abs(headers[0]["top"] - headers[1]["top"]) > 2:
        raise ExtractionError("Coordinate fallback requires two aligned period headers")
    centers = [(w["x0"] + w["x1"]) / 2 for w in headers]
    gap = centers[1] - centers[0]
    if gap <= 4 * max(w["height"] for w in headers):
        raise ExtractionError("Period headers are too close to infer column bands")
    label_right = centers[0] - gap / 2
    column_split = sum(centers) / 2
    lines = _word_lines(words)
    date_lines = [line for line in lines if min(w["top"] for w in line) > max(w["top"] for w in headers)
                  and len(re.findall(r"\d{4}年\d{1,2}月\d{1,2}日",
                                     re.sub(r"\s+", "", normalize("".join(w["text"] for w in line))))) == 2]
    if len(date_lines) != 1:
        raise ExtractionError("Coordinate fallback requires one unambiguous two-period date row")
    after_dates = max(w["bottom"] for w in date_lines[0])
    body = []
    footer_seen = False
    for line in lines:
        if min(w["top"] for w in line) <= after_dates:
            continue
        text = re.sub(r"\s+", "", normalize("".join(w["text"] for w in line)))
        if min(w["top"] for w in line) > page.height * .85 and re.fullmatch(r"-\d+-", text):
            footer_seen = True
            continue
        if footer_seen:
            raise ExtractionError("Unexpected text after the printed page footer")
        labels = [w for w in line if w["x0"] < label_right]
        values = [w for w in line if w["x0"] >= label_right]
        if not labels or any(w["x1"] > label_right for w in labels):
            raise ExtractionError("Coordinate fallback encountered a missing or crossing row label")
        body.append((line, labels, values))
    if not body:
        raise ExtractionError("Coordinate fallback found no body rows")
    candidate_edges = [[], []]
    for _, _, values in body:
        for word in values:
            if normalize(word["text"]) in {"△", "▲", "-", "−"}:
                continue
            try:
                token = parse_cell(word["text"])
            except ExtractionError:
                continue
            if token["status"] in {"number", "dash"}:
                candidate_edges[int(word["x1"] >= column_split)].append(word["x1"])
    if any(len(edges) < 2 for edges in candidate_edges):
        raise ExtractionError("Insufficient body evidence for both numeric columns")
    anchors = [median(edges) for edges in candidate_edges]
    if anchors[0] >= column_split or anchors[1] <= column_split or anchors[1] - anchors[0] < gap / 2:
        raise ExtractionError("Body amount anchors disagree with period-header bands")
    font_height = median(w["height"] for line, _, _ in body for w in line)
    alignment_tolerance = max(2 * font_height, .2 * (anchors[1] - anchors[0]))
    left = max(0, min(w["x0"] for _, labels, _ in body for w in labels) - 2)
    right = min(page.width, max(w["x1"] for line, _, _ in body for w in line) + 2)
    top = max(0, min(w["top"] for w in body[0][0]) - 2)
    bottom = min(page.height, max(w["bottom"] for w in body[-1][0]) + 2)
    if not left < label_right < column_split < right:
        raise ExtractionError("Invalid inferred column boundaries")
    boundaries = [left, label_right, column_split, right]
    rows, raw_rows = [], []
    for i, (line, labels, values) in enumerate(body):
        raw_values = [[], []]
        for word in values:
            column = min(range(2), key=lambda c: abs(word["x1"] - anchors[c]))
            if abs(word["x1"] - anchors[column]) > alignment_tolerance:
                raise ExtractionError("Amount token is outside inferred column alignment", code="extraction_review")
            raw_values[column].append(word)
        amounts = []
        for fragments in raw_values:
            fragments.sort(key=lambda w: w["x0"])
            if len(fragments) > 1 and not (
                len(fragments) == 2 and normalize(fragments[0]["text"]) in {"△", "▲", "-", "−"}
                and parse_cell(fragments[1]["text"])["status"] == "number"
                and not re.match(r"[△▲\-−]", normalize(fragments[1]["text"]))
            ):
                raise ExtractionError("Ambiguous multiple amount tokens in one inferred cell", code="extraction_review")
            raw = "".join(w["text"] for w in fragments)
            parse_cell(raw)  # Reject unsupported values rather than concatenating arbitrary tokens.
            amounts.append(raw)
        row_top = top if i == 0 else (max(w["bottom"] for w in body[i-1][0]) + min(w["top"] for w in line)) / 2
        row_bottom = bottom if i == len(body)-1 else (max(w["bottom"] for w in line) + min(w["top"] for w in body[i+1][0])) / 2
        cells = [(boundaries[j], row_top, boundaries[j+1], row_bottom) for j in range(3)]
        rows.append(CoordinateRegion((left, row_top, right, row_bottom), cells))
        raw_rows.append(["".join(w["text"] for w in labels)] + amounts)
    columns = [CoordinateRegion((boundaries[j], top, boundaries[j+1], bottom)) for j in range(3)]
    return CoordinateTable((left, top, right, bottom), columns, rows, raw_rows)


def extract_metadata(page, table):
    header = page.crop((0, 0, page.width, table.bbox[1]))
    words = header.extract_words()
    header_text = header.extract_text() or ""
    header_normal = normalize(header_text)
    if "単位:千円" not in re.sub(r"\s+", "", header_normal):
        raise ExtractionError("Expected explicit 千円 unit metadata")
    title_line = next((line for line in header_text.splitlines()
                       if "連結貸借対照表" in line), None)
    if not title_line:
        raise ExtractionError("Expected consolidated balance-sheet title")
    labels = [w for w in words if w["text"] in {"前連結会計年度", "当連結会計年度"}]
    if len(labels) != 2:
        raise ExtractionError("Expected two unambiguous period headers")
    columns = []
    # Use detected cell columns to bind headers/dates; never assign by token order.
    for i, column in enumerate(table.columns[1:]):
        x0, _, x1, _ = column.bbox
        selected = [w for w in words if x0 <= (w["x0"] + w["x1"]) / 2 < x1]
        period_labels = [w for w in selected if w in labels]
        if len(period_labels) != 1:
            raise ExtractionError("Header not aligned to detected numeric column")
        label = period_labels[0]
        date_words = [w for w in selected if w["top"] > label["top"] + 1]
        date_text = "".join(w["text"] for w in sorted(date_words, key=lambda w: w["x0"]))
        matches = re.findall(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日", normalize(date_text))
        if len(matches) != 1:
            raise ExtractionError("Could not identify one Gregorian date per column")
        period = date(*map(int, matches[0])).isoformat()
        columns.append(dict(id=f"c{i+1}", label_raw=label["text"], date_raw=date_text,
                            period=period, source_bbox=box(column.bbox)))
    footer = normalize(page.crop((0, table.bbox[3], page.width, page.height)).extract_text() or "")
    footer_number = re.search(r"-\s*(\d+)\s*-", footer)
    return dict(title_raw=title_line, currency="JPY", unit_raw="千円", unit_multiplier=1000,
                correction_marker_raw=next((w["text"] for w in words if "訂正後" in w["text"]), None),
                printed_page_number=int(footer_number.group(1)) if footer_number else None,
                columns=columns)


def extract_page(page, page_index):
    if not page.chars:
        raise ExtractionError(f"Page {page_index}: no text layer; OCR required", code="ocr_required")
    tables = [t for t in page.find_tables() if len(t.rows) >= 2 and len(t.columns) >= 2]
    if not tables:
        table, method = coordinate_table(page), "word_coordinates"
    elif len(tables) == 1 and len(tables[0].columns) == 3:
        table, method = tables[0], "detected_cells"
    else:
        raise ExtractionError(f"Page {page_index}: expected one detected 3-column table")
    metadata = extract_metadata(page, table)
    raw_rows = table.extract()
    staged = []
    for values, geometry in zip(raw_rows, table.rows):
        if len(values) != 3 or any(b is None for b in geometry.cells):
            raise ExtractionError("Merged/missing cells require structural review")
        if values[0] is None or not values[0].strip() or "\n" in values[0]:
            raise ExtractionError("Missing/wrapped label requires structural review")
        label_bounds = geometry.cells[0]
        label_words = page.crop(label_bounds).extract_words()
        if not label_words:
            raise ExtractionError("Label has no positional text evidence")
        label_x0 = min(w["x0"] for w in label_words)
        cells = {c["id"]: parse_cell(raw or "", bounds)
                 for c, raw, bounds in zip(metadata["columns"], values[1:], geometry.cells[1:])}
        staged.append((values[0], label_x0, geometry, cells))
    anchors = cluster_indents([r[1] for r in staged])
    stack, rows = [], []
    for i, (label_raw, x0, geometry, cells) in enumerate(staged, 1):
        depth = min(range(len(anchors)), key=lambda j: abs(anchors[j] - x0))
        while stack and stack[-1]["depth"] >= depth:
            stack.pop()
        if (not stack and depth != 0) or (stack and depth != stack[-1]["depth"] + 1):
            raise ExtractionError("Indentation jump cannot be interpreted safely")
        label = normalize(label_raw)
        is_blank = all(c["status"] == "blank" for c in cells.values())
        if any(c["status"] == "blank" for c in cells.values()) and not is_blank:
            raise ExtractionError(f"Partially blank value row: {label_raw}")
        kind = "section" if is_blank else "subtotal" if label.endswith("合計") else "net" if "(純額)" in label else "item"
        parent = stack[-1] if stack else None
        row = dict(id=f"r{i:03d}", label_raw=label_raw, label=label,
                   depth=depth, parent_id=parent["id"] if parent else None,
                   path=(parent["path"] if parent else []) + [label], kind=kind,
                   label_x0=round(x0, 4), source_bbox=box(geometry.bbox),
                   label_source_bbox=box(geometry.cells[0]), cells=cells)
        rows.append(row)
        stack.append(row)
    return dict(page_index=page_index, extraction_method=method, width=page.width, height=page.height,
                table_bbox=box(table.bbox), metadata=metadata, rows=rows)


def parse_document(path):
    path = Path(path)
    pages = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            try:
                pages.append(extract_page(page, i))
            except ExtractionError as exc:
                raise ExtractionError(f"{path.name}, page {i}: {exc}", code=exc.code) from exc
    return dict(schema_version="1.1.0", source=dict(filename=path.name,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), page_count=len(pages)),
                extractor=dict(name="pdfplumber", version=pdfplumber.__version__,
                               method="detected_cells_with_word_coordinate_fallback"), pages=pages)


def write_outputs(document, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "table.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for page in document["pages"]:
        columns = page["metadata"]["columns"]
        with (output / f"page_{page['page_index']}_wide.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["label_raw"] + [c["period"] for c in columns])
            for row in page["rows"]:
                writer.writerow([row["label_raw"]] + [row["cells"][c["id"]]["raw"] for c in columns])
    fields = ["page_index", "row_id", "parent_id", "depth", "kind", "path", "label_raw",
              "period", "currency", "unit_multiplier", "raw", "normalized", "value", "status", "negative_zero"]
    # Long-form CSV: one row/period observation per record, including blank sections.
    with (output / "table.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for page in document["pages"]:
            meta = page["metadata"]
            for row in page["rows"]:
                for col in meta["columns"]:
                    cell = row["cells"][col["id"]]
                    writer.writerow(dict(page_index=page["page_index"], row_id=row["id"],
                        parent_id=row["parent_id"], depth=row["depth"], kind=row["kind"],
                        path=json.dumps(row["path"], ensure_ascii=False), label_raw=row["label_raw"],
                        period=col["period"], currency=meta["currency"], unit_multiplier=meta["unit_multiplier"],
                        **{k: cell[k] for k in ["raw", "normalized", "value", "status", "negative_zero"]}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    try:
        document = parse_document(args.input)
        write_outputs(document, args.output)
    except (ExtractionError, OSError) as exc:
        print(f"Extraction failed: {exc}", file=sys.stderr)
        return 2
    print(f"Extracted {sum(len(p['rows']) for p in document['pages'])} rows across {len(document['pages'])} page(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
