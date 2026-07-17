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
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
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
  const view = render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SubscriptionDiscoveryPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { ...view, queryClient }
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
        sourceCount: 2,
        sourceSummaryText: "起点中文网(App) / 起点中文网(Web)",
      }],
    })
    ;(api.subscribe.subscribeCard as any).mockResolvedValue({
      book: { aggregateBookId: "book-1" },
      provisioning: {
        state: "processing",
        readableChapterCount: 0,
        previewChapterCount: 0,
        pendingChapterCount: 10,
        firstReadableChapter: null,
      },
    })
  })

  it("subscribes an existing shared book with user-selected settings", async () => {
    const user = userEvent.setup()
    const { queryClient } = renderPage()
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries")

    await user.type(screen.getByLabelText("搜索小说或作者"), "共享书")
    await user.click(screen.getByRole("button", { name: "开始搜索" }))
    expect(await screen.findByText("已入库")).toBeInTheDocument()
    expect(screen.getByText("2 个来源")).toBeInTheDocument()
    expect(screen.queryByText("已共享，可订阅")).not.toBeInTheDocument()
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
    await waitFor(() => expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["library"] }))
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

  it("stops polling when a persisted search was interrupted by restart", async () => {
    const user = userEvent.setup()
    ;(api.subscribe.searchJob as any).mockResolvedValue({
      jobId: "job-1",
      status: "interrupted",
      liveSearchPending: true,
      message: "服务重启，搜索任务已中断，请重新搜索。",
      cards: [],
    })
    renderPage()

    await user.type(screen.getByLabelText("搜索小说或作者"), "测试")
    await user.click(screen.getByRole("button", { name: "开始搜索" }))

    expect(await screen.findByText("服务重启，搜索任务已中断，请重新搜索。")).toBeInTheDocument()
    expect(screen.queryByText("正在搜索…")).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "开始搜索" })).toBeEnabled()
    expect(screen.getByRole("button", { name: "重试" })).toBeEnabled()
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

  it("refetches the active search job from the error state", async () => {
    const user = userEvent.setup()
    ;(api.subscribe.searchJob as any)
      .mockRejectedValueOnce(new Error("搜索状态暂时不可用"))
      .mockResolvedValueOnce({ status: "completed", liveSearchPending: false, cards: [] })
    renderPage()

    await user.type(screen.getByLabelText("搜索小说或作者"), "测试")
    await user.click(screen.getByRole("button", { name: "开始搜索" }))
    expect(await screen.findByText("搜索状态暂时不可用")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(api.subscribe.searchJob).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("未找到匹配的书籍。")).toBeInTheDocument()
  })
})
