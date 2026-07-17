import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { Plugins } from "./Plugins"

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    plugins: vi.fn(),
    pingAllPlugins: vi.fn(),
    batchEnablePlugins: vi.fn(),
  },
}))

vi.mock("./OfficialSourcesPage", () => ({
  OfficialSourcesPage: ({ embedded }: { embedded?: boolean }) => (
    <div data-testid="official-auth-panel">官方认证面板 {embedded ? "embedded" : "standalone"}</div>
  ),
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Plugins />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("Plugins", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.plugins as any).mockResolvedValue({
      items: [
        { pluginId: "source-1", name: "书源一", author: "Yunwei", enabled: true, official: false, health: { pingStatus: "reachable", pingLatencyMs: 10 } },
        { pluginId: "source-2", name: "书源二", author: "Yunwei", enabled: true, official: false, health: { pingStatus: "unreachable", pingLatencyMs: 20 } },
        { pluginId: "official-1", name: "官方源一", author: "Yunwei", enabled: true, official: true, capabilities: ["auth"] },
      ],
    })
    ;(api.pingAllPlugins as any).mockResolvedValue({ results: [] })
    ;(api.batchEnablePlugins as any).mockResolvedValue({ results: [] })
  })

  it("uses Ping as the only source health signal", async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText("50.0%")).toBeInTheDocument()
    expect(screen.getByText("2/2 已测")).toBeInTheDocument()
    expect(screen.getAllByText("作者: Yunwei")).toHaveLength(2)
    expect(screen.queryByText(/Smoke|冒烟|测试通过率/)).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText(/搜索书源名称/)).not.toBeInTheDocument()
    expect(screen.getByRole("checkbox", { name: "全选当前书源" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "详情与检测" })).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Ping 全部" }))
    await waitFor(() => expect(api.pingAllPlugins).toHaveBeenCalledWith(["source-1", "source-2"]))
  })

  it("runs batch actions from the shared table header selection", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("checkbox", { name: "全选当前书源" }))
    expect(screen.getByText("已选 2 项")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "批量启用" }))

    await waitFor(() => expect(api.batchEnablePlugins).toHaveBeenCalledWith(["source-1", "source-2"], true))
  })

  it("shows official authentication inside the unified source page", async () => {
    const user = userEvent.setup()
    renderPage()

    await user.click(await screen.findByRole("tab", { name: /官方源认证/ }))

    expect(screen.getByTestId("official-auth-panel")).toHaveTextContent("embedded")
    expect(screen.queryByPlaceholderText("搜索书源名称, ID, 或贡献者/作者...")).not.toBeInTheDocument()
  })
})
