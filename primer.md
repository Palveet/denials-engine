# Domain primer

**The billing loop.** An ambulance service (the *provider*) sends a claim to an insurance company (the *payer*). The payer adjudicates it and responds. That response reaches the provider two ways, often both:

- **835 remittance (ERA).** An X12 EDI file straight from the payer. Segments end with `~`, elements are separated by `*`. Each claim lives in a `CLP` loop: `CLP` (claim ID, claim status - `1` = processed and paid as primary, `4` = denied - billed, paid, patient responsibility), `NM1*QC` (patient; the element after the `MI` qualifier is the member ID), `DTM` (dates: `232` = claim statement date, `472` = service-line date), `SVC` (service lines - ambulance HCPCS codes: `A0425` ground mileage, `A0426` ALS non-emergency transport, `A0427` ALS emergency, `A0429` BLS emergency, `A0433` ALS level 2), `CAS` (adjustments), `LQ*HE` (remark codes). `BPR` at the top carries the total payment for the whole file.
- **Clearinghouse export.** The clearinghouse is a middleman that routes claims and responses. Its denials report is a flattened CSV. Field formats are its own (dates, names, code formats).

**CARC / RARC.** A `CAS` segment reads `CAS*<group>*<reason>*<amount>`. The group code says who absorbs the money: `CO` = contractual obligation (provider write-off), `PR` = patient responsibility. The reason is a CARC - a standard Claim Adjustment Reason Code. RARCs (in `LQ*HE` segments) are remark codes that add detail. `carc_cheatsheet.md` explains every code that appears in this data.

**Fax.** Payers in this scenario accept correspondence only by fax. An appeal, a records submission, or an authorization request arrives at the payer's intake queue, gets routed by its cover sheet, and lands on an examiner's desk. A usable cover sheet identifies: patient name, member ID (where you have it), claim ID, date of service, provider name and NPI, what is being requested, and a page count.

**Payer directory (synthetic).**
Granite State Health Plan - Provider Appeals & Authorizations fax: (603) 555-0188. Provider services phone: (603) 555-0142. Mail: PO Box 91000, Concord, NH 03301.

**Provider (synthetic).**
Skyline Ambulance Service - NPI 1999999984, 4400 Airport Road, Nashua, NH 03063.

All data in this exercise is synthetic: fake payer, fake patients, fake identifiers. Nothing here is PHI.

