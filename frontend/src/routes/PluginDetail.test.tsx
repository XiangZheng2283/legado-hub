import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { PluginDetail } from "./PluginDetail"

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    plugin: vi.fn(),
    pluginAttempts: vi.fn(),
    enablePlugin: vi.fn(),
    pingPlugin: vi.fn(),
  },
}))

const plugin = {
  pluginId: "source-1",
  name: "测试书源",
  author: "Yunwei",
  version: "1.0.0",
  enabled: true,
  capabilities: ["search", "chapter"],
  health: {},
  auth: { mode: "none" },
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/console/plugins/source-1"]}>
        <Routes>
          <Route path="/console/plugins/:pluginId" element={<PluginDetail />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("PluginDetail", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.plugin as any).mockResolvedValue(plugin)
    ;(api.pluginAttempts as any).mockResolvedValue({ attempts: [] })
    ;(api.pingPlugin as any).mockResolvedValue({ pluginId: "source-1", status: "reachable", latencyMs: 7 })
  })

  it("refetches plugin details from the load error", async () => {
    const user = userEvent.setup()
    ;(api.plugin as any)
      .mockRejectedValueOnce(new Error("书源详情不可用"))
      .mockResolvedValueOnce(plugin)
    renderPage()

    expect(await screen.findByText(/书源详情不可用/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(api.plugin).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("测试书源")).toBeInTheDocument()
  })

  it("refetches attempt records without reloading plugin details", async () => {
    const user = userEvent.setup()
    ;(api.pluginAttempts as any)
      .mockRejectedValueOnce(new Error("执行记录不可用"))
      .mockResolvedValueOnce({ attempts: [] })
    renderPage()

    expect(await screen.findByText("执行记录不可用")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试记录" }))

    await waitFor(() => expect(api.pluginAttempts).toHaveBeenCalledTimes(2))
    expect(api.plugin).toHaveBeenCalledTimes(1)
  })

  it("runs the retained ping check", async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText("Yunwei")).toBeInTheDocument()
    await user.click(await screen.findByRole("button", { name: "Ping 检测" }))

    await waitFor(() => expect(api.pingPlugin).toHaveBeenCalledWith("source-1"))
    await waitFor(() => expect(api.plugin).toHaveBeenCalledTimes(2))
    await waitFor(() => expect(api.pluginAttempts).toHaveBeenCalledTimes(2))
  })

  it("shows ping failures without restoring smoke controls", async () => {
    const user = userEvent.setup()
    ;(api.pingPlugin as any).mockRejectedValueOnce(new Error("Ping 请求失败"))
    renderPage()

    await user.click(await screen.findByRole("button", { name: "Ping 检测" }))

    expect(await screen.findByText("Ping 请求失败")).toBeInTheDocument()
    expect(screen.queryByText(/Smoke|冒烟/)).not.toBeInTheDocument()
  })
})
