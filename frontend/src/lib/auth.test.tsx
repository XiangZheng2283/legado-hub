import { act, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useState } from "react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AuthProvider, useAuth } from "./auth"

const apiMocks = vi.hoisted(() => ({
  entrypoint: vi.fn(),
  me: vi.fn(),
  login: vi.fn(),
  redeemAccessCode: vi.fn(),
  logout: vi.fn(),
}))

vi.mock("@/lib/api", () => ({
  api: {
    auth: apiMocks,
  },
}))

function LoginProbe() {
  const { login, user } = useAuth()
  const [resolved, setResolved] = useState(false)
  return (
    <div>
      <button
        type="button"
        onClick={() => {
          void login("admin", "password-123").then(() => setResolved(true))
        }}
      >
        登录
      </button>
      <span>{user?.username || "未登录"}</span>
      {resolved && <span>登录 Promise 已完成</span>}
    </div>
  )
}

function StatusProbe() {
  const { authError, entrypoint, logout, retryAuth, user } = useAuth()
  return (
    <div>
      <span>{entrypoint}</span>
      <span>{user?.username || "未登录"}</span>
      <span>{authError || "认证可用"}</span>
      <button type="button" onClick={() => { void retryAuth() }}>重试认证</button>
      <button type="button" onClick={() => { void logout() }}>退出</button>
    </div>
  )
}

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.entrypoint.mockResolvedValue({ entrypoint: "admin" })
    apiMocks.login.mockResolvedValue({ ok: true })
  })

  it("waits for an explicit identity before resolving login", async () => {
    let resolveIdentity: (value: unknown) => void = () => undefined
    apiMocks.me
      .mockResolvedValueOnce({ authenticated: false, user: null })
      .mockImplementationOnce(
        () => new Promise((resolve) => {
          resolveIdentity = resolve
        }),
      )
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <LoginProbe />
        </AuthProvider>
      </QueryClientProvider>,
    )

    expect(await screen.findByText("未登录")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "登录" }))
    await waitFor(() => expect(apiMocks.login).toHaveBeenCalledTimes(1))
    expect(screen.queryByText("登录 Promise 已完成")).not.toBeInTheDocument()

    await act(async () => {
      resolveIdentity({
        authenticated: true,
        user: { userId: "admin-id", username: "admin", role: "admin", disabled: false },
      })
    })

    expect(await screen.findByText("admin")).toBeInTheDocument()
    expect(await screen.findByText("登录 Promise 已完成")).toBeInTheDocument()
  })

  it("keeps network failures distinct from an unauthenticated identity", async () => {
    apiMocks.entrypoint.mockResolvedValue({ entrypoint: "public" })
    apiMocks.me
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ authenticated: false, user: null })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider><StatusProbe /></AuthProvider>
      </QueryClientProvider>,
    )

    expect(await screen.findByText("无法连接认证服务，请检查网络后重试。")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "重试认证" }))
    expect(await screen.findByText("认证可用")).toBeInTheDocument()
    expect(screen.getByText("未登录")).toBeInTheDocument()
  })

  it("preserves the entrypoint while clearing session state on logout", async () => {
    apiMocks.entrypoint.mockResolvedValue({ entrypoint: "public" })
    apiMocks.me.mockResolvedValue({
      authenticated: true,
      user: { userId: "reader-id", username: "reader", role: "user", disabled: false },
    })
    apiMocks.logout.mockResolvedValue({ ok: true })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const user = userEvent.setup()
    render(
      <QueryClientProvider client={queryClient}>
        <AuthProvider><StatusProbe /></AuthProvider>
      </QueryClientProvider>,
    )

    expect(await screen.findByText("reader")).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: "退出" }))
    expect(await screen.findByText("未登录")).toBeInTheDocument()
    expect(screen.getByText("public")).toBeInTheDocument()
  })
})
