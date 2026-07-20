import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { api } from "@/lib/api"
import { UsersPage } from "./UsersPage"

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { userId: "admin-1", username: "admin", role: "admin" } }),
}))

vi.mock("@/lib/api", () => ({
  apiErrorMessage: (error: any, fallback: string) => error?.message || fallback,
  api: {
    users: {
      list: vi.fn(),
      create: vi.fn(),
      resetPassword: vi.fn(),
      resetAccessCode: vi.fn(),
      revokeSessions: vi.fn(),
      setDisabled: vi.fn(),
    },
  },
}))

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <UsersPage />
    </QueryClientProvider>,
  )
}

describe("UsersPage", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    ;(api.users.list as any).mockResolvedValue({
      items: [
        { userId: "admin-1", username: "admin", role: "admin", disabled: false },
        { userId: "user-1", username: "reader", role: "user", disabled: false },
      ],
      total: 2,
    })
    ;(api.users.create as any).mockResolvedValue({
      userId: "user-2",
      username: "new-reader",
      role: "user",
      disabled: false,
      accessCode: "LH1.new-reader.secret",
    })
    ;(api.users.resetPassword as any).mockResolvedValue({ userId: "admin-1", passwordReset: true })
    ;(api.users.resetAccessCode as any).mockResolvedValue({ userId: "user-1", accessCode: "LH1.reader.replacement" })
    ;(api.users.revokeSessions as any).mockResolvedValue({ userId: "user-1", revokedSessions: 2 })
    ;(api.users.setDisabled as any).mockResolvedValue({ userId: "user-1", disabled: true })
  })

  it("creates an access user without a password and shows the code once", async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByText("reader")

    await user.click(screen.getByRole("button", { name: "新建用户" }))
    await user.type(screen.getByLabelText("用户名"), "new-reader")
    expect(screen.queryByLabelText("初始密码")).not.toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "创建" }))

    await waitFor(() => expect(api.users.create).toHaveBeenCalledWith({
      username: "new-reader",
      role: "user",
    }))
    expect(await screen.findByText("LH1.new-reader.secret")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "关闭" }))
    expect(screen.queryByText("LH1.new-reader.secret")).not.toBeInTheDocument()
  })

  it("requires an initial password only when creating an administrator", async () => {
    const user = userEvent.setup()
    ;(api.users.create as any).mockResolvedValue({
      userId: "admin-2",
      username: "operator",
      role: "admin",
      disabled: false,
    })
    renderPage()
    await screen.findByText("reader")

    await user.click(screen.getByRole("button", { name: "新建用户" }))
    await user.type(screen.getByLabelText("用户名"), "operator")
    await user.selectOptions(screen.getByLabelText("角色"), "admin")
    await user.type(screen.getByLabelText("初始密码"), "password-123")
    await user.click(screen.getByRole("button", { name: "创建" }))

    await waitFor(() => expect(api.users.create).toHaveBeenCalledWith({
      username: "operator",
      password: "password-123",
      role: "admin",
    }))
  })

  it("resets access codes, revokes sessions, and prevents disabling the current account", async () => {
    const user = userEvent.setup()
    vi.spyOn(window, "confirm").mockReturnValue(true)
    renderPage()

    const adminRow = (await screen.findByText("admin")).closest("tr")
    const readerRow = screen.getByText("reader").closest("tr")
    expect(adminRow).not.toBeNull()
    expect(readerRow).not.toBeNull()
    expect(within(adminRow!).getByRole("button", { name: "禁用" })).toBeDisabled()
    expect(within(adminRow!).getByRole("button", { name: "撤销 admin 的登录会话" })).toBeDisabled()

    await user.click(within(readerRow!).getByRole("button", { name: "重置 reader 的授权码" }))
    await user.click(screen.getByRole("button", { name: "生成新授权码" }))
    await waitFor(() => expect(api.users.resetAccessCode).toHaveBeenCalledWith("user-1"))
    expect(await screen.findByText("LH1.reader.replacement")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "关闭" }))

    await user.click(within(readerRow!).getByRole("button", { name: "撤销 reader 的登录会话" }))
    await waitFor(() => expect(api.users.revokeSessions).toHaveBeenCalledWith("user-1"))
    expect(await screen.findByText("已撤销 reader 的 2 个登录会话。")).toBeInTheDocument()

    await user.click(within(readerRow!).getByRole("button", { name: "禁用" }))
    await waitFor(() => expect(api.users.setDisabled).toHaveBeenCalledWith("user-1", true))
  })
})
