import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { executeLibraryBookMaintenanceAction } from "@/lib/library-actions"
import { LibraryBookDetailPage } from "./LibraryBookDetailPage"

const authState = vi.hoisted(() => ({ role: "admin" as "admin" | "user" }))
const logStreamState = vi.hoisted(() => ({ onRecord: undefined as undefined | (() => void) }))

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { userId: "user-1", username: "tester", role: authState.role } }),
}))

vi.mock("@/components/shared/LogStream", () => ({
  LogStream: ({ onRecord }: { onRecord?: () => void }) => {
    logStreamState.onRecord = onRecord
    return <div>日志流</div>
  },
}))

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    libraryBookSummary: vi.fn(),
    libraryBookChapters: vi.fn(),
    updateLibraryBookSettings: vi.fn(),
    checkLibraryBookUpdate: vi.fn(),
    refreshLibraryBookSources: vi.fn(),
    repairLibraryBook: vi.fn(),
    rebuildLibraryBook: vi.fn(),
    processLibraryBookChapter: vi.fn(),
    deleteLibraryBook: vi.fn(),
    chapter: vi.fn(),
    streamLibraryBookLogsUrl: vi.fn(() => "/logs"),
    reading: {
      chapterReviews: vi.fn(),
      chapterReviewsViewUrl: vi.fn((chapterId: string, tab: string, paragraphIds: number[] = []) => {
        const params = new URLSearchParams({ tab })
        if (paragraphIds.length > 0) params.set("paragraphIds", paragraphIds.join(","))
        return `/api/legado/chapter/${encodeURIComponent(chapterId)}/reviews/view?${params}`
      }),
    },
    subscribe: {
      book: vi.fn(),
      chapters: vi.fn(),
      updateSubscription: vi.fn(),
      removeSubscription: vi.fn(),
      chapter: vi.fn(),
    },
  },
}))

const adminBook = {
  found: true,
  aggregateBookId: "book-1",
  displayName: "测试书籍",
  displayAuthor: "作者",
  totalChapters: 10,
  processedChapters: 2,
  visibleProcessedChapters: 2,
  failedChapters: 0,
  status: "active",
  bookStatus: "ongoing",
  processingSettings: { updateIntervalMinutes: 60, backlogChapterLimit: 25 },
  sourceMapSummary: [],
  bookState: {},
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const view = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/console/library/book-1"]}>
        <Routes>
          <Route path="/console/library/:bookId" element={<LibraryBookDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, queryClient }
}

