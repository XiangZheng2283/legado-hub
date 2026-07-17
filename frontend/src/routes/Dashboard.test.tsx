import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { Dashboard } from "./Dashboard"

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { userId: "admin-1", username: "admin", role: "admin" } }),
}))

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: { status: vi.fn() },
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <Dashboard />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe("Dashboard", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("refetches system status from the error state", async () => {
    const user = userEvent.setup()
    ;(api.status as any)
      .mockRejectedValueOnce(new Error("状态接口不可用"))
      .mockResolvedValueOnce({
        health: "healthy",
        uptimeSeconds: 3660,
        version: "0.0.1",
        pluginStats: { total: 2, enabled: 2, disabled: 0, healthy: 2, unhealthy: 0, checked: 2, unknown: 0 },
      })
    renderPage()

    expect(await screen.findByText(/状态接口不可用/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试" }))

    await waitFor(() => expect(api.status).toHaveBeenCalledTimes(2))
    expect(await screen.findByText("1 小时 1 分钟")).toBeInTheDocument()
    expect(screen.getByText("后端进程 · v0.0.1")).toBeInTheDocument()
  })

  it("shows degraded and untested plugin state from the status contract", async () => {
    ;(api.status as any).mockResolvedValue({
      health: "degraded",
      uptimeSeconds: 60,
      version: "0.0.1",
      pluginStats: { total: 4, enabled: 3, disabled: 1, healthy: 1, unhealthy: 1, checked: 2, unknown: 1 },
    })

    renderPage()

    expect(await screen.findByText("1 分钟")).toBeInTheDocument()
    expect(screen.getByText("另有 1 个待检测")).toBeInTheDocument()
    expect(screen.getByText("启用 3 · 停用 1")).toBeInTheDocument()
  })
})
