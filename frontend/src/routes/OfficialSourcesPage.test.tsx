import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { OfficialSourcesPage } from "./OfficialSourcesPage"

vi.mock("@/lib/api", () => ({
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

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <OfficialSourcesPage />
    </QueryClientProvider>
  )
}

describe("OfficialSourcesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.officialSources as any).mockResolvedValue({
      items: [{
        pluginId: "qidian_com",
        name: "起点中文网",
        auth: { mode: "required" },
        authStatus: { authenticated: true, accountName: "reader" },
      }],
    })
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
})
