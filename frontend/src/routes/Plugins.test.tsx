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
      ],
    })
    ;(api.pingAllPlugins as any).mockResolvedValue({ results: [] })
  })

  it("uses Ping as the only source health signal", async () => {
    const user = userEvent.setup()
    renderPage()

    expect(await screen.findByText("50.0%")).toBeInTheDocument()
    expect(screen.getByText("2/2 已测")).toBeInTheDocument()
    expect(screen.getAllByText("作者: Yunwei")).toHaveLength(2)
    expect(screen.queryByText(/Smoke|冒烟|测试通过率/)).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Ping 全部" }))
    await waitFor(() => expect(api.pingAllPlugins).toHaveBeenCalledWith(["source-1", "source-2"]))
  })
})
