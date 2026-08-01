export default function ArtifactsList({ artifacts }) {
  const packets = artifacts.filter((artifact) => artifact.kind === "fax_packet");
  const handoff = artifacts.filter((artifact) => artifact.kind.startsWith("handoff_"));
  const zip = artifacts.find((artifact) => artifact.kind === "all_artifacts_zip");
  return (
    <section className="artifacts-card">
      <div className="card-heading">
        <div>
          <p className="kicker">Step 4</p>
          <h2>Review and download</h2>
        </div>
        {zip && <a className="primary link-button" href={zip.download_url}>Download all</a>}
      </div>
      <div className="artifact-groups">
        <div>
          <h3>Fax packets</h3>
          {packets.map((artifact) => (
            <div className="artifact-row" key={artifact.id}>
              <div><strong>{artifact.claim_id}</strong><span>Cover sheet + letter · {artifact.page_count} pages</span></div>
              <div className="artifact-actions">
                <a href={artifact.preview_url} target="_blank" rel="noreferrer">Preview</a>
                <a href={artifact.download_url}>PDF</a>
              </div>
            </div>
          ))}
        </div>
        <div>
          <h3>Handoff</h3>
          {handoff.map((artifact) => (
            <div className="artifact-row" key={artifact.id}>
              <div><strong>{artifact.kind === "handoff_csv" ? "Spreadsheet-ready CSV" : "Readable HTML summary"}</strong><span>Every normalized claim</span></div>
              <a href={artifact.download_url}>Download</a>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

