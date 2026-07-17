import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { executeLibraryBookAction } from "@/lib/library-actions"
import { LibraryPage } from "./LibraryPage"

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { userId: "user-1", username: "reader", role: "user" } }),
}))

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    subscribe: {
      myLibrary: vi.fn(),
      updateSubscription: vi.fn(),
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
  })

  it("shows personal coverage and pauses only the current user's subscription", async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText("25%")).toBeInTheDocument()
    expect(screen.getByText("全文 20 · 预览 5")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "打开《用户订阅书》操作菜单" }))
    await user.click(screen.getByRole("menuitem", { name: "暂停" }))

    await waitFor(() => expect(api.subscribe.updateSubscription).toHaveBeenCalledWith(
      "book-1",
      { status: "paused" },
    ))
    expect(api.pauseLibraryBook).not.toHaveBeenCalled()
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
    expect(await screen.findByText("你还没有订阅的书籍")).toBeInTheDocument()
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
