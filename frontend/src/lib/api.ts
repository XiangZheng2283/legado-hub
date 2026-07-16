const API_BASE = "/api/console"

export interface ApiErrorDetail {
  code?: string
  message?: string
  retryable?: boolean
  [key: string]: unknown
}

export class ApiError extends Error {
  readonly status: number
  readonly detail: ApiErrorDetail

  constructor(
    status: number,
    detail: ApiErrorDetail,
  ) {
    super(detail.message || `请求失败（${status}）`)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

async function fetchRaw(path: string, options?: RequestInit): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...options,
  })
}

async function responseError(res: Response): Promise<Error> {
  const payload = await res.json().catch(() => null)
  const detail = payload?.detail ?? payload?.message ?? payload?.error
  if (detail && typeof detail === "object") {
    return new ApiError(res.status, detail as ApiErrorDetail)
  }
  return new ApiError(res.status, {
    message: typeof detail === "string" && detail.trim() ? detail : `请求失败（${res.status}）`,
  })
}

async function fetchJson(path: string, options?: RequestInit): Promise<any> {
  const res = await fetchRaw(path, options)
  if (!res.ok) throw await responseError(res)
  if (res.status === 204) return null
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
  if (!res.ok) throw await responseError(res)
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
  const rawChapters = Array.isArray(data?.items) && data.items.length > 0
    ? data.items
    : Array.isArray(data?.chapters)
      ? data.chapters
      : []
  const chapters = rawChapters.map((chapter: any) => ({
    ...chapter,
    id: chapter?.chapterId ?? chapter?.id,
    readChapterId: chapter?.readChapterId ?? "",
    chapterId: chapter?.chapterId ?? chapter?.id,
  }))
  return {
    ...data,
    chapters,
    items: chapters,
  }
}

function normalizeSearchCards(data: any): any {
  return {
    ...data,
    cards: (data?.cards || []).map((card: any) => ({
      ...card,
      status: card.status ?? "unknown",
      alreadyIngested: card.alreadyIngested ?? card.alreadyInLibrary ?? false,
      sourceSummaryText: Array.isArray(card.sourceSummary)
        ? card.sourceSummary.map((source: any) => source.sourceName || source.sourceId).filter(Boolean).join(" / ")
        : card.sourceSummary ?? "",
    })),
  }
}

