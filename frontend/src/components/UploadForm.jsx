import { useState } from "react";

function displayDate(value) {
  if (!value) return "Loading…";
  const [year, month, day] = value.split("-");
  return `${month}/${day}/${year}`;
}

export default function UploadForm({ onSubmit, busy, currentDate }) {
  const [era, setEra] = useState(null);
  const [csv, setCsv] = useState(null);

  function submit(event) {
    event.preventDefault();
    if (!era || !csv) return;
    const form = new FormData();
    form.append("era_file", era);
    form.append("csv_file", csv);
    onSubmit(form);
  }

  return (
    <form className="upload-card" onSubmit={submit}>
      <div className="card-heading">
        <div>
          <p className="kicker">Step 1</p>
          <h2>Load the payer responses</h2>
        </div>
        <span className="pill neutral">UTF-8 · 5 MB max</span>
      </div>
      <div className="file-grid">
        <label className={`drop-zone ${era ? "selected" : ""}`}>
          <span className="file-type">835</span>
          <strong>{era ? era.name : "Choose the remittance file"}</strong>
          <span>Direct payer adjudication record</span>
          <input type="file" accept=".835" onChange={(e) => setEra(e.target.files[0])} />
        </label>
        <label className={`drop-zone ${csv ? "selected" : ""}`}>
          <span className="file-type">CSV</span>
          <strong>{csv ? csv.name : "Choose the denials export"}</strong>
          <span>Clearinghouse report for reconciliation</span>
          <input type="file" accept=".csv,text/csv" onChange={(e) => setCsv(e.target.files[0])} />
        </label>
      </div>
      <div className="form-footer">
        <div className="date-field">
          <span>Decision as-of date</span>
          <strong className="current-date">{displayDate(currentDate)}</strong>
          <small>Automatically set to today</small>
        </div>
        <button className="primary" disabled={!era || !csv || busy}>
          {busy ? "Parsing…" : "Parse and reconcile"}
        </button>
      </div>
    </form>
  );
}
