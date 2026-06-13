import { useState, useEffect, useCallback } from "react"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Textarea } from "@/components/ui/textarea"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Loader2, Smartphone, Cookie, CheckCircle, AlertCircle, ShieldCheck } from "lucide-react"
import { api } from "@/lib/api"

function formatLoginError(message?: string, code?: number | string): string {
  if (message && code != null) return `${code}: ${message}`
  if (message) return message
  if (code != null) return `错误码 ${code}`
  return "登录请求失败"
}

// Types from backend login-capabilities response
interface LoginCapabilities {
  pluginId: string
  methods: string[]
  defaultMethod: string
  privateFeatures: {
    phoneAuth: boolean
    cookieAuth: boolean
    reviews: boolean
  }
  hasPrivatePackage: boolean
}

interface OfficialSourceLoginDialogProps {
  pluginId: string
  sourceName: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSuccess?: () => void
}

export function OfficialSourceLoginDialog({
  pluginId,
  sourceName,
  open,
  onOpenChange,
  onSuccess,
}: OfficialSourceLoginDialogProps) {
  const [caps, setCaps] = useState<LoginCapabilities | null>(null)
  const [loadingCaps, setLoadingCaps] = useState(false)
  const [activeMethod, setActiveMethod] = useState("")

  // Phone login state
  const [phone, setPhone] = useState("")
  const [smsCode, setSmsCode] = useState("")
  const [sessionId, setSessionId] = useState("")
  const [sendingSms, setSendingSms] = useState(false)
  const [verifying, setVerifying] = useState(false)
  const [countdown, setCountdown] = useState(0)
  const [challengeData, setChallengeData] = useState<any>(null)

  // Cookie login state
  const [cookieText, setCookieText] = useState("")
  const [verifyingCookie, setVerifyingCookie] = useState(false)

  // Shared state
  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  // Load capabilities when dialog opens
  useEffect(() => {
    if (!open) return
    setLoadingCaps(true)
    setError("")
    setSuccess("")
    setPhone("")
    setSmsCode("")
    setSessionId("")
    setCookieText("")
    setChallengeData(null)
    setCountdown(0)

    api
      .loginCapabilities(pluginId)
      .then((data) => {
        setCaps(data)
        setActiveMethod(data.defaultMethod || data.methods[0] || "")
      })
      .catch((err) => {
        setError(`获取登录能力失败: ${err.message}`)
      })
      .finally(() => setLoadingCaps(false))
  }, [open, pluginId])

  // Countdown timer for SMS resend
  useEffect(() => {
    if (countdown <= 0) return
    const timer = setInterval(() => setCountdown((c) => c - 1), 1000)
    return () => clearInterval(timer)
  }, [countdown])

  // Tencent Captcha integration
  const showTencentCaptcha = useCallback(
    (appId: string, callback: (ticket: string, randstr: string) => void) => {
      const win = window as any
      console.log("[captcha] existing TencentCaptcha:", !!win.TencentCaptcha)

      // Use a hidden body anchor so the popup is not tied to the dialog DOM.
      let container = document.getElementById("tencent-captcha-anchor")
      if (!container) {
        container = document.createElement("div")
        container.id = "tencent-captcha-anchor"
        container.style.position = "fixed"
        container.style.left = "-9999px"
        container.style.top = "-9999px"
        container.style.width = "0"
        container.style.height = "0"
        document.body.appendChild(container)
      }

      const createCaptcha = () => {
        try {
          const captcha = new win.TencentCaptcha(container, appId, (res: any) => {
            console.log("[captcha] result:", res)
            if (res.ret === 0) {
              callback(res.ticket, res.randstr)
            } else {
              setError("滑块验证未完成")
            }
          })
          console.log("[captcha] calling show()")
          captcha.show()
        } catch (err: any) {
          console.error("[captcha] constructor/show failed:", err)
          setError(`滑块验证初始化失败: ${err.message || "未知错误"}`)
        }
      }

      if (win.TencentCaptcha) {
        createCaptcha()
        return
      }

      // Fallback: load Tencent Captcha JS dynamically
      console.log("[captcha] loading script...")
      const script = document.createElement("script")
      script.src = "https://turing.captcha.qcloud.com/TCaptcha.js"
      script.async = true
      script.onload = () => {
        console.log("[captcha] script loaded, TencentCaptcha:", !!win.TencentCaptcha)
        if (win.TencentCaptcha) {
          createCaptcha()
        } else {
          setError("滑块验证组件加载后未找到构造函数")
        }
      }
      script.onerror = (err) => {
        console.error("[captcha] script load error:", err)
        setError("滑块验证组件加载失败，请检查网络或改用浏览器/Cookie 登录")
      }
      document.body.appendChild(script)
    },
    []
  )

  // Phone login: request SMS code
  const handleRequestCode = async () => {
    if (!phone || phone.length < 11) {
      setError("请输入有效的手机号")
      return
    }
    setError("")
    setSendingSms(true)

    try {
      const result = await api.loginPhoneRequestCode(pluginId, { phone })
      console.log("[login] request-code result:", result)

      if (!result.ok) {
        // Check if challenge required
        if (result.nextAction === "complete_challenge" && result.challenge) {
          const challenge = result.challenge
          console.log("[login] challenge:", challenge)
          // Reject challenges without usable captcha data
          const captchaUrl = challenge.captchaUrl || challenge.url || ""
          const isTencentCaptcha =
            challenge.type === "tencent_captcha" ||
            challenge.captchaType === 1 ||
            captchaUrl.includes("TCaptcha.js")
          if (!captchaUrl && !isTencentCaptcha) {
            const msg = result.error || "无法加载滑块验证，请稍后重试或使用其他登录方式"
            console.warn("[login] challenge has no usable captcha data")
            setError(msg)
            setSendingSms(false)
            return
          }
          setChallengeData(challenge)
          const appId = challenge.appId || "1600000770"
          console.log("[login] showing tencent captcha, appId:", appId)
          showTencentCaptcha(appId, async (ticket, randstr) => {
            console.log("[login] captcha completed, retrying request-code")
            // After captcha, retry request with challenge token
            try {
              const retryResult = await api.loginPhoneRequestCode(pluginId, {
                phone,
                challengeToken: ticket,
                challengeRandstr: randstr,
                sessionId: result.sessionId,
              })
              console.log("[login] retry request-code result:", retryResult)
              if (retryResult.ok) {
                setSessionId(retryResult.sessionId)
                setCountdown(60)
                setSuccess("验证码已发送")
              } else {
                setError(formatLoginError(retryResult.error, retryResult.errorCode))
              }
            } catch (err: any) {
              console.error("[login] retry request-code failed:", err)
              setError(`发送失败: ${err.message}`)
            }
          })
        } else {
          console.warn("[login] request-code failed:", result.error)
          setError(formatLoginError(result.error, result.errorCode))
        }
        return
      }

      setSessionId(result.sessionId)
      setCountdown(60)
      setSuccess("验证码已发送")
    } catch (err: any) {
      console.error("[login] request-code exception:", err)
      setError(`发送失败: ${err.message}`)
    } finally {
      setSendingSms(false)
    }
  }

  // Phone login: verify code
  const handlePhoneVerify = async () => {
    if (!sessionId) {
      setError("请先获取验证码")
      return
    }
    if (!smsCode || smsCode.length < 4) {
      setError("请输入短信验证码")
      return
    }
    setError("")
    setVerifying(true)

    try {
      const result = await api.loginPhoneVerify(pluginId, {
        sessionId,
        phone,
        code: smsCode,
      })

      if (result.ok && result.authenticated) {
        setSuccess(`登录成功${result.accountName ? ` - ${result.accountName}` : ""}`)
        onSuccess?.()
        setTimeout(() => onOpenChange(false), 1500)
      } else {
        setError(result.message || result.error || "登录失败")
      }
    } catch (err: any) {
      setError(`登录失败: ${err.message}`)
    } finally {
      setVerifying(false)
    }
  }

  // Cookie login: verify
  const handleCookieVerify = async () => {
    if (!cookieText.trim()) {
      setError("请粘贴 Cookie 文本")
      return
    }
    setError("")
    setVerifyingCookie(true)

    try {
      const result = await api.loginCookieVerify(pluginId, { cookieText: cookieText.trim() })

      if (result.ok && result.authenticated) {
        setSuccess(`Cookie 验证通过${result.accountName ? ` - ${result.accountName}` : ""}`)
        onSuccess?.()
        setTimeout(() => onOpenChange(false), 1500)
      } else {
        setError(result.message || result.error || "Cookie 验证失败")
      }
    } catch (err: any) {
      setError(`验证失败: ${err.message}`)
    } finally {
      setVerifyingCookie(false)
    }
  }

  const methods = caps?.methods || []
  const hasPhone = methods.includes("phone")
  const hasCookie = methods.includes("cookie")
  const hasBrowser = methods.includes("browser")

  return (
    <Dialog open={open} onOpenChange={onOpenChange} modal={false}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ShieldCheck className="w-5 h-5" />
            {sourceName} 登录
          </DialogTitle>
          <DialogDescription>
            {hasPhone
              ? "选择登录方式完成认证"
              : "Cookie 登录始终可用；手机号验证码登录需要安装私有插件"}
          </DialogDescription>
        </DialogHeader>

        {loadingCaps && (
          <div className="flex items-center gap-2 text-muted-foreground py-4">
            <Loader2 className="w-4 h-4 animate-spin" />
            加载登录能力...
          </div>
        )}

        {!loadingCaps && !caps && (
          <Alert variant="destructive">
            <AlertCircle className="w-4 h-4" />
            <AlertDescription>无法获取登录能力，请刷新重试</AlertDescription>
          </Alert>
        )}

        {caps && (
          <>
            {error && (
              <Alert variant="destructive" className="text-sm">
                <AlertCircle className="w-4 h-4" />
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            {success && (
              <Alert className="bg-green-50 border-green-200 text-sm">
                <CheckCircle className="w-4 h-4 text-green-600" />
                <AlertDescription className="text-green-700">{success}</AlertDescription>
              </Alert>
            )}

            <Tabs value={activeMethod} onValueChange={setActiveMethod}>
              <TabsList className="grid w-full" style={{ gridTemplateColumns: `repeat(${methods.length}, 1fr)` }}>
                {hasPhone && (
                  <TabsTrigger value="phone">
                    <Smartphone className="w-3 h-3 mr-1" />
                    手机号
                  </TabsTrigger>
                )}
                {hasCookie && (
                  <TabsTrigger value="cookie">
                    <Cookie className="w-3 h-3 mr-1" />
                    Cookie
                  </TabsTrigger>
                )}
                {hasBrowser && (
                  <TabsTrigger value="browser">
                    <ShieldCheck className="w-3 h-3 mr-1" />
                    浏览器
                  </TabsTrigger>
                )}
              </TabsList>

              {hasPhone && (
                <TabsContent value="phone" className="space-y-4 mt-4">
                  <div className="space-y-2">
                    <Label htmlFor="phone">手机号</Label>
                    <div className="flex gap-2">
                      <Input
                        id="phone"
                        type="tel"
                        placeholder="请输入手机号"
                        value={phone}
                        onChange={(e) => setPhone(e.target.value)}
                        disabled={sendingSms || verifying}
                      />
                      <Button
                        onClick={handleRequestCode}
                        disabled={sendingSms || countdown > 0 || verifying}
                        variant="outline"
                        className="shrink-0"
                      >
                        {sendingSms ? (
                          <Loader2 className="w-4 h-4 animate-spin" />
                        ) : countdown > 0 ? (
                          `${countdown}s`
                        ) : (
                          "获取验证码"
                        )}
                      </Button>
                    </div>
                  </div>

                  {sessionId && (
                    <div className="space-y-2">
                      <Label htmlFor="smsCode">短信验证码</Label>
                      <Input
                        id="smsCode"
                        type="text"
                        placeholder="请输入短信验证码"
                        value={smsCode}
                        onChange={(e) => setSmsCode(e.target.value)}
                        disabled={verifying}
                        maxLength={6}
                      />
                    </div>
                  )}

                  <Button
                    onClick={handlePhoneVerify}
                    disabled={!sessionId || !smsCode || verifying}
                    className="w-full"
                  >
                    {verifying ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        登录中...
                      </>
                    ) : (
                      "登录"
                    )}
                  </Button>
                </TabsContent>
              )}

              {hasCookie && (
                <TabsContent value="cookie" className="space-y-4 mt-4">
                  <div className="space-y-2">
                    <Label htmlFor="cookieText">Cookie 文本</Label>
                    <Textarea
                      id="cookieText"
                      placeholder="粘贴完整的 Cookie 字符串，如：ywguid=xxx; ywkey=xxx; _csrfToken=xxx"
                      value={cookieText}
                      onChange={(e) => setCookieText(e.target.value)}
                      rows={4}
                      disabled={verifyingCookie}
                    />
                    <p className="text-xs text-muted-foreground">
                      从浏览器开发者工具的 Application &gt; Cookies 中复制完整 Cookie 字符串粘贴
                    </p>
                  </div>

                  <Button
                    onClick={handleCookieVerify}
                    disabled={!cookieText.trim() || verifyingCookie}
                    className="w-full"
                  >
                    {verifyingCookie ? (
                      <>
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                        验证中...
                      </>
                    ) : (
                      "验证登录"
                    )}
                  </Button>
                </TabsContent>
              )}

              {hasBrowser && (
                <TabsContent value="browser" className="space-y-4 mt-4">
                  <div className="text-sm text-muted-foreground space-y-2">
                    <p>浏览器登录方式需要弹出窗口完成滑块验证和短信登录。</p>
                    <p>此方式不依赖私有插件，但需手动操作浏览器窗口。</p>
                  </div>
                  <Button
                    variant="outline"
                    className="w-full"
                    onClick={() => {
                      onOpenChange(false)
                      // Emit event for parent to handle browser login
                      window.dispatchEvent(
                        new CustomEvent("official-source-browser-login", {
                          detail: { pluginId },
                        })
                      )
                    }}
                  >
                    启动浏览器登录
                  </Button>
                </TabsContent>
              )}
            </Tabs>

            {!hasPhone && !hasCookie && !hasBrowser && (
              <div className="text-center py-4 text-muted-foreground text-sm">
                暂无可用的登录方式
                <br />
                Cookie 登录异常不可用，请检查系统配置
              </div>
            )}
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
