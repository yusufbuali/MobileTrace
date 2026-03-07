// Shared fetch helpers
export async function apiFetch(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

export const api = {
  getCases: (status) => apiFetch(`/api/cases${status ? `?status=${status}` : ""}`),
  getCase: (id) => apiFetch(`/api/cases/${id}`),
  createCase: (body) => apiFetch("/api/cases", { method: "POST", body: JSON.stringify(body) }),
  updateCase: (id, body) => apiFetch(`/api/cases/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  deleteCase: (id) => apiFetch(`/api/cases/${id}`, { method: "DELETE" }),
};
