async function request(path, options = {}) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      // Keep the HTTP status when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

export const api = {
  health: () => request("/api/health"),
  upload: (formData) => request("/api/upload", { method: "POST", body: formData }),
  run: (runId) =>
    request("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId }),
    }),
  status: (runId) => request(`/api/run/${runId}/status`),
  claims: (runId) => request(`/api/claims?run_id=${encodeURIComponent(runId)}`),
  artifacts: (runId) => request(`/api/artifacts?run_id=${encodeURIComponent(runId)}`),
};

