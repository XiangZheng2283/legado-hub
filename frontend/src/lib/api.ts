const API_BASE = "/api/console"

async function fetchJson(path: string, options?: RequestInit): Promise<any> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}: ${res.statusText}`)
  }
  return res.json()
}

export const api = {
  status: (): Promise<any> => fetch("/api/console/status").then((r) => r.json()),

  plugins: (): Promise<any> => fetchJson("/plugins"),
  plugin: (id: string): Promise<any> => fetchJson(`/plugins/${id}`),
  reloadPlugins: (): Promise<any> => fetchJson("/plugins/reload", { method: "POST" }),
  enablePlugin: (id: string, enabled: boolean): Promise<any> =>
    fetchJson(`/plugins/${id}/enable`, {
      method: "POST",
      body: JSON.stringify({ enabled }),
    }),
  smokePlugin: (id: string, keyword?: string): Promise<any> =>
    fetchJson(`/plugins/${id}/smoke`, {
      method: "POST",
      body: JSON.stringify({ mode: "fixture", keyword: keyword || "凡人修仙传" }),
    }),
  pluginAuth: (id: string): Promise<any> => fetchJson(`/plugins/${id}/auth`),
  pluginLogin: (id: string): Promise<any> => fetchJson(`/plugins/${id}/login`, { method: "POST" }),
  pluginAuthCheck: (id: string): Promise<any> => fetchJson(`/plugins/${id}/auth/check`, { method: "POST" }),
  pluginCookiesClear: (id: string): Promise<any> => fetchJson(`/plugins/${id}/cookies/clear`, { method: "POST" }),
  submitBrowserChallengeCookies: (sessionId: string, cookies: any): Promise<any> =>
    fetchJson(`/browser-challenges/${sessionId}/cookies`, {
      method: "POST",
      body: JSON.stringify({ cookies }),
    }),
  retryBrowserChallengeLiveCheck: (sessionId: string, keyword?: string): Promise<any> =>
    fetchJson(`/browser-challenges/${sessionId}/retry-live-check`, {
      method: "POST",
      body: JSON.stringify({ keyword: keyword || "凡人修仙传" }),
    }),
  openBrowserChallengeBrowser: (sessionId: string): Promise<any> =>
    fetchJson(`/browser-challenges/${sessionId}/browser/open`, { method: "POST" }),
  importBrowserChallengeCookies: (sessionId: string): Promise<any> =>
    fetchJson(`/browser-challenges/${sessionId}/browser/import-cookies`, { method: "POST" }),

  createSearchJob: (keyword: string, page?: number, limit?: number): Promise<any> =>
    fetchJson("/search-jobs", {
      method: "POST",
      body: JSON.stringify({ keyword, page: page || 1, limit }),
    }),
  searchJob: (id: string): Promise<any> => fetchJson(`/search-jobs/${id}`),
  searchJobEvents: (id: string, after?: number): Promise<any> =>
    fetchJson(`/search-jobs/${id}/events?after=${after || 0}`),
  searchJobCandidates: (id: string): Promise<any> => fetchJson(`/search-jobs/${id}/candidates`),
  verifySearchCandidate: (jobId: string, candidateId: string, chapterIndex?: number): Promise<any> =>
    fetchJson(`/search-jobs/${jobId}/candidates/${candidateId}/verify`, {
      method: "POST",
      body: JSON.stringify({ chapterIndex: chapterIndex || 0 }),
    }),
  cancelSearchJob: (id: string): Promise<any> =>
    fetchJson(`/search-jobs/${id}/cancel`, { method: "POST" }),
  liveCheckPlugin: (id: string, keyword?: string): Promise<any> =>
    fetchJson(`/plugins/${id}/live-check`, {
      method: "POST",
      body: JSON.stringify({ keyword: keyword || "凡人修仙传" }),
    }),
  pluginLiveChecks: (id: string): Promise<any> => fetchJson(`/plugins/${id}/live-checks`),

  cache: (): Promise<any> => fetchJson("/cache"),
  clearCache: (): Promise<any> => fetchJson("/cache", { method: "DELETE" }),

  settings: (): Promise<any> => fetchJson("/settings"),
  updateSettings: (payload: Record<string, any>): Promise<any> =>
    fetchJson("/settings", { method: "POST", body: JSON.stringify(payload) }),

  aggregateSource: (): Promise<any> => fetchJson("/aggregate-source"),
  regenerateAggregateSource: (): Promise<any> =>
    fetchJson("/aggregate-source/regenerate", { method: "POST" }),

  verification: (): Promise<any> => fetchJson("/verification"),
  runVerification: (): Promise<any> => fetchJson("/verification/run", { method: "POST" }),
}
