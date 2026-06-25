import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, waitFor, fireEvent } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { OfficialSourceLoginDialog } from "./OfficialSourceLoginDialog"
import { api } from "@/lib/api"

// Mock API module
vi.mock("@/lib/api", () => ({
  api: {
    loginCapabilities: vi.fn(),
    loginPhoneRequestCode: vi.fn(),
    loginPhoneVerify: vi.fn(),
    loginCookieVerify: vi.fn(),
    loginLogout: vi.fn(),
  },
}))

// Mock window.TencentCaptcha
const mockCaptchaShow = vi.fn()
Object.defineProperty(window, "TencentCaptcha", {
  writable: true,
  value: vi.fn(() => ({ show: mockCaptchaShow })),
})

describe("OfficialSourceLoginDialog", () => {
  let mockDispatchEvent: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    vi.clearAllMocks()
    mockDispatchEvent = vi.spyOn(window, "dispatchEvent")
  })

  afterEach(() => {
    mockDispatchEvent.mockRestore()
  })

  const renderDialog = (props = {}) =>
    render(
      <OfficialSourceLoginDialog
        pluginId="qidian_com"
        sourceName="起点中文网"
        open={true}
        onOpenChange={() => {}}
        {...props}
      />
    )

  it("shows only cookie tab when phone method is not available", async () => {
    ;(api.loginCapabilities as any).mockResolvedValue({
      pluginId: "other_src",
      methods: ["cookie"],
      defaultMethod: "cookie",
      privateFeatures: { phoneAuth: false, cookieAuth: false, reviews: false },
      hasPrivatePackage: false,
    })

    renderDialog({ pluginId: "other_src" })

    await waitFor(() => {
      expect(screen.getByText(/Cookie 登录始终可用/)).toBeInTheDocument()
    })

    expect(screen.getByRole("tab", { name: /Cookie/i })).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: /手机号/i })).not.toBeInTheDocument()
  })

  it("shows phone tab for qidian_com fallback without private package", async () => {
    ;(api.loginCapabilities as any).mockResolvedValue({
      pluginId: "qidian_com",
      methods: ["phone", "cookie"],
      defaultMethod: "phone",
      privateFeatures: { phoneAuth: false, cookieAuth: false, reviews: false },
      hasPrivatePackage: false,
    })

    renderDialog()

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /手机号/i })).toBeInTheDocument()
    })

    expect(screen.getByRole("tab", { name: /手机号/i })).toHaveAttribute("data-state", "active")
    expect(screen.getByRole("tab", { name: /Cookie/i })).toBeInTheDocument()
    expect(screen.queryByText(/需要安装私有插件/)).not.toBeInTheDocument()
  })

  it("defaults to phone tab when phone auth is available", async () => {
    ;(api.loginCapabilities as any).mockResolvedValue({
      pluginId: "qidian_com",
      methods: ["phone", "cookie"],
      defaultMethod: "phone",
      privateFeatures: { phoneAuth: true, cookieAuth: false, reviews: false },
      hasPrivatePackage: true,
    })

    renderDialog()

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /手机号/i })).toBeInTheDocument()
    })

    expect(screen.getByRole("tab", { name: /手机号/i })).toHaveAttribute("data-state", "active")
    expect(screen.getByRole("tab", { name: /Cookie/i })).toBeInTheDocument()
  })

  it("retries request-code with challenge params after captcha", async () => {
    const user = userEvent.setup()

    ;(api.loginCapabilities as any).mockResolvedValue({
      pluginId: "qidian_com",
      methods: ["phone", "cookie"],
      defaultMethod: "phone",
      privateFeatures: { phoneAuth: true, cookieAuth: false, reviews: false },
      hasPrivatePackage: true,
    })

    // First call returns challenge required
    ;(api.loginPhoneRequestCode as any)
      .mockResolvedValueOnce({
        ok: false,
        sessionId: "sess_abc",
        nextAction: "complete_challenge",
        challenge: { type: "tencent_captcha", appId: "1600000770" },
      })
      // Second call (after captcha) succeeds
      .mockResolvedValueOnce({
        ok: true,
        sessionId: "sess_abc",
        nextAction: "verify_code",
      })

    renderDialog()

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /手机号/i })).toBeInTheDocument()
    })

    const phoneInput = screen.getByPlaceholderText(/请输入手机号/)
    await user.type(phoneInput, "13800138000")

    const requestBtn = screen.getByRole("button", { name: /获取验证码/ })
    await user.click(requestBtn)

    await waitFor(() => {
      expect(api.loginPhoneRequestCode).toHaveBeenCalledTimes(1)
    })

    // Simulate captcha callback
    const captchaCallback = mockCaptchaShow.mock.calls[0]?.[0]
    if (!captchaCallback) {
      // TencentCaptcha constructor callback pattern
      const tencentCtor = (window as any).TencentCaptcha
      const ctorArgs = tencentCtor.mock.calls[0]
      const callback = ctorArgs?.[2]
      if (callback) {
        callback({ ret: 0, ticket: "ticket_123", randstr: "@rand" })
      }
    }

    await waitFor(() => {
      expect(api.loginPhoneRequestCode).toHaveBeenCalledTimes(2)
    })

    const secondCall = (api.loginPhoneRequestCode as any).mock.calls[1]
    expect(secondCall[1]).toMatchObject({
      phone: "13800138000",
      sessionId: "sess_abc",
      challengeToken: "ticket_123",
      challengeRandstr: "@rand",
    })
  })

  it("emits browser-login event when browser tab is clicked", async () => {
    const user = userEvent.setup()

    ;(api.loginCapabilities as any).mockResolvedValue({
      pluginId: "qidian_com",
      methods: ["browser"],
      defaultMethod: "browser",
      privateFeatures: { phoneAuth: false, cookieAuth: false, reviews: false },
      hasPrivatePackage: false,
    })

    renderDialog()

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /浏览器/i })).toBeInTheDocument()
    })

    const startBtn = screen.getByRole("button", { name: /启动浏览器登录/ })
    await user.click(startBtn)

    expect(mockDispatchEvent).toHaveBeenCalled()
    const event = mockDispatchEvent.mock.calls.find(
      (call: any) => call[0] instanceof CustomEvent && call[0].type === "official-source-browser-login"
    )
    expect(event).toBeTruthy()
    expect((event![0] as CustomEvent).detail.pluginId).toBe("qidian_com")
  })

  it("calls onSuccess after cookie login succeeds", async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()

    ;(api.loginCapabilities as any).mockResolvedValue({
      pluginId: "qidian_com",
      methods: ["cookie"],
      defaultMethod: "cookie",
      privateFeatures: { phoneAuth: false, cookieAuth: false, reviews: false },
      hasPrivatePackage: false,
    })

    ;(api.loginCookieVerify as any).mockResolvedValue({
      ok: true,
      authenticated: true,
      accountName: "test_user",
      message: "Cookie 验证通过",
    })

    renderDialog({ onSuccess })

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /Cookie/i })).toBeInTheDocument()
    })

    const textarea = screen.getByPlaceholderText(/粘贴完整的 Cookie 字符串/)
    await user.type(textarea, "ywguid=abc; ywkey=def")

    const verifyBtn = screen.getByRole("button", { name: /验证登录/ })
    await user.click(verifyBtn)

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled()
    })
  })

  it("calls onSuccess after phone login succeeds", async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()

    ;(api.loginCapabilities as any).mockResolvedValue({
      pluginId: "qidian_com",
      methods: ["phone", "cookie"],
      defaultMethod: "phone",
      privateFeatures: { phoneAuth: true, cookieAuth: false, reviews: false },
      hasPrivatePackage: true,
    })

    ;(api.loginPhoneRequestCode as any).mockResolvedValue({
      ok: true,
      sessionId: "sess_123",
      nextAction: "verify_code",
    })

    ;(api.loginPhoneVerify as any).mockResolvedValue({
      ok: true,
      authenticated: true,
      accountName: "phone_user",
      message: "登录成功",
    })

    renderDialog({ onSuccess })

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /手机号/i })).toBeInTheDocument()
    })

    const phoneInput = screen.getByPlaceholderText(/请输入手机号/)
    await user.type(phoneInput, "13800138000")

    await user.click(screen.getByRole("button", { name: /获取验证码/ }))

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/请输入短信验证码/)).toBeInTheDocument()
    })

    const codeInput = screen.getByPlaceholderText(/请输入短信验证码/)
    await user.type(codeInput, "123456")

    await user.click(screen.getByRole("button", { name: /^登录$/ }))

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled()
    })
  })

  it("accepts pending phone login confirmation after verify", async () => {
    const user = userEvent.setup()
    const onSuccess = vi.fn()

    ;(api.loginCapabilities as any).mockResolvedValue({
      pluginId: "qidian_com_app",
      methods: ["phone", "cookie"],
      defaultMethod: "phone",
      privateFeatures: { phoneAuth: true, cookieAuth: false, reviews: false },
      hasPrivatePackage: true,
    })

    ;(api.loginPhoneRequestCode as any).mockResolvedValue({
      ok: true,
      sessionId: "sess_pending",
      nextAction: "verify_code",
    })

    ;(api.loginPhoneVerify as any).mockResolvedValue({
      ok: true,
      authenticated: false,
      authStatus: "pending",
      message: "Cookie 已保存，但用户中心未识别登录态",
    })

    renderDialog({ pluginId: "qidian_com_app", onSuccess })

    await waitFor(() => {
      expect(screen.getByRole("tab", { name: /手机号/i })).toBeInTheDocument()
    })

    await user.type(screen.getByPlaceholderText(/请输入手机号/), "13800138000")
    await user.click(screen.getByRole("button", { name: /获取验证码/ }))
    await user.type(screen.getByPlaceholderText(/请输入短信验证码/), "123456")
    await user.click(screen.getByRole("button", { name: /^登录$/ }))

    await waitFor(() => {
      expect(onSuccess).toHaveBeenCalled()
    })
  })
})