describe("LibraryBookDetailPage processing settings", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.role = "admin"
    logStreamState.onRecord = undefined
    ;(api.libraryBookSummary as any).mockResolvedValue(adminBook)
    ;(api.libraryBookChapters as any).mockResolvedValue({ items: [], total: 0, pageSize: 200 })
    ;(api.updateLibraryBookSettings as any).mockResolvedValue({
      bookId: "book-1",
      settings: { updateIntervalMinutes: 120, backlogChapterLimit: 40 },
      currentPolicyVersion: 1,
      intervalMinutes: 120,
      updated: true,
    })
    ;(api.subscribe.book as any).mockResolvedValue({
      ...adminBook,
      subscription: { status: "active", startChapterIndex: 1, autoArchiveOnComplete: true },
      personalProgress: { fullCount: 2, previewCount: 0, failedCount: 0, pendingCount: 8, coverageRatio: 0.2 },
      provisioning: {
        state: "processing",
        readableChapterCount: 0,
        previewChapterCount: 0,
        pendingChapterCount: 8,
        firstReadableChapter: null,
      },
    })
    ;(api.subscribe.chapters as any).mockResolvedValue({ items: [], total: 0, pageSize: 200 })
    ;(api.reading.chapterReviews as any).mockResolvedValue({
      chapterEnd: [],
      chapterEndHot: [],
      authorReviews: [],
      hotParagraphReviews: [],
      summary: { totalReviews: 0, chapterEndCount: 0 },
    })
    ;(api.deleteLibraryBook as any).mockResolvedValue({ deleted: true })
    ;(api.subscribe.removeSubscription as any).mockResolvedValue({ aggregateBookId: "book-1", deleted: true })
    ;(api.checkLibraryBookUpdate as any).mockResolvedValue({ ok: true })
    ;(api.refreshLibraryBookSources as any).mockResolvedValue({ ok: true })
    ;(api.repairLibraryBook as any).mockResolvedValue({ ok: true })
    ;(api.rebuildLibraryBook as any).mockResolvedValue({ ok: true })
  })

  it("lets administrators update the shared processing cadence", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("button", { name: "处理设置" }))
    const interval = screen.getByLabelText("更新检查间隔（分钟）")
    const backlog = screen.getByLabelText("单轮积压章节上限")
    expect(interval).toHaveValue(60)
    expect(backlog).toHaveValue(25)
    await user.clear(interval)
    await user.type(interval, "120")
    await user.clear(backlog)
    await user.type(backlog, "40")
    await user.click(screen.getByRole("button", { name: "保存" }))

    await waitFor(() => expect(api.updateLibraryBookSettings).toHaveBeenCalledWith("book-1", {
      updateIntervalMinutes: 120,
      backlogChapterLimit: 40,
    }))
  })

  it("keeps shared processing controls hidden from ordinary users", async () => {
    authState.role = "user"
    renderPage()

    await screen.findByText("测试书籍")
    expect(screen.queryByRole("button", { name: "处理设置" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "订阅设置" })).toBeInTheDocument()
    expect(screen.getByText("等待首章")).toBeInTheDocument()
    expect(screen.getByRole("progressbar", { name: "当前章节全文覆盖" })).toHaveAttribute("aria-valuenow", "20")
    expect(screen.getByText("全文 2 · 预览 0 · 待处理 8 · 失败 0")).toBeInTheDocument()
  })

  it("excludes preview chapters from full-text coverage and keeps ongoing tracking explicit", async () => {
    ;(api.libraryBookSummary as any).mockResolvedValueOnce({
      ...adminBook,
      totalChapters: 8,
      processedChapters: 10,
      visibleProcessedChapters: 8,
      bookState: {
        chapterCount: 10,
        processedChapterCount: 10,
        readableChapterCount: 8,
        previewChapterCount: 2,
        failedChapterCount: 0,
      },
    })
    renderPage()

    await screen.findByText("测试书籍")
    expect(screen.getByText("8 / 10 章 (80%)")).toBeInTheDocument()
    expect(screen.getByRole("progressbar", { name: "当前章节全文覆盖" })).toHaveAttribute("aria-valuenow", "80")
    expect(screen.getByText("全文 8 · 预览 2 · 待处理 0 · 失败 0")).toBeInTheDocument()
    expect(screen.getByText("当前章节已同步 · 持续追更")).toBeInTheDocument()
  })

  it("shows candidate chapter counts without a misleading status column", async () => {
    ;(api.libraryBookSummary as any).mockResolvedValueOnce({
      ...adminBook,
      sourceMapSummary: [
        {
          sourceId: "qidian_com_web",
          sourceName: "起点中文网(Web)",
          score: 221,
          lastChapter: "第九百九十九章 关底boss",
          chapterCount: 1195,
          bookStatus: "",
        },
      ],
    })
    renderPage()

    const boundary = await screen.findByTestId("candidate-sources-table-boundary")
    expect(within(boundary).getByRole("columnheader", { name: "来源" })).toBeInTheDocument()
    expect(within(boundary).getByRole("columnheader", { name: "章节数" })).toBeInTheDocument()
    expect(within(boundary).queryByRole("columnheader", { name: "状态" })).not.toBeInTheDocument()
    expect(within(boundary).getByText("1195章")).toBeInTheDocument()
  })

  it("refetches the book summary from the load error", async () => {
    const user = userEvent.setup()
    ;(api.libraryBookSummary as any)
      .mockRejectedValueOnce(new Error("书籍摘要不可用"))
      .mockResolvedValueOnce(adminBook)
    renderPage()

    expect(await screen.findByText(/书籍摘要不可用/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(api.libraryBookSummary).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("测试书籍")).toBeInTheDocument()
  })

  it("refetches the chapter list without reloading the page", async () => {
    const user = userEvent.setup()
    ;(api.libraryBookChapters as any)
      .mockRejectedValueOnce(new Error("章节列表不可用"))
      .mockResolvedValueOnce({ items: [], total: 0, pageSize: 200 })
    renderPage()

    expect(await screen.findByText("章节列表不可用")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试章节列表" }))

    await waitFor(() => expect(api.libraryBookChapters).toHaveBeenCalledTimes(2))
  })

  it("invalidates live detail data when an SSE record arrives", async () => {
    const { queryClient } = renderPage()
    await screen.findByText("测试书籍")
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries")
    vi.useFakeTimers()
    try {
      act(() => {
        logStreamState.onRecord?.()
        logStreamState.onRecord?.()
        logStreamState.onRecord?.()
      })
      expect(invalidateQueries).not.toHaveBeenCalled()

      await act(async () => { await vi.advanceTimersByTimeAsync(1000) })

      expect(invalidateQueries).toHaveBeenCalledTimes(2)
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["library", "book", "book-1"] })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["library", "admin"] })
    } finally {
      vi.useRealTimers()
    }
  })

  it("polls summary and chapters for ordinary users", async () => {
    authState.role = "user"
    vi.useFakeTimers()
    const view = renderPage()
    try {
      await vi.waitFor(() => {
        expect(api.subscribe.book).toHaveBeenCalledTimes(1)
        expect(api.subscribe.chapters).toHaveBeenCalledTimes(1)
      })
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      await vi.waitFor(() => {
        expect(api.subscribe.book).toHaveBeenCalledTimes(2)
        expect(api.subscribe.chapters).toHaveBeenCalledTimes(2)
      })
    } finally {
      view.unmount()
      vi.useRealTimers()
    }
  })

  it("pages chapter content and opens plugin-backed review views", async () => {
    const user = userEvent.setup()
    const readChapterId = "legadohub_ai_aggregate:chapter-test"
    ;(api.libraryBookChapters as any).mockResolvedValue({
      items: [{
        chapterId: "chapter-test",
        chapterIndex: 1,
        title: "第一章 可读章节",
        status: "readable",
        hasContent: true,
        contentLength: 3600,
        readChapterId,
      }],
      total: 1,
      pageSize: 200,
    })
    ;(api.chapter as any).mockResolvedValue({
      content: Array.from({ length: 36 }, (_, index) => `这是用于模拟翻页阅读的第 ${index + 1} 个正文段落，包含足够的文本来覆盖多个阅读页面。`).join("\n"),
    })
    ;(api.reading.chapterReviews as any).mockResolvedValue({
      chapterEnd: [
        { id: "chapter-hot-1", userName: "书友甲", content: "第一条章末热评" },
        { id: "chapter-review", userName: "书友丁", content: "普通章末评论" },
      ],
      chapterEndHot: [
        { id: "chapter-hot-1", userName: "书友甲", content: "第一条章末热评" },
        { id: "chapter-hot-2", userName: "书友乙", content: "第二条章末热评" },
        { id: "chapter-hot-3", userName: "书友丙", content: "第三条章末热评" },
        { id: "chapter-hot-4", userName: "书友丁", content: "不应显示的第四条热评" },
      ],
      authorReviews: [{ id: "author-review", userName: "作者甲", content: "这是作者留在章末的补充" }],
      hotParagraphReviews: [{
        paragraphId: 2,
        matchedText: "用于模拟翻页阅读",
        matchedParagraphIndex: 12,
        matchedParagraphCount: 1,
        commentCount: 4,
      }, {
        paragraphId: 3,
        matchedText: "这是用于模拟翻页阅读的第 25 个正文段落，包含足够的文本来覆盖多个阅读页面。",
        matchedParagraphCount: 1,
        commentCount: 6,
      }, {
        paragraphId: 4,
        matchedText: "用于模拟翻页阅读",
        matchedParagraphCount: 1,
        commentCount: 8,
      }],
      summary: { totalReviews: 18, chapterEndCount: 13 },
    })

    const clientWidthSpy = vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(600)
    const scrollWidthSpy = vi.spyOn(Element.prototype, "scrollWidth", "get").mockReturnValue(1848)
    const clientRectsSpy = vi.spyOn(Element.prototype, "getClientRects").mockImplementation(function (this: Element) {
      const value = Number((this as HTMLElement).dataset?.paragraphIndex)
      if (!Number.isInteger(value)) return { length: 0, item: () => null } as unknown as DOMRectList
      const page = Math.floor(value / 12)
      const transform = (this.parentElement as HTMLElement | null)?.style.transform || ""
      const translated = Number(transform.match(/translate3d\((-?[\d.]+)px/)?.[1] || 0)
      const left = page * 632 + translated
      const rect = { left, right: left + 580, top: 0, bottom: 40, width: 580, height: 40, x: left, y: 0, toJSON: () => ({}) } as DOMRect
      return { 0: rect, length: 1, item: (index: number) => index === 0 ? rect : null } as unknown as DOMRectList
    })

    try {
      renderPage()
      await user.click(await screen.findByText("第一章 可读章节"))

      await waitFor(() => {
        expect(screen.getByTestId("chapter-reader-columns")).toHaveStyle({ width: "600px" })
        expect(screen.getByTestId("chapter-reader-columns").scrollWidth).toBe(1848)
      })

      await waitFor(() => {
        expect(api.chapter).toHaveBeenCalledWith(readChapterId)
        expect(api.reading.chapterReviews).toHaveBeenCalledWith(readChapterId)
        expect(screen.getByTestId("chapter-reader-page-indicator")).toHaveTextContent("1 / 3")
      })
      expect(screen.getByTestId("chapter-author-say")).toHaveTextContent("作者甲")
      expect(screen.getByTestId("chapter-author-say")).toHaveTextContent("这是作者留在章末的补充")
      expect(screen.getByText("第一条章末热评")).toBeInTheDocument()
      expect(screen.getByText("第二条章末热评")).toBeInTheDocument()
      expect(screen.getByText("第三条章末热评")).toBeInTheDocument()
      expect(screen.queryByText("不应显示的第四条热评")).not.toBeInTheDocument()

      const previousPage = screen.getByRole("button", { name: "上一页" })
      const nextPage = screen.getByRole("button", { name: "下一页" })
      expect(screen.getByRole("button", { name: "页热评 0 条" })).toBeDisabled()
      expect(previousPage).toBeDisabled()
      expect(nextPage).toBeEnabled()

      await user.click(nextPage)
      expect(screen.getByTestId("chapter-reader-page-indicator")).toHaveTextContent("2 / 3")
      expect(previousPage).toBeEnabled()

      await waitFor(() => expect(screen.getByRole("button", { name: "页热评 4 条" })).toBeEnabled())
      await user.click(screen.getByRole("button", { name: "页热评 4 条" }))
      expect(screen.getByTitle("页热评")).toHaveAttribute(
        "src",
        `/api/legado/chapter/${encodeURIComponent(readChapterId)}/reviews/view?tab=paragraph&paragraphIds=2`,
      )
      await user.click(screen.getByRole("button", { name: "关闭评论" }))

      await user.click(nextPage)
      expect(screen.getByTestId("chapter-reader-page-indicator")).toHaveTextContent("3 / 3")
      expect(nextPage).toBeDisabled()
      await waitFor(() => expect(screen.getByRole("button", { name: "页热评 6 条" })).toBeEnabled())

      await user.click(screen.getByRole("button", { name: "本章说 13 条评论" }))
      expect(screen.getByTitle("本章评论")).toHaveAttribute(
        "src",
        `/api/legado/chapter/${encodeURIComponent(readChapterId)}/reviews/view?tab=chapter`,
      )
    } finally {
      clientWidthSpy.mockRestore()
      scrollWidthSpy.mockRestore()
      clientRectsSpy.mockRestore()
    }
  })

  it("rejects an unknown maintenance action without rebuilding", () => {
    expect(() => executeLibraryBookMaintenanceAction("book-1", "unexpected")).toThrow("不支持的维护操作")
    expect(api.rebuildLibraryBook).not.toHaveBeenCalled()
  })

  it("shows clear feedback after refreshing the source map", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("button", { name: "更多维护操作" }))
    await user.click(screen.getByRole("button", { name: "刷新源映射" }))

    await waitFor(() => expect(api.refreshLibraryBookSources).toHaveBeenCalledWith("book-1", { force: true }))
    expect(await screen.findByText("源映射已刷新，页面数据已更新。")).toBeInTheDocument()
  })

  it("lets an ordinary user remove their own subscription", async () => {
    authState.role = "user"
    const user = userEvent.setup()
    const confirmRemove = vi.spyOn(window, "confirm").mockReturnValue(true)
    renderPage()

    await user.click(await screen.findByRole("button", { name: "移除订阅" }))

    await waitFor(() => expect(api.subscribe.removeSubscription).toHaveBeenCalledWith("book-1"))
    expect(api.deleteLibraryBook).not.toHaveBeenCalled()
    confirmRemove.mockRestore()
  })

  it("clears detail state and invalidates the library after deletion", async () => {
    const user = userEvent.setup()
    const confirmDelete = vi.spyOn(window, "confirm").mockReturnValue(true)
    const { queryClient } = renderPage()
    const removeQueries = vi.spyOn(queryClient, "removeQueries")
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries")

    await user.click(await screen.findByRole("button", { name: "更多维护操作" }))
    await user.click(screen.getByRole("button", { name: "删除书籍" }))

    await waitFor(() => {
      expect(api.deleteLibraryBook).toHaveBeenCalledWith("book-1")
      expect(removeQueries).toHaveBeenCalledWith({ queryKey: ["library", "book", "book-1"] })
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["library"] })
    })
    confirmDelete.mockRestore()
  })
})
