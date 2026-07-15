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

function explicitLoginIdentity(result: any): string {
  return String(
    result?.accountName
      || result?.phoneMasked
      || result?.mobileMasked
      || result?.mobilePhone
      || result?.phoneNumber
      || result?.phone
      || ""
  ).trim()
}

function isLoginAccepted(result: any): boolean {
  return Boolean(result?.ok) && Boolean(result?.authenticated) && Boolean(explicitLoginIdentity(result))
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

  // Cookie login state
  const [cookieText, setCookieText] = useState("")
  const [verifyingCookie, setVerifyingCookie] = useState(false)

  // Shared state
  const [error, setError] = useState("")
  const [success, setSuccess] = useState("")

  // Load capabilities when dialog opens
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (!open) return
    let cancelled = false
    setCaps(null)
    setLoadingCaps(true)
    setActiveMethod("")
    setError("")
    setSuccess("")
    setPhone("")
    setSmsCode("")
    setSessionId("")
    setCookieText("")
    setSendingSms(false)
    setVerifying(false)
    setVerifyingCookie(false)
    setCountdown(0)

    api
      .loginCapabilities(pluginId)
      .then((data) => {
        if (cancelled) return
        setCaps(data)
        setActiveMethod(data.defaultMethod || data.methods[0] || "")
      })
      .catch((err) => {
        if (cancelled) return
        setError(`获取登录能力失败: ${err.message}`)
      })
      .finally(() => {
        if (!cancelled) setLoadingCaps(false)
      })
    return () => {
      cancelled = true
    }
  }, [open, pluginId])
  /* eslint-enable react-hooks/set-state-in-effect */

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
            if (res.ret === 0) {
              callback(res.ticket, res.randstr)
            } else {
              setError("滑块验证未完成")
            }
          })
          captcha.show()
        } catch (err: any) {
          setError(`滑块验证初始化失败: ${err.message || "未知错误"}`)
        }
      }

      if (win.TencentCaptcha) {
        createCaptcha()
        return
      }

      // Fallback: load Tencent Captcha JS dynamically
      const script = document.createElement("script")
      script.src = "https://turing.captcha.qcloud.com/TCaptcha.js"
      script.async = true
      script.onload = () => {
        if (win.TencentCaptcha) {
          createCaptcha()
        } else {
          setError("滑块验证组件加载后未找到构造函数")
        }
      }
      script.onerror = () => {
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
    setSuccess("")
    setSendingSms(true)

    try {
      const result = await api.loginPhoneRequestCode(pluginId, { phone })

      if (!result.ok) {
        // Check if challenge required
        if (result.nextAction === "complete_challenge" && result.challenge) {
          const challenge = result.challenge
          // Reject challenges without usable captcha data
          const captchaUrl = challenge.captchaUrl || challenge.url || ""
          const isTencentCaptcha =
            challenge.type === "tencent_captcha" ||
            challenge.captchaType === 1 ||
            captchaUrl.includes("TCaptcha.js")
          if (!captchaUrl && !isTencentCaptcha) {
            const msg = result.error || "无法加载滑块验证，请稍后重试或使用其他登录方式"
            setError(msg)
            setSendingSms(false)
            return
          }
          const appId = challenge.appId || "1600000770"
          showTencentCaptcha(appId, async (ticket, randstr) => {
            // After captcha, retry request with challenge token
            setSendingSms(true)
            try {
              const retryResult = await api.loginPhoneRequestCode(pluginId, {
                phone,
                challengeToken: ticket,
                challengeRandstr: randstr,
                sessionId: result.sessionId,
              })
              if (retryResult.ok) {
                setSessionId(retryResult.sessionId)
                setCountdown(60)
                setSuccess("验证码已发送")
              } else {
                setError(formatLoginError(retryResult.error, retryResult.errorCode))
              }
            } catch (err: any) {
              setError(`发送失败: ${err.message}`)
            } finally {
              setSendingSms(false)
            }
          })
        } else {
          setError(formatLoginError(result.error, result.errorCode))
        }
        return
      }

      setSessionId(result.sessionId)
      setCountdown(60)
      setSuccess("验证码已发送")
    } catch (err: any) {
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
    setSuccess("")
    setVerifying(true)

    try {
      const result = await api.loginPhoneVerify(pluginId, {
        sessionId,
        phone,
        code: smsCode,
      })

      if (isLoginAccepted(result)) {
        const accountName = explicitLoginIdentity(result)
        setSuccess(`登录成功 - ${accountName}`)
        onSuccess?.()
        setTimeout(() => onOpenChange(false), 1500)
      } else {
        setError(result.message || result.error || "登录未返回用户名或登录手机号，暂不判定为成功")
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
    setSuccess("")
    setVerifyingCookie(true)

    try {
      const result = await api.loginCookieVerify(pluginId, { cookieText: cookieText.trim() })

      if (isLoginAccepted(result)) {
        const accountName = explicitLoginIdentity(result)
        setSuccess(`Cookie 验证通过 - ${accountName}`)
        onSuccess?.()
        setTimeout(() => onOpenChange(false), 1500)
      } else {
        setError(result.message || result.error || "Cookie 未返回用户名或登录手机号，暂不判定为成功")
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
              <Alert className="border-primary/30 bg-primary/10 text-sm">
                <CheckCircle className="h-4 w-4 text-primary" />
                <AlertDescription className="text-primary">{success}</AlertDescription>
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
