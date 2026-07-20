import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { BROWSER_LOGIN_TIMEOUT_MS, OfficialSourcesPage } from "./OfficialSourcesPage"

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    officialSources: vi.fn(),
    pluginAuthCheck: vi.fn(),
    loginLogout: vi.fn(),
    pluginCookiesClear: vi.fn(),
    cancelLoginBrowser: vi.fn(),
    startLoginBrowser: vi.fn(),
    getLoginBrowserStatus: vi.fn(),
  },
}))

function renderPage(selection?: { selectedIds: Set<string>; onToggleSelectAll: () => void; onToggleSelected: (pluginId: string) => void }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OfficialSourcesPage {...selection} />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe("OfficialSourcesPage", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.officialSources as any).mockResolvedValue({
      items: [{
        pluginId: "qidian_com",
        name: "起点中文网",
        enabled: false,
        accessType: "Browser",
        auth: { mode: "required" },
        authStatus: { authenticated: true, accountName: "reader", lastCheckedAt: "2026-07-18T01:00:00Z" },
      }],
    })
  })

  it("embeds authentication controls without a second page heading", async () => {
    const onToggleSelectAll = vi.fn()
    const onToggleSelected = vi.fn()
    renderPage({ selectedIds: new Set(), onToggleSelectAll, onToggleSelected })

    const sourceName = await screen.findByText("起点中文网")
    expect(screen.queryByRole("heading", { name: "官方源管理" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "全局刷新状态" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Ping" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "登录状态" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "登录操作" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "插件标识 (ID)" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "格式/分类" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "激活状态" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "认证模式" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "当前账号" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "最后检查" })).not.toBeInTheDocument()
    expect(screen.getByText("reader")).toHaveClass("bg-emerald-50")
    expect(screen.queryByText("有效")).not.toBeInTheDocument()
    expect(screen.queryByText("已检查")).not.toBeInTheDocument()
    expect(screen.queryByText("尚未检查")).not.toBeInTheDocument()
    expect(screen.getByText("Browser")).toBeInTheDocument()
    expect(sourceName.closest("tr")).toHaveClass("grayscale")
    await userEvent.click(screen.getByRole("checkbox", { name: "选择 起点中文网" }))
    expect(onToggleSelected).toHaveBeenCalledWith("qidian_com")
  })

  it("shows a single invalid or signed-out login label", async () => {
    ;(api.officialSources as any).mockResolvedValue({
      items: [
        { pluginId: "expired", name: "失效源", enabled: true, authStatus: { authenticated: false, hasCookies: true } },
        { pluginId: "signed-out", name: "未登录源", enabled: true, authStatus: { authenticated: false, hasCookies: false } },
      ],
    })

    renderPage()

    expect(await screen.findByText("登录失效")).toBeInTheDocument()
    expect(screen.getByText("未登录")).toBeInTheDocument()
    expect(screen.queryByText("有效")).not.toBeInTheDocument()
    expect(screen.queryByText("尚未检查")).not.toBeInTheDocument()
  })

  it("requires confirmation before logging out an official source", async () => {
    const user = userEvent.setup()
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false)
    renderPage()

    await user.click(await screen.findByRole("button", { name: "注销 起点中文网" }))
    expect(api.loginLogout).not.toHaveBeenCalled()

    confirm.mockReturnValue(true)
    ;(api.loginLogout as any).mockResolvedValue({ ok: true })
    await user.click(screen.getByRole("button", { name: "注销 起点中文网" }))

    await waitFor(() => expect(api.loginLogout).toHaveBeenCalledWith("qidian_com"))
  })

  it("stops browser-login polling at the five-minute deadline and permits a restart", async () => {
    let resolveFirstStart: (value: unknown) => void = () => {}
    ;(api.startLoginBrowser as any)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirstStart = resolve }))
      .mockResolvedValueOnce({ status: "running", message: "第二次登录进行中" })
    ;(api.getLoginBrowserStatus as any).mockImplementation(() => new Promise(() => {}))
    renderPage()
    await screen.findByText("起点中文网")
    vi.useFakeTimers()

    await act(async () => {
      window.dispatchEvent(new CustomEvent("official-source-browser-login", { detail: { pluginId: "qidian_com" } }))
      await Promise.resolve()
    })
    expect(api.startLoginBrowser).toHaveBeenCalledTimes(1)

    act(() => { vi.advanceTimersByTime(BROWSER_LOGIN_TIMEOUT_MS) })
    expect(screen.getByText("浏览器登录超时，请重新发起。")).toBeInTheDocument()

    await act(async () => {
      window.dispatchEvent(new CustomEvent("official-source-browser-login", { detail: { pluginId: "qidian_com" } }))
      await Promise.resolve()
    })
    expect(api.startLoginBrowser).toHaveBeenCalledTimes(2)
    expect(screen.getByText("第二次登录进行中")).toBeInTheDocument()

    await act(async () => {
      resolveFirstStart({ status: "success", message: "迟到的旧会话" })
      await Promise.resolve()
    })
    expect(screen.queryByText("迟到的旧会话")).not.toBeInTheDocument()
    expect(screen.getByText("第二次登录进行中")).toBeInTheDocument()
  })

  it("clears browser-login timers when the page unmounts", async () => {
    ;(api.startLoginBrowser as any).mockResolvedValue({ status: "running" })
    ;(api.getLoginBrowserStatus as any).mockResolvedValue({ status: "running" })
    const view = renderPage()
    await screen.findByText("起点中文网")
    vi.useFakeTimers()

    await act(async () => {
      window.dispatchEvent(new CustomEvent("official-source-browser-login", { detail: { pluginId: "qidian_com" } }))
      await Promise.resolve()
    })
    view.unmount()
    act(() => { vi.advanceTimersByTime(BROWSER_LOGIN_TIMEOUT_MS) })

    expect(api.getLoginBrowserStatus).not.toHaveBeenCalled()
  })
})
