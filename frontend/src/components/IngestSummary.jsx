export default function IngestSummary({ summary, onRun, busy }) {
  const metrics = [
    [summary.normalized_claims, "normalized claims"],
    [summary.denials, "decision-bearing denials"],
    [summary.overlapping_claims, "claims in both sources"],
    [summary.discrepancy_count, "recorded discrepancies"],
  ];
  return (
    <section className="summary-card">
      <div className="card-heading">
        <div>
          <p className="kicker">Ingest passed</p>
          <h2>Sources reconciled without double-counting</h2>
        </div>
        <span className="pill success">BPR ${summary.bpr_total}</span>
      </div>
      <div className="metric-grid">
        {metrics.map(([value, label]) => (
          <div className="metric" key={label}>
            <strong>{value}</strong>
            <span>{label}</span>
          </div>
        ))}
      </div>
      <div className="summary-note">
        <span>ERA {summary.era_claims} · CSV {summary.csv_claims} · {summary.decision_work_items} model work items</span>
        <button className="primary" onClick={onRun} disabled={busy}>
          {busy ? "Starting agent…" : "Run decision agent"}
        </button>
      </div>
    </section>
  );
}

