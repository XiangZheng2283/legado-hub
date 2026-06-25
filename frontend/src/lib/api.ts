const API_BASE = "/api/console"

async function fetchRaw(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...options,
  })
}

async function fetchJson(path: string, options?: RequestInit): Promise<any> {
  const res = await fetchRaw(path, options)
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    throw new Error(`HTTP ${res.status}: ${res.statusText}${text ? " - " + text : ""}`)
  }
  return res.json()
}

async function fetchApiRaw(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...options,
  })
}

async function fetchApiJson(path: string, options?: RequestInit): Promise<any> {
  const res = await fetchApiRaw(path, options)
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    throw new Error(`HTTP ${res.status}: ${res.statusText}${text ? " - " + text : ""}`)
  }
  if (res.status === 204) return null
  return res.json()
}

function normalizeLibraryBook(raw: any): any {
  if (!raw || typeof raw !== "object") return raw
  return {
    ...raw,
    id: raw.aggregateBookId ?? raw.id,
    displayName: raw.displayName ?? raw.name ?? raw.canonicalName ?? "",
    displayAuthor: raw.displayAuthor ?? raw.author ?? raw.canonicalAuthor ?? "",
    lastChapterTitle: raw.lastChapterTitle ?? raw.lastSourceChapterTitle ?? raw.lastLocalChapterTitle ?? "",
    lastCheckedAt: raw.lastCheckedAt ?? raw.lastCheckTime ?? "",
  }
}

function normalizeLibraryList(data: any): any {
  return {
    ...data,
    items: (data?.items || []).map(normalizeLibraryBook),
  }
}

function normalizeLibraryDetail(data: any): any {
  const book = normalizeLibraryBook(data?.book ?? data)
  return {
    ...data,
    ...book,
    book,
  }
}

function normalizeChapterList(data: any): any {
  const chapters = data?.chapters || data?.items || []
  return {
    ...data,
    chapters,
    items: data?.items || chapters,
  }
}

function normalizeSearchCards(data: any): any {
  return {
    ...data,
    cards: (data?.cards || []).map((card: any) => ({
      ...card,
      status: card.status ?? "completed",
      alreadyIngested: card.alreadyIngested ?? card.alreadyInLibrary ?? false,
      addedBy: card.addedBy ?? card.addedByUsername ?? "",
      sourceSummaryText: Array.isArray(card.sourceSummary)
        ? card.sourceSummary.map((source: any) => source.sourceName || source.sourceId).filter(Boolean).join(" / ")
        : card.sourceSummary ?? "",
    })),
  }
}

export const api = {
  status: (): Promise<any> => fetch("/api/console/status", { credentials: "include" }).then((r) => r.json()),

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
  cancelLoginBrowser: (id: string): Promise<any> =>
    fetch(`${API_BASE}/plugins/${id}/login-browser`, { method: "DELETE", credentials: "include" }).then((r) => r.json()),

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

  // Auth (session cookie based)
  auth: {
    me: (): Promise<any> => fetchApiJson("/auth/me"),
    bootstrap: (payload: { username: string; password: string }): Promise<any> =>
      fetchApiJson("/auth/bootstrap", { method: "POST", body: JSON.stringify(payload) }),
    login: (payload: { username: string; password: string }): Promise<any> =>
      fetchApiJson("/auth/login", { method: "POST", body: JSON.stringify(payload) }),
    changePassword: (payload: { currentPassword: string; newPassword: string }): Promise<any> =>
      fetchApiJson("/auth/change-password", { method: "POST", body: JSON.stringify(payload) }),
    logout: (): Promise<any> => fetchApiJson("/auth/logout", { method: "POST" }),
  },

  // Subscription discovery (shared library)
  subscribe: {
    search: (payload: { keyword: string; page?: number }): Promise<any> =>
      fetchApiJson("/subscribe/search", { method: "POST", body: JSON.stringify(payload) }).then(normalizeSearchCards),
    searchJob: (jobId: string): Promise<any> =>
      fetchApiJson(`/subscribe/search/${jobId}`).then(normalizeSearchCards),
    subscribeCard: (
      jobId: string,
      candidateId: string,
      payload: { startChapterIndex?: number; autoArchiveOnComplete?: boolean }
    ): Promise<any> =>
      fetchApiJson(`/subscribe/search/${jobId}/cards/${candidateId}/subscribe`, {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    library: (): Promise<any> => fetchApiJson("/subscribe/library").then(normalizeLibraryList),
    myLibrary: (): Promise<any> => fetchApiJson("/subscribe/library/mine").then(normalizeLibraryList),
    book: (aggregateBookId: string): Promise<any> =>
      fetchApiJson(`/subscribe/books/${aggregateBookId}`).then(normalizeLibraryDetail),
    chapters: (aggregateBookId: string): Promise<any> =>
      fetchApiJson(`/subscribe/books/${aggregateBookId}/chapters`).then(normalizeChapterList),
  },

  // Admin shared library management
  libraryBooks: (params?: Record<string, string>): Promise<any> => {
    const qs = params ? `?${new URLSearchParams(params)}` : ""
    return fetchJson(`/library-books${qs}`).then(normalizeLibraryList)
  },
  libraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}`).then(normalizeLibraryDetail),
  libraryBookChapters: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/chapters`).then(normalizeChapterList),
  pauseLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/pause`, { method: "POST" }),
  resumeLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/resume`, { method: "POST" }),
  archiveLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/archive`, { method: "POST" }),
  deleteLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}`, { method: "DELETE" }),
  updateLibraryBookSettings: (bookId: string, payload: Record<string, any>): Promise<any> =>
    fetchJson(`/library-books/${bookId}/settings`, { method: "POST", body: JSON.stringify(payload) }),
  rebuildLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/rebuild`, { method: "POST" }),
  libraryBookProcessingLogs: (bookId: string, limit = 50, offset = 0): Promise<any> =>
    fetchJson(`/library-books/${bookId}/processing-logs?limit=${limit}&offset=${offset}`),

  // Admin users
  users: (): Promise<any> => fetchJson("/users"),
  createUser: (payload: Record<string, any>): Promise<any> =>
    fetchJson("/users", { method: "POST", body: JSON.stringify(payload) }),
  resetUserPassword: (userId: string, payload: Record<string, any>): Promise<any> =>
    fetchJson(`/users/${userId}/reset-password`, { method: "POST", body: JSON.stringify(payload) }),
  disableUser: (userId: string, disabled: boolean): Promise<any> =>
    fetchJson(`/users/${userId}/disable`, { method: "POST", body: JSON.stringify({ disabled }) }),
}
