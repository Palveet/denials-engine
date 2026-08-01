export default function RunProgress({ status }) {
  const percent = status.total ? Math.round((status.completed / status.total) * 100) : 0;
  return (
    <section className="progress-card">
      <div className="card-heading">
        <div>
          <p className="kicker">Step 2</p>
          <h2>The agent is reviewing each work item</h2>
        </div>
        <span className="progress-number">{status.completed}/{status.total}</span>
      </div>
      <div className="progress-track"><span style={{ width: `${percent}%` }} /></div>
      <div className="progress-list">
        {status.items.map((item) => (
          <div className="progress-row" key={item.decision_id}>
            <div><strong>{item.claim_id}</strong><span>{item.code}</span></div>
            <span className={`status-dot ${item.status}`}>{item.status}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

