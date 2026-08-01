from __future__ import annotations

import csv
import html
from pathlib import Path

from app.output.templates import BASE_CSS


HEADERS = [
    "claim_id",
    "patient",
    "date_of_service",
    "denied_amount",
    "outcome",
    "next_step",
    "actor",
    "confidence",
    "validator_flags",
    "source_discrepancies",
    "artifacts",
    "model_rationale",
]


def generate_handoff(rows: list[dict], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "handoff-summary.csv"
    html_path = output_dir / "handoff-summary.html"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows([{key: row.get(key, "") for key in HEADERS} for row in rows])
    body_rows = "".join(
        "<tr>"
        + "".join(f"<td>{html.escape(str(row.get(key, '')))}</td>" for key in HEADERS)
        + "</tr>"
        for row in rows
    )
    html_path.write_text(
        f"""<!doctype html><html><head><meta charset="utf-8"><style>{BASE_CSS}
        @page {{ size: Letter landscape; margin: .45in; }} body {{ font-size: 9pt; }}
        h1 {{ color: #173f5f; }} .sub {{ color: #475569; margin-bottom: 16px; }}</style></head>
        <body><h1>Denials handoff summary</h1>
        <p class="sub">One row per normalized claim. Paid/no-action claims remain visible so reconciliation is complete.</p>
        <table><thead><tr>{''.join(f'<th>{html.escape(key.replace("_", " ").title())}</th>' for key in HEADERS)}</tr></thead>
        <tbody>{body_rows}</tbody></table></body></html>""",
        encoding="utf-8",
    )
    return html_path, csv_path

