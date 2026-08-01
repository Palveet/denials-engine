from __future__ import annotations

BASE_CSS = """
@page { size: Letter; margin: 0.58in; }
* { box-sizing: border-box; }
body { font-family: Arial, Helvetica, sans-serif; color: #111827; font-size: 10.5pt; line-height: 1.42; margin: 0; }
h1 { font-size: 21pt; margin: 0 0 8px; letter-spacing: -0.02em; }
h2 { font-size: 13pt; margin: 18px 0 7px; color: #173f5f; }
p { margin: 0 0 10px; }
.cover { min-height: 9.3in; display: flex; flex-direction: column; }
.letter { break-before: page; }
.brand { border-top: 7px solid #0d9488; padding-top: 16px; margin-bottom: 20px; }
.eyebrow { color: #0f766e; font-weight: 700; text-transform: uppercase; letter-spacing: .12em; font-size: 8.5pt; }
.cover-table { border: 1px solid #cbd5e1; border-radius: 8px; border-collapse: separate; border-spacing: 0; table-layout: fixed; overflow: hidden; }
.cover-table td { width: 50%; border: 0; border-bottom: 1px solid #e2e8f0; padding: 10px 14px; vertical-align: top; font-size: 10.5pt; }
.cover-table td + td { border-left: 1px solid #e2e8f0; }
.cover-table tr:last-child td { border-bottom: 0; }
.label { display: block; color: #64748b; font-size: 8pt; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 3px; }
.value { display: block; font-weight: 700; overflow-wrap: anywhere; }
.notice { margin-top: 18px; background: #f1f5f9; border-left: 4px solid #0d9488; padding: 11px 13px; }
.checklist { margin-top: 14px; border: 1px solid #f59e0b; background: #fffbeb; padding: 10px 13px; }
.footer { margin-top: auto; color: #64748b; font-size: 8.5pt; border-top: 1px solid #cbd5e1; padding-top: 8px; }
.letterhead { display: flex; justify-content: space-between; gap: 30px; border-bottom: 2px solid #0d9488; padding-bottom: 12px; margin-bottom: 20px; }
.letterhead strong { color: #173f5f; font-size: 14pt; }
.meta { text-align: right; color: #475569; font-size: 9pt; }
.subject { background: #f1f5f9; padding: 10px 12px; margin: 14px 0; }
.signature { margin-top: 25px; }
.basis { border-left: 3px solid #94a3b8; padding-left: 12px; color: #334155; }
table { border-collapse: collapse; width: 100%; }
th { text-align: left; background: #173f5f; color: white; padding: 7px; font-size: 8.5pt; }
td { border-bottom: 1px solid #d8e0e8; padding: 7px; vertical-align: top; font-size: 8.5pt; }
"""
