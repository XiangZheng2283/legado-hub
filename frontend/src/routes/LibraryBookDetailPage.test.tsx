import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
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
    subscribe: {
      book: vi.fn(),
      chapters: vi.fn(),
      updateSubscription: vi.fn(),
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
    ;(api.deleteLibraryBook as any).mockResolvedValue({ deleted: true })
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
      totalChapters: 10,
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
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["library", "admin"], refetchType: "none" })
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

  it("rejects an unknown maintenance action without rebuilding", () => {
    expect(() => executeLibraryBookMaintenanceAction("book-1", "unexpected")).toThrow("不支持的维护操作")
    expect(api.rebuildLibraryBook).not.toHaveBeenCalled()
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
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["library"], refetchType: "none" })
    })
    confirmDelete.mockRestore()
  })
})
