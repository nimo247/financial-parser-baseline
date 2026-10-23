"""Serialize independently entered TSV. Never imports or executes the parser.

Amounts in *_value were entered explicitly, not calculated from *_raw.
Parent IDs were assigned by visual interpretation, not inferred from coordinates.
"""
import csv
import json
from pathlib import Path
import unicodedata

ROOT = Path(__file__).resolve().parent


def build():
    rows, index = [], {}
    with (ROOT / "manual_reference.tsv").open(encoding="utf-8", newline="") as stream:
        for entered in csv.DictReader(stream, delimiter="\t"):
            parent = entered["parent_id"] or None
            label = unicodedata.normalize("NFKC", entered["label_raw"])
            row = dict(id=entered["id"], parent_id=parent, depth=int(entered["depth"]),
                       kind=entered["kind"], label_raw=entered["label_raw"], label=label,
                       path=(index[parent]["path"] if parent else []) + [label], cells={})
            for col, prefix in [("c1", "prior"), ("c2", "current")]:
                typed = entered[prefix + "_value"]
                row["cells"][col] = dict(raw=entered[prefix + "_raw"],
                    value=None if typed in {"DASH", "BLANK"} else int(typed),
                    status={"DASH": "dash", "BLANK": "blank"}.get(typed, "number"),
                    negative_zero=entered["id"] == "r012" and col == "c2")
            rows.append(row)
            index[row["id"]] = row
    return dict(reference_version="1.0.0", source_sha256="0764bba6f5f0e7984a837e4cc19d8bb95db4a7ac22c26f18c95bbe652c983c74",
        provenance=dict(method="AI-assisted manual transcription and visual review of rendered source",
                        independent_of_parser_output=True, independent_human_review=False,
                        limitations="Same assistant authored parser and reference; independent human review is pending."),
        metadata=dict(page_index=1, printed_page_number=4, currency="JPY", unit_raw="千円",
                      unit_multiplier=1000, correction_marker_raw="（訂正後）",
                      periods=["2025-03-31", "2026-03-31"]), rows=rows)


if __name__ == "__main__":
    (ROOT / "expected.json").write_text(json.dumps(build(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
