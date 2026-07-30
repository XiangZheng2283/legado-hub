import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { executeLibraryBookAction } from "@/lib/library-actions"
import { LibraryPage } from "./LibraryPage"

let mockRole: "admin" | "user" = "user"

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { userId: "user-1", username: "reader", role: mockRole } }),
}))

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    subscribe: {
      myLibrary: vi.fn(),
      updateSubscription: vi.fn(),
      removeSubscription: vi.fn(),
    },
    libraryBooks: vi.fn(),
    pauseLibraryBook: vi.fn(),
    resumeLibraryBook: vi.fn(),
    archiveLibraryBook: vi.fn(),
    rebuildLibraryBook: vi.fn(),
    deleteLibraryBook: vi.fn(),
  },
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <LibraryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("LibraryPage user controls", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRole = "user"
    ;(api.subscribe.myLibrary as any).mockResolvedValue({
      items: [{
        aggregateBookId: "book-1",
        displayName: "用户订阅书",
        displayAuthor: "作者",
        totalChapters: 100,
        processedChapters: 100,
        visibleProcessedChapters: 100,
        status: "active",
        bookStatus: "ongoing",
        subscription: { status: "active", startChapterIndex: 20, autoArchiveOnComplete: false },
        personalProgress: { fullCount: 20, previewCount: 5, failedCount: 1, pendingCount: 74, coverageRatio: 0.25 },
      }],
    })
    ;(api.subscribe.updateSubscription as any).mockResolvedValue({ subscription: { status: "paused" } })
    ;(api.subscribe.removeSubscription as any).mockResolvedValue({ aggregateBookId: "book-1", deleted: true })
  })

  it("keeps preview chapters out of personal coverage and pauses only the current user's subscription", async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText("20%")).toBeInTheDocument()
    expect(screen.getByText("全文 20 · 预览 5")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "打开《用户订阅书》操作菜单" }))
    await user.click(screen.getByRole("menuitem", { name: "暂停" }))

    await waitFor(() => expect(api.subscribe.updateSubscription).toHaveBeenCalledWith(
      "book-1",
      { status: "paused" },
    ))
    expect(api.pauseLibraryBook).not.toHaveBeenCalled()
  })

  it("uses readable full chapters instead of processed previews for admin coverage", async () => {
    mockRole = "admin"
    ;(api.libraryBooks as any).mockResolvedValue({
      items: [{
        aggregateBookId: "book-admin",
        displayName: "管理员书库测试书",
        displayAuthor: "作者",
        totalChapters: 100,
        processedChapters: 100,
        visibleProcessedChapters: 80,
        status: "active",
        bookStatus: "ongoing",
        bookState: {
          chapterCount: 100,
          readableChapterCount: 80,
          previewChapterCount: 20,
          failedChapterCount: 0,
        },
      }],
    })

    renderPage()

    expect(await screen.findByText("80%")).toBeInTheDocument()
    expect(screen.getByText("全文 80 · 预览 20")).toBeInTheDocument()
    expect(screen.queryByText("已同步 · 追更中")).not.toBeInTheDocument()
  })

  it("lets an ordinary user remove only their subscription", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("button", { name: "打开《用户订阅书》操作菜单" }))
    await user.click(screen.getByRole("menuitem", { name: "移除订阅" }))
    await user.click(screen.getByRole("button", { name: "确认移除" }))

    await waitFor(() => expect(api.subscribe.removeSubscription).toHaveBeenCalledWith("book-1"))
    expect(api.deleteLibraryBook).not.toHaveBeenCalled()
    expect(await screen.findByText("订阅已移除。")).toBeInTheDocument()
  })

  it("moves archived subscriptions to the completed tab without activity controls", async () => {
    const user = userEvent.setup()
    ;(api.subscribe.myLibrary as any).mockResolvedValue({
      items: [{
        aggregateBookId: "book-completed",
        displayName: "完结归档书",
        displayAuthor: "作者",
        totalChapters: 10,
        processedChapters: 10,
        visibleProcessedChapters: 10,
        status: "archived",
        bookStatus: "completed",
        subscription: { status: "archived", startChapterIndex: 1, autoArchiveOnComplete: true },
        personalProgress: { fullCount: 10, previewCount: 0, failedCount: 0, pendingCount: 0, coverageRatio: 1 },
      }],
    })
    renderPage()

    expect(await screen.findByText("你还没有进行中的订阅")).toBeInTheDocument()
    await user.click(screen.getByRole("tab", { name: /已完结/ }))
    expect(await screen.findByText("完结归档书")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "打开《完结归档书》操作菜单" }))
    expect(screen.queryByRole("menuitem", { name: "继续" })).not.toBeInTheDocument()
    expect(screen.queryByRole("menuitem", { name: "暂停" })).not.toBeInTheDocument()
    expect(screen.queryByRole("menuitem", { name: "归档" })).not.toBeInTheDocument()
  })

  it("refetches the library query from the error state", async () => {
    const user = userEvent.setup()
    ;(api.subscribe.myLibrary as any)
      .mockRejectedValueOnce(new Error("书库暂时不可用"))
      .mockResolvedValueOnce({ items: [] })
    renderPage()

    expect(await screen.findByText("书库暂时不可用")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(api.subscribe.myLibrary).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("你还没有进行中的订阅")).toBeInTheDocument()
  })

  it("refreshes library progress while the page remains open", async () => {
    vi.useFakeTimers()
    const view = renderPage()
    try {
      await vi.waitFor(() => expect(api.subscribe.myLibrary).toHaveBeenCalledTimes(1))
      await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
      await vi.waitFor(() => expect(api.subscribe.myLibrary).toHaveBeenCalledTimes(2))
    } finally {
      view.unmount()
      vi.useRealTimers()
    }
  })

  it("rejects unknown actions without calling an archive or rebuild endpoint", () => {
    expect(() => executeLibraryBookAction("book-1", "unexpected", false)).toThrow("不支持的书库操作")
    expect(() => executeLibraryBookAction("book-1", "unexpected", true)).toThrow("不支持的书库操作")
    expect(api.subscribe.updateSubscription).not.toHaveBeenCalled()
    expect(api.archiveLibraryBook).not.toHaveBeenCalled()
    expect(api.rebuildLibraryBook).not.toHaveBeenCalled()
  })
})
