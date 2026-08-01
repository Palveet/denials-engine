from __future__ import annotations

import html
import os
import sys
from datetime import date
from pathlib import Path

if sys.platform == "darwin" and Path("/opt/homebrew/lib").exists():
    # Homebrew provides Pango/Cairo on Apple Silicon; cffi needs the library
    # search path before WeasyPrint is imported.
    current_library_path = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(
        item for item in ("/opt/homebrew/lib", current_library_path) if item
    )
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/mini-denials-cache")

from pypdf import PdfReader
from weasyprint import HTML

from app.constants import PAYER, PROVIDER, RARC_DESCRIPTIONS
from app.output.templates import BASE_CSS
from app.schemas import ClaimData, DenialData, ValidatedDecision


def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _request_label(action: str) -> str:
    return {
        "submit_appeal": "Medical necessity appeal",
        "submit_records": "Records submission / claim reconsideration",
        "request_retro_auth": "Retro-authorization request",
    }.get(action, action.replace("_", " ").title())


def _denial_code(denial: DenialData) -> str:
    if not denial.carc:
        return "a reason code the payer did not supply"
    return f"{denial.group_code}-{denial.carc}"


def _remark_sentence(denial: DenialData) -> str:
    """Cite remark codes only when the payer actually sent them."""
    if not denial.rarcs:
        return ""
    described = ", ".join(
        f"{code} ({RARC_DESCRIPTIONS[code].rstrip('.')})" if code in RARC_DESCRIPTIONS else code
        for code in denial.rarcs
    )
    return f" The payer cited remark code {_e(described)}."


def _requested_material(denial: DenialData) -> str:
    """Name the enclosure the denial itself asks for, not the one the action implies."""
    rarcs = set(denial.rarcs)
    if "M60" in rarcs:
        return "the signed Certificate of Medical Necessity"
    if denial.carc == "16":
        return "the documentation identified by the payer's remark codes"
    if denial.carc == "50":
        return "the clinical records supporting the medical necessity of this transport"
    if denial.carc == "197":
        return "the authorization request and supporting records"
    return "the supporting documentation for this claim"


def _letter_body(claim: ClaimData, denial: DenialData, decision: ValidatedDecision) -> str:
    code = _denial_code(denial)
    material = _requested_material(denial)
    remark = _remark_sentence(denial)
    line_text = ""
    if denial.service_line_sequence:
        line = next(
            (item for item in claim.service_lines if item.sequence == denial.service_line_sequence),
            None,
        )
        if line:
            line_text = (
                f" This request is limited to service line {_e(line.hcpcs)} "
                f"({_e(line.service_date or claim.date_of_service)}), denied amount ${_e(denial.denied_amount)}."
            )
    if decision.next_action.value == "submit_records":
        return (
            f"{_e(PAYER['name'])} denied the referenced service under {_e(code)}.{remark} "
            f"We are submitting {_e(material)} and ask that the claim be reconsidered on that record."
            + line_text
        )
    if decision.next_action.value == "request_retro_auth":
        return (
            f"The referenced service was denied under {_e(code)} for absent authorization.{remark} "
            "Please advise whether retro-authorization is available under the member's plan and review "
            f"the enclosed request together with {_e(material)}."
            + line_text
        )
    return (
        f"We request reconsideration of the referenced service denied under {_e(code)}.{remark} "
        f"The enclosed material includes {_e(material)}. "
        "Please reverse the denial or provide the specific coverage criteria that remain unmet."
        + line_text
    )


