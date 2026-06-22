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
  batchEnablePlugins: (pluginIds: string[], enabled: boolean): Promise<any> =>
    fetchJson("/plugins/batch-enable", {
      method: "POST",
      body: JSON.stringify({ pluginIds, enabled }),
    }),
  batchDeletePlugins: (pluginIds: string[]): Promise<any> =>
    fetchJson("/plugins/batch-delete", {
      method: "POST",
      body: JSON.stringify({ pluginIds }),
    }),
  smokePlugin: (id: string, keyword?: string): Promise<any> =>
    fetchJson(`/plugins/${id}/smoke`, {
      method: "POST",
      body: JSON.stringify({ mode: "fixture", keyword: keyword || "凡人修仙传" }),
    }),
  pingPlugin: (id: string): Promise<any> =>
    fetchJson(`/plugins/${id}/ping`, { method: "POST" }),
  pingAllPlugins: (pluginIds?: string[]): Promise<any> =>
    fetchJson("/plugins/ping", { method: "POST", body: JSON.stringify({ pluginIds }) }),
  testSource: (id: string, payload: Record<string, any>): Promise<any> =>
    fetchJson(`/sources/${id}/test`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  pluginAuth: (id: string): Promise<any> => fetchJson(`/plugins/${id}/auth`),
  pluginLogin: (id: string): Promise<any> => fetchJson(`/plugins/${id}/login`, { method: "POST" }),
  pluginAuthCheck: (id: string): Promise<any> => fetchJson(`/plugins/${id}/auth/check`, { method: "POST" }),
  pluginCookiesClear: (id: string): Promise<any> => fetchJson(`/plugins/${id}/cookies/clear`, { method: "POST" }),
  startLoginBrowser: (id: string): Promise<any> => fetchJson(`/plugins/${id}/login-browser`, { method: "POST" }),
  getLoginBrowserStatus: (id: string): Promise<any> => fetchJson(`/plugins/${id}/login-browser/status`),
  cancelLoginBrowser: (id: string): Promise<any> => fetch(`${API_BASE}/plugins/${id}/login-browser`, { method: "DELETE" }).then((r) => r.json()),

  // Official source login (generic protocol)
  loginCapabilities: (pluginId: string): Promise<any> =>
    fetchJson(`/official-sources/${pluginId}/login-capabilities`),
  loginPhoneRequestCode: (pluginId: string, payload: Record<string, any>): Promise<any> =>
    fetchJson(`/official-sources/${pluginId}/login/phone/request-code`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  loginPhoneVerify: (pluginId: string, payload: Record<string, any>): Promise<any> =>
    fetchJson(`/official-sources/${pluginId}/login/phone/verify`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  loginCookieVerify: (pluginId: string, payload: Record<string, any>): Promise<any> =>
    fetchJson(`/official-sources/${pluginId}/login/cookie/verify`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  loginLogout: (pluginId: string): Promise<any> =>
    fetchJson(`/official-sources/${pluginId}/login/logout`, { method: "POST" }),

  officialSources: (): Promise<any> => fetchJson("/official-sources"),
  createSearchJob: (payload: {
    keyword: string
    page?: number
    limit?: number
    sourceIds?: string[]
  }): Promise<any> =>
    fetchJson("/search-jobs", {
      method: "POST",
      body: JSON.stringify({
        keyword: payload.keyword,
        page: payload.page || 1,
        limit: payload.limit,
        sourceIds: payload.sourceIds,
      }),
    }),
  createAggregateSearch: (payload: {
    keyword: string
    page?: number
    limit?: number
    sourceIds?: string[]
  }): Promise<any> =>
    fetchJson("/search/aggregate", {
      method: "POST",
      body: JSON.stringify({
        keyword: payload.keyword,
        page: payload.page || 1,
        limit: payload.limit,
        sourceIds: payload.sourceIds,
      }),
    }),
  searchJobs: (): Promise<any> => fetchJson("/search-jobs?limit=20"),
  searchJob: (id: string): Promise<any> => fetchJson(`/search-jobs/${id}`),
  searchJobEvents: (id: string, after?: number): Promise<any> =>
    fetchJson(`/search-jobs/${id}/events?after=${after || 0}`),
  searchJobCandidates: (id: string): Promise<any> => fetchJson(`/search-jobs/${id}/candidates`),
  verifySearchCandidate: (
    jobId: string,
    candidateId: string,
    chapterIndex?: number,
    includeReviews: boolean = true
  ): Promise<any> =>
    fetchJson(`/search-jobs/${jobId}/candidates/${candidateId}/verify`, {
      method: "POST",
      body: JSON.stringify({ chapterIndex: chapterIndex || 0, includeReviews }),
    }),
  fetchCandidateReviews: (jobId: string, candidateId: string, chapterIndex?: number): Promise<any> =>
    fetchJson(`/search-jobs/${jobId}/candidates/${candidateId}/reviews`, {
      method: "POST",
      body: JSON.stringify({ chapterIndex: chapterIndex || 0, timeout: 120 }),
    }),
  cancelSearchJob: (id: string): Promise<any> =>
    fetchJson(`/search-jobs/${id}/cancel`, { method: "POST" }),
  liveCheckPlugin: (id: string, keyword?: string): Promise<any> =>
    fetchJson(`/plugins/${id}/live-check`, {
      method: "POST",
      body: JSON.stringify({ keyword: keyword || "凡人修仙传" }),
    }),
  pluginLiveChecks: (id: string): Promise<any> => fetchJson(`/plugins/${id}/live-checks`),
  pluginAttempts: (id: string): Promise<any> => fetchJson(`/plugins/${id}/attempts`),
  cache: (): Promise<any> => fetchJson("/cache"),
  cacheItems: (): Promise<any> => fetchJson("/cache/items?limit=100"),
  clearCache: (): Promise<any> => fetchJson("/cache", { method: "DELETE" }),
  clearCacheByType: (type: "all" | "search" | "book" | "toc" | "chapter"): Promise<any> =>
    fetchJson("/cache/clear", {
      method: "POST",
      body: JSON.stringify({ type }),
    }),

  settings: (): Promise<any> => fetchJson("/settings"),
  updateSettings: (payload: Record<string, any>): Promise<any> =>
    fetchJson("/settings", { method: "POST", body: JSON.stringify(payload) }),

  aggregateSource: (): Promise<any> => fetchJson("/aggregate-source"),
  regenerateAggregateSource: (): Promise<any> =>
    fetchJson("/aggregate-source/regenerate", { method: "POST" }),

  verification: (): Promise<any> => fetchJson("/verification"),
  runVerification: (): Promise<any> => fetchJson("/verification/run", { method: "POST" }),
  exploreGroups: (id: string): Promise<any> => fetchJson(`/explore/sources/${id}/groups`),
  exploreItems: (id: string, payload: Record<string, any>): Promise<any> =>
    fetchJson(`/explore/sources/${id}/items`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),

  // Aggregate AI source
  aggregateSettings: (): Promise<any> => fetchJson("/aggregate-settings"),
  updateAggregateSettings: (payload: Record<string, any>): Promise<any> =>
    fetchJson("/aggregate-settings", { method: "POST", body: JSON.stringify(payload) }),
  testAggregateProvider: (payload: Record<string, any>): Promise<any> =>
    fetchJson("/aggregate-settings/test-provider", { method: "POST", body: JSON.stringify(payload) }),
  fetchAggregateModels: (payload: Record<string, any>): Promise<any> =>
    fetchJson("/aggregate-settings/fetch-models", { method: "POST", body: JSON.stringify(payload) }),
  aggregateBooks: (params: Record<string, string>): Promise<any> => {
    const qs = new URLSearchParams(params)
    return fetchJson(`/aggregate-books?${qs}`)
  },
  aggregateBook: (bookId: string): Promise<any> => fetchJson(`/aggregate-books/${bookId}`),
  aggregateBookChapters: (bookId: string, params: Record<string, string>): Promise<any> => {
    const qs = new URLSearchParams(params)
    return fetchJson(`/aggregate-books/${bookId}/chapters?${qs}`)
  },
  aggregateChapter: (bookId: string, chapterId: string): Promise<any> =>
    fetchJson(`/aggregate-books/${bookId}/chapters/${chapterId}`),
  aggregateChapterReviews: (bookId: string, chapterId: string): Promise<any> =>
    fetchJson(`/aggregate-books/${bookId}/chapters/${chapterId}/reviews`),
  retryAggregateChapter: (bookId: string, chapterId: string): Promise<any> =>
    fetchJson(`/aggregate-books/${bookId}/chapters/${chapterId}/retry`, { method: "POST" }),
  runAggregateBook: (bookId: string): Promise<any> =>
    fetchJson(`/aggregate-books/${bookId}/run`, { method: "POST" }),
  pauseAggregateBook: (bookId: string): Promise<any> =>
    fetchJson(`/aggregate-books/${bookId}/pause`, { method: "POST" }),
  resumeAggregateBook: (bookId: string): Promise<any> =>
    fetchJson(`/aggregate-books/${bookId}/resume`, { method: "POST" }),
  deleteAggregateBook: (bookId: string): Promise<any> =>
    fetchJson(`/aggregate-books/${bookId}`, { method: "DELETE" }),
}
