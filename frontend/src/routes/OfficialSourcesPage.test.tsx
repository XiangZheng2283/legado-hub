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

function renderPage(embedded = false) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <OfficialSourcesPage embedded={embedded} />
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
        enabled: true,
        auth: { mode: "required" },
        authStatus: { authenticated: true, accountName: "reader" },
      }],
    })
  })

  it("embeds authentication controls without a second page heading", async () => {
    renderPage(true)

    const sourceLink = await screen.findByRole("link", { name: "起点中文网" })
    expect(sourceLink).toHaveAttribute("href", "/console/plugins/qidian_com")
    expect(screen.queryByRole("heading", { name: "官方源管理" })).not.toBeInTheDocument()
    expect(screen.getByRole("button", { name: "全局刷新状态" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "格式/分类" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Ping 状态" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "账号状态" })).toBeInTheDocument()
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