def packet_html(
    claim: ClaimData,
    denial: DenialData,
    decision: ValidatedDecision,
    *,
    packet_date: date,
    page_count: int | str,
) -> str:
    member = claim.member_id or f"Not on file - clearinghouse ref {claim.clearinghouse_ref or 'not supplied'}"
    request_label = _request_label(decision.next_action.value)
    attachments = f"Attach {_requested_material(denial)} before faxing."
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><style>{BASE_CSS}</style><title>{_e(claim.claim_id)} fax packet</title></head>
<body>
  <section class="cover">
    <div class="brand"><div class="eyebrow">Fax cover sheet</div><h1>{_e(request_label)}</h1>
      <p>{_e(PROVIDER['name'])} · NPI {_e(PROVIDER['npi'])}</p></div>
    <table class="cover-table"><tbody>
      <tr><td><span class="label">To</span><span class="value">{_e(PAYER['name'])}</span></td>
          <td><span class="label">Destination fax</span><span class="value">{_e(PAYER['fax'])}</span></td></tr>
      <tr><td><span class="label">Patient</span><span class="value">{_e(claim.patient_name)}</span></td>
          <td><span class="label">Member ID</span><span class="value">{_e(member)}</span></td></tr>
      <tr><td><span class="label">Claim ID</span><span class="value">{_e(claim.claim_id)}</span></td>
          <td><span class="label">Date of service</span><span class="value">{_e(claim.date_of_service)}</span></td></tr>
      <tr><td><span class="label">Provider</span><span class="value">{_e(PROVIDER['name'])}</span></td>
          <td><span class="label">Provider NPI</span><span class="value">{_e(PROVIDER['npi'])}</span></td></tr>
      <tr><td colspan="2"><span class="label">Request</span><span class="value">{_e(request_label)}</span></td></tr>
      <tr><td><span class="label">Generated packet pages</span><span class="value">{_e(page_count)}</span></td>
          <td><span class="label">Date</span><span class="value">{_e(packet_date)}</span></td></tr>
    </tbody></table>
    <div class="checklist"><strong>Before sending:</strong> {_e(attachments)} The generated page count excludes external attachments.</div>
    <div class="notice"><strong>Synthetic exercise data.</strong> This packet contains no real PHI. Verify the destination and every attachment before any real-world use.</div>
    <div class="footer">Prepared by the Mini Denials Engine for biller review. The application does not transmit faxes.</div>
  </section>
  <section class="letter">
    <div class="letterhead"><div><strong>{_e(PROVIDER['name'])}</strong><br>{_e(PROVIDER['address'])}<br>NPI {_e(PROVIDER['npi'])}</div>
      <div class="meta">{_e(packet_date)}<br>Via fax: {_e(PAYER['fax'])}</div></div>
    <p>{_e(PAYER['name'])}<br>{_e(PAYER['address'])}</p>
    <div class="subject"><strong>Re: {_e(request_label)}</strong><br>
      Patient: {_e(claim.patient_name)} · Member ID: {_e(member)}<br>
      Claim: {_e(claim.claim_id)} · DOS: {_e(claim.date_of_service)}</div>
    <p>To the Claims Review Team:</p>
    <p>{_letter_body(claim, denial, decision)}</p>
    <p>Please send the written determination to the provider address above. For questions, contact the submitting biller.</p>
    <div class="signature"><p>Sincerely,</p><p><strong>Billing Department</strong><br>{_e(PROVIDER['name'])}</p></div>
  </section>
</body></html>"""


def generate_fax_packet(
    claim: ClaimData,
    denial: DenialData,
    decision: ValidatedDecision,
    *,
    output_dir: Path,
    packet_date: date,
) -> tuple[Path, Path, int]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{claim.claim_id.lower()}-{decision.next_action.value.replace('_', '-')}"
    html_path = output_dir / f"{stem}.html"
    pdf_path = output_dir / f"{stem}.pdf"
    draft = packet_html(claim, denial, decision, packet_date=packet_date, page_count="calculating")
    draft_pages = len(HTML(string=draft, base_url=str(output_dir)).render().pages)
    final_html = packet_html(
        claim,
        denial,
        decision,
        packet_date=packet_date,
        page_count=draft_pages,
    )
    html_path.write_text(final_html, encoding="utf-8")
    HTML(string=final_html, base_url=str(output_dir)).write_pdf(pdf_path)
    actual_pages = len(PdfReader(str(pdf_path)).pages)
    if actual_pages != draft_pages:
        final_html = packet_html(
            claim,
            denial,
            decision,
            packet_date=packet_date,
            page_count=actual_pages,
        )
        html_path.write_text(final_html, encoding="utf-8")
        HTML(string=final_html, base_url=str(output_dir)).write_pdf(pdf_path)
        actual_pages = len(PdfReader(str(pdf_path)).pages)
    return html_path, pdf_path, actual_pages
