import { useEffect, useState } from "react";
import { api } from "./api";
import ArtifactsList from "./components/ArtifactsList";
import ClaimsTable from "./components/ClaimsTable";
import IngestSummary from "./components/IngestSummary";
import RunProgress from "./components/RunProgress";
import UploadForm from "./components/UploadForm";

export default function App() {
  const [phase, setPhase] = useState("idle");
  const [health, setHealth] = useState(null);
  const [summary, setSummary] = useState(null);
  const [status, setStatus] = useState(null);
  const [claims, setClaims] = useState([]);
  const [artifacts, setArtifacts] = useState([]);
  const [error, setError] = useState("");

  useEffect(() => { api.health().then(setHealth).catch(() => null); }, []);

  useEffect(() => {
    if (phase !== "running" || !summary?.run_id) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const next = await api.status(summary.run_id);
        setStatus(next);
        if (next.status === "completed") {
          window.clearInterval(timer);
          const [claimData, artifactData] = await Promise.all([
            api.claims(summary.run_id),
            api.artifacts(summary.run_id),
          ]);
          setClaims(claimData);
          setArtifacts(artifactData);
          setPhase("done");
        } else if (next.status === "failed") {
          window.clearInterval(timer);
          setError(next.error || "The run failed.");
          setPhase("uploaded");
        }
      } catch (err) {
        setError(err.message);
      }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [phase, summary]);

  async function upload(form) {
    setError("");
    setPhase("uploading");
    try {
      const result = await api.upload(form);
      setSummary(result);
      setPhase("uploaded");
    } catch (err) {
      setError(err.message);
      setPhase("idle");
    }
  }

  async function run() {
    setError("");
    setPhase("starting");
    try {
      await api.run(summary.run_id);
      setStatus({ total: summary.decision_work_items, completed: 0, items: [] });
      setPhase("running");
    } catch (err) {
      setError(err.message);
      setPhase("uploaded");
    }
  }

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand-mark" href="/"><span>MD</span><strong>Mini Denials</strong></a>
        <div className="header-status">
          <span className={`live-dot ${health?.status === "ok" ? "online" : ""}`} />
          {health?.status === "ok" ? "Pipeline ready" : "Connecting"}
        </div>
      </header>
      <main>
        <section className="hero">
          <div>
            <p className="kicker">Ambulance billing operations</p>
            <h1>Turn payer responses into a clear next move.</h1>
            <p className="hero-copy">Reconcile an 835 with a clearinghouse export, let a constrained model review every claim, and leave with biller-ready handoffs and fax packets.</p>
          </div>
          <div className="hero-rail"><span>01 Ingest</span><span>02 Decide</span><span>03 Handoff</span></div>
        </section>

        {health?.status === "ok" && health?.llm_configured === false && (
          <div className="mode-warning"><strong>Model configuration is incomplete.</strong> Add <code>ANTHROPIC_API_KEY</code> and the exact <code>LLM_MODEL</code> ID to <code>.env</code>, then restart.</div>
        )}
        {error && <div className="error-banner"><strong>Needs attention</strong><span>{error}</span></div>}
        <UploadForm onSubmit={upload} busy={phase === "uploading"} currentDate={health?.current_date} />
        {summary && <IngestSummary summary={summary} onRun={run} busy={phase === "starting" || phase === "running"} />}
        {phase === "running" && status && <RunProgress status={status} />}
        {phase === "done" && (
          <>
            <ClaimsTable claims={claims} />
            <ArtifactsList artifacts={artifacts} />
          </>
        )}
      </main>
      <footer>Built for transparent review: facts, model output, guardrails, and artifacts remain inspectable.</footer>
    </div>
  );
}
