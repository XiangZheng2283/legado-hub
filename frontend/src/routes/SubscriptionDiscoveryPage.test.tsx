import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { SubscriptionDiscoveryPage } from "./SubscriptionDiscoveryPage"

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { userId: "user-1", username: "reader", role: "user" } }),
}))

vi.mock("@/lib/api", () => ({
  api: {
    subscribe: {
      search: vi.fn(),
      searchJob: vi.fn(),
      subscribeCard: vi.fn(),
    },
  },
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SubscriptionDiscoveryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("SubscriptionDiscoveryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.subscribe.search as any).mockResolvedValue({ jobId: "job-1" })
    ;(api.subscribe.searchJob as any).mockResolvedValue({
      jobId: "job-1",
      status: "completed",
      liveSearchPending: false,
      cards: [{
        candidateId: "candidate-1",
        name: "共享书",
        author: "作者",
        alreadyIngested: true,
        alreadySubscribed: false,
        aggregateBookId: "book-1",
      }],
    })
    ;(api.subscribe.subscribeCard as any).mockResolvedValue({ book: { aggregateBookId: "book-1" } })
  })

  it("subscribes an existing shared book with user-selected settings", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.type(screen.getByLabelText("搜索小说或作者"), "共享书")
    await user.click(screen.getByRole("button", { name: "开始搜索" }))
    await user.click(await screen.findByText("共享书"))

    const startInput = screen.getByLabelText("从第几章开始订阅")
    await user.clear(startInput)
    await user.type(startInput, "5")
    await user.click(screen.getByRole("switch", { name: "完结且处理完成后自动归档" }))
    await user.click(screen.getByRole("button", { name: "确认订阅" }))

    await waitFor(() => expect(api.subscribe.subscribeCard).toHaveBeenCalledWith(
      "job-1",
      "candidate-1",
      { startChapterIndex: 5, autoArchiveOnComplete: false },
    ))
  })

  it("stops the searching state and shows the backend failure message", async () => {
    const user = userEvent.setup()
    ;(api.subscribe.searchJob as any).mockResolvedValue({
      jobId: "job-1",
      status: "failed",
      liveSearchPending: false,
      message: "官方源暂时不可用",
      cards: [],
    })
    renderPage()

    await user.type(screen.getByLabelText("搜索小说或作者"), "测试")
    await user.click(screen.getByRole("button", { name: "开始搜索" }))

    expect(await screen.findByText("官方源暂时不可用")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "开始搜索" })).toBeEnabled()
  })

  it("keeps the dialog open when a success response has no book id", async () => {
    const user = userEvent.setup()
    ;(api.subscribe.subscribeCard as any).mockResolvedValue({})
    renderPage()

    await user.type(screen.getByLabelText("搜索小说或作者"), "共享书")
    await user.click(screen.getByRole("button", { name: "开始搜索" }))
    await user.click(await screen.findByText("共享书"))
    await user.click(screen.getByRole("button", { name: "确认订阅" }))

    expect(await screen.findByText("订阅响应缺少书籍 ID，请刷新后确认订阅状态。")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "确认订阅" })).toBeEnabled()
  })
})
