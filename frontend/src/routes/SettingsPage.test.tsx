import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { SettingsPage } from "./SettingsPage"

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    settings: vi.fn(),
    updateSettings: vi.fn(),
    aggregateSettings: vi.fn(),
    updateAggregateSettings: vi.fn(),
    lexiconStatus: vi.fn(),
    updateLexicon: vi.fn(),
    auth: { changePassword: vi.fn() },
  },
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  )
}

describe("SettingsPage subscription policy", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.settings as any).mockResolvedValue({
      sourcePool: {
        proxy: { enabled: false, url: "", allowAutoRetry: false },
        max_concurrency: 20,
        source_timeout_seconds: 8,
        overall_search_timeout_seconds: 120,
        browser_source_timeout_seconds: 30,
        browser_search_timeout_seconds: 30,
        default_user_agent: "test-agent",
        officialSourceInNormalSearch: false,
      },
      searchScoreFilter: 100,
      searchConfig: {
        overallTimeoutSeconds: 120,
        firstResultTimeoutSeconds: 5,
        sourceTimeoutSeconds: 8,
        cacheTtlSeconds: 600,
      },
      contentWorkflow: {},
      subscription: {
        maxActivePerUser: 100,
        maxNewSharedBooksPerDay: 10,
        maxGlobalProvisioningBooks: 20,
        rateLimitWindowSeconds: 60,
        searchRateLimitPerWindow: 30,
        createRateLimitPerWindow: 10,
        updateRateLimitPerWindow: 60,
      },
    })
    ;(api.aggregateSettings as any).mockResolvedValue({ contentWorkflow: {} })
    ;(api.lexiconStatus as any).mockResolvedValue({})
    ;(api.updateSettings as any).mockResolvedValue({ saved: true })
    ;(api.updateAggregateSettings as any).mockResolvedValue({ saved: true })
  })

  it("saves administrator subscription quotas through the existing settings flow", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("tab", { name: "订阅政策" }))
    const activeLimit = screen.getByLabelText("每用户活跃订阅上限")
    const searchLimit = screen.getByLabelText("每窗口搜索次数")
    await user.clear(activeLimit)
    await user.type(activeLimit, "23")
    await user.clear(searchLimit)
    await user.type(searchLimit, "12")
    await user.click(screen.getByRole("button", { name: "保存配置" }))

    await waitFor(() => expect(api.updateSettings).toHaveBeenCalledTimes(1))
    const payload = (api.updateSettings as any).mock.calls[0][0]
    expect(payload.subscription).toEqual({
      maxActivePerUser: 23,
      maxNewSharedBooksPerDay: 10,
      maxGlobalProvisioningBooks: 20,
      rateLimitWindowSeconds: 60,
      searchRateLimitPerWindow: 12,
      createRateLimitPerWindow: 10,
      updateRateLimitPerWindow: 60,
    })
    expect(payload.searchConfig.sourceTimeoutSeconds).toBe(8)
    expect(payload.contentWorkflow).toBeUndefined()
  })

  it("refetches both settings queries from the load error", async () => {
    const user = userEvent.setup()
    ;(api.settings as any)
      .mockRejectedValueOnce(new Error("设置接口不可用"))
      .mockResolvedValueOnce({ sourcePool: {}, subscription: {} })
    renderPage()

    expect(await screen.findByText("设置接口不可用")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(api.settings).toHaveBeenCalledTimes(2))
    expect(api.aggregateSettings).toHaveBeenCalledTimes(2)
  })
})
