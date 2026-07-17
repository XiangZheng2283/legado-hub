import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { executeLibraryBookMaintenanceAction } from "@/lib/library-actions"
import { LibraryBookDetailPage } from "./LibraryBookDetailPage"

const authState = vi.hoisted(() => ({ role: "admin" as "admin" | "user" }))

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { userId: "user-1", username: "tester", role: authState.role } }),
}))

vi.mock("@/components/shared/LogStream", () => ({ LogStream: () => <div>日志流</div> }))

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
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/console/library/book-1"]}>
        <Routes>
          <Route path="/console/library/:bookId" element={<LibraryBookDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("LibraryBookDetailPage processing settings", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authState.role = "admin"
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
    })
    ;(api.subscribe.chapters as any).mockResolvedValue({ items: [], total: 0, pageSize: 200 })
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

  it("rejects an unknown maintenance action without rebuilding", () => {
    expect(() => executeLibraryBookMaintenanceAction("book-1", "unexpected")).toThrow("不支持的维护操作")
    expect(api.rebuildLibraryBook).not.toHaveBeenCalled()
  })
})
