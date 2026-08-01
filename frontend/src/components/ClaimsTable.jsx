const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

function DecisionDetail({ claim, decision }) {
  const policy = decision.policy || {};
  return (
    <div className="decision-detail">
      <div className={`policy-callout ${policy.status || "human_review"}`}>
        <div>
          <strong>{policy.label || "Human review"}</strong>
          <p>{policy.reason || "No independent policy assessment is available."}</p>
        </div>
        {policy.expected && (
          <div className="policy-baseline">
            <span>Policy baseline</span>
            <strong>{policy.expected.outcome.replaceAll("_", " ")} · {policy.expected.next_action.replaceAll("_", " ")}</strong>
          </div>
        )}
        {policy.evidence?.length > 0 && <small>Evidence: {policy.evidence.join(" • ")}</small>}
      </div>
      <div>
        <h4>{policy.status === "guardrail_corrected" ? "Guardrail explanation" : "Claude rationale"}</h4>
        <p>{decision.rationale || "Decision pending"}</p>
      </div>
      <div className="detail-grid">
        <div><span>Actor</span><strong>{decision.actor || "—"}</strong></div>
        <div><span>Confidence</span><strong>{decision.confidence == null ? "—" : `${Math.round(decision.confidence * 100)}%`}</strong></div>
        <div><span>Model</span><strong>{decision.model_name || "—"}</strong></div>
        <div><span>Prompt</span><strong>{decision.prompt_version || "—"}</strong></div>
      </div>
      {(claim.discrepancies?.length > 0 || decision.validator_flags?.length > 0) && (
        <div className="flags">
          {claim.discrepancies?.map((flag) => <span key={flag.field}>discrepancy: {flag.field}</span>)}
          {decision.validator_flags?.map((flag) => <span key={flag}>{flag}</span>)}
        </div>
      )}
      <details className="raw-json">
        <summary>Inspect fact sheet and raw model response</summary>
        <div className="json-grid">
          <pre>{JSON.stringify(decision.fact_sheet, null, 2)}</pre>
          <pre>{JSON.stringify(decision.llm_raw, null, 2)}</pre>
        </div>
      </details>
    </div>
  );
}

export default function ClaimsTable({ claims }) {
  return (
    <section className="results-card">
      <div className="card-heading">
        <div>
          <p className="kicker">Step 3</p>
          <h2>Claim decisions</h2>
        </div>
        <span className="pill neutral">{claims.length} reconciled claims</span>
      </div>
      <div className="decision-guide">
        <strong>How to judge a decision</strong>
        <span><b>Rule confirmed</b> means Claude matches the supplied billing rules.</span>
        <span><b>Human review</b> means the files do not contain enough information for a safe automatic answer.</span>
        <span><b>Claude corrected</b> means a deterministic guardrail replaced an unsafe recommendation.</span>
      </div>
      <div className="claim-list">
        {claims.map((claim) => {
          const decision = claim.decisions[0] || {};
          const denial = claim.denials?.[0];
          const hasDenial = (claim.denials?.length || 0) > 0;
          return (
            <details className="claim-row" key={claim.claim_id}>
              <summary>
                <div className="claim-identity"><strong>{claim.claim_id}</strong><span>{claim.patient_name}</span></div>
                <div className="claim-amount"><span>{hasDenial ? "Denied" : "No denial"}</span><strong>{money.format(Number(denial?.denied_amount || 0))}</strong></div>
                <span className={`outcome ${decision.outcome || "pending"}`}>{(decision.outcome || "pending").replaceAll("_", " ")}</span>
                <div className="next-action">
                  <span>Next step</span>
                  <strong>{(decision.next_action || "pending").replaceAll("_", " ")}</strong>
                  <em className={`policy-badge ${decision.policy?.status || "human_review"}`}>{decision.policy?.label || "Human review"}</em>
                </div>
                <span className="chevron">⌄</span>
              </summary>
              <DecisionDetail claim={claim} decision={decision} />
            </details>
          );
        })}
      </div>
    </section>
  );
}