export const api = {
  status: (): Promise<any> => fetchJson("/status"),

  plugins: (): Promise<any> => fetchJson("/plugins"),
  plugin: (id: string): Promise<any> => fetchJson(`/plugins/${id}`),
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
  smokePlugin: (id: string, keyword?: string): Promise<any> =>
    fetchJson(`/plugins/${id}/smoke`, {
      method: "POST",
      body: JSON.stringify({ mode: "fixture", keyword: keyword || "凡人修仙传" }),
    }),
  pingAllPlugins: (pluginIds?: string[]): Promise<any> =>
    fetchJson("/plugins/ping", { method: "POST", body: JSON.stringify({ pluginIds }) }),
  pluginAuthCheck: (id: string): Promise<any> => fetchJson(`/plugins/${id}/auth/check`, { method: "POST" }),
  pluginCookiesClear: (id: string): Promise<any> => fetchJson(`/plugins/${id}/cookies/clear`, { method: "POST" }),
  startLoginBrowser: (id: string): Promise<any> => fetchJson(`/plugins/${id}/login-browser`, { method: "POST" }),
  getLoginBrowserStatus: (id: string): Promise<any> => fetchJson(`/plugins/${id}/login-browser/status`),
  cancelLoginBrowser: (id: string): Promise<any> =>
    fetchJson(`/plugins/${id}/login-browser`, { method: "DELETE" }),

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
  searchJob: (id: string): Promise<any> => fetchJson(`/search-jobs/${id}`),
  searchJobEvents: (id: string, after?: number): Promise<any> =>
    fetchJson(`/search-jobs/${id}/events?after=${after || 0}`),
  pluginAttempts: (id: string): Promise<any> => fetchJson(`/plugins/${id}/attempts`),

  settings: (): Promise<any> => fetchJson("/settings"),
  updateSettings: (payload: Record<string, any>): Promise<any> =>
    fetchJson("/settings", { method: "POST", body: JSON.stringify(payload) }),

  // Subscription content workflow settings.
  aggregateSettings: (): Promise<any> => fetchJson("/aggregate-settings"),
  updateAggregateSettings: (payload: Record<string, any>): Promise<any> =>
    fetchJson("/aggregate-settings", { method: "POST", body: JSON.stringify(payload) }),

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
    myLibrary: (keyword = ""): Promise<any> => {
      const qs = keyword ? `?${new URLSearchParams({ keyword })}` : ""
      return fetchApiJson(`/subscribe/library/mine${qs}`).then(normalizeLibraryList)
    },
    book: (bookId: string): Promise<any> =>
      fetchApiJson(`/subscribe/books/${bookId}`).then(normalizeLibraryDetail),
    chapters: (bookId: string, params?: Record<string, string>): Promise<any> => {
      const qs = params ? `?${new URLSearchParams(params)}` : ""
      return fetchApiJson(`/subscribe/books/${bookId}/chapters${qs}`).then(normalizeChapterList)
    },
    subscription: (bookId: string): Promise<any> =>
      fetchApiJson(`/subscribe/books/${bookId}/subscription`),
    updateSubscription: (
      bookId: string,
      payload: { status?: "active" | "paused" | "archived"; startChapterIndex?: number; autoArchiveOnComplete?: boolean },
    ): Promise<any> =>
      fetchApiJson(`/subscribe/books/${bookId}/subscription`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      }),
    chapter: (chapterId: string): Promise<any> =>
      fetchApiJson(`/subscribe/chapters/${encodeURIComponent(chapterId)}`),
  },

  // Admin shared library management
  libraryBooks: (params?: Record<string, string>): Promise<any> => {
    const qs = params ? `?${new URLSearchParams(params)}` : ""
    return fetchJson(`/library-books${qs}`).then(normalizeLibraryList)
  },
  libraryBookSummary: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}`).then(normalizeLibraryDetail),
  libraryBookChapters: (bookId: string, params?: Record<string, string>): Promise<any> => {
    const qs = params ? `?${new URLSearchParams(params)}` : ""
    return fetchJson(`/library-books/${bookId}/chapters${qs}`).then(normalizeChapterList)
  },
  libraryBookChapterProgress: (bookId: string, chapterId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/chapters/${chapterId}/progress`),
  processLibraryBookChapter: (bookId: string, chapterId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/chapters/${chapterId}/process`, { method: "POST" }),
  chapter: (chapterId: string): Promise<any> =>
    fetchJson(`/chapter/${encodeURIComponent(chapterId)}`),
  pauseLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/pause`, { method: "POST" }),
  resumeLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/resume`, { method: "POST" }),
  archiveLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/archive`, { method: "POST" }),
  deleteLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}`, { method: "DELETE" }),
  rebuildLibraryBook: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/rebuild`, { method: "POST" }),
  refreshLibraryBookSources: (bookId: string, payload?: Record<string, any>): Promise<any> =>
    fetchJson(`/library-books/${bookId}/source-map/refresh`, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    }),
  repairLibraryBook: (bookId: string, payload?: Record<string, any>): Promise<any> =>
    fetchJson(`/library-books/${bookId}/repair`, {
      method: "POST",
      body: JSON.stringify(payload || {}),
    }),
  checkLibraryBookUpdate: (bookId: string): Promise<any> =>
    fetchJson(`/library-books/${bookId}/update-check`, { method: "POST" }),
  streamLibraryBookLogsUrl: (bookId: string): string =>
    `${window.location.origin}${API_BASE}/library-books/${bookId}/logs/stream`,

  // Sensitive-word lexicon
  lexiconStatus: (): Promise<any> => fetchJson("/lexicon/status"),
  updateLexicon: (): Promise<any> =>
    fetchJson("/lexicon/update", { method: "POST" }),

}
