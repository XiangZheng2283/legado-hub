import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { BookOpen, KeyRound, Loader2, ShieldCheck } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { apiErrorMessage } from "@/lib/api"
import { useAuth } from "@/lib/auth"

export function LoginPage() {
  const navigate = useNavigate()
  const { user, entrypoint, isLoading, authError, retryAuth, login, loginWithAccessCode } = useAuth()
  const [mode, setMode] = useState<"access" | "admin">("access")
  const [accessCode, setAccessCode] = useState("")
  const [username, setUsername] = useState("admin")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const effectiveEntrypoint = entrypoint || "combined"
  const effectiveMode = effectiveEntrypoint === "admin" ? "admin" : effectiveEntrypoint === "public" ? "access" : mode

  useEffect(() => {
    if (!isLoading && user) {
      navigate("/console", { replace: true })
    }
  }, [isLoading, navigate, user])

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (effectiveMode === "access" && !accessCode.trim()) {
      setError("请输入授权码")
      return
    }
    if (effectiveMode === "admin" && (!username.trim() || !password)) {
      setError("请输入管理员用户名和密码")
      return
    }
    setSubmitting(true)
    try {
      if (effectiveMode === "access") {
        await loginWithAccessCode(accessCode.trim())
        setAccessCode("")
      } else {
        await login(username.trim(), password)
        setPassword("")
      }
      navigate("/console", { replace: true })
    } catch (loginError) {
      setError(apiErrorMessage(loginError, "登录失败，请稍后重试。"))
    } finally {
      setSubmitting(false)
    }
  }

  const loginForm = (
    <form onSubmit={handleSubmit} className="space-y-4">
      {effectiveMode === "access" ? (
        <div className="space-y-2">
          <Label htmlFor="access-code">授权码</Label>
          <Input
            id="access-code"
            type="password"
            value={accessCode}
            onChange={(e) => setAccessCode(e.target.value)}
            autoComplete="current-password"
            autoFocus
          />
        </div>
      ) : (
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="username">用户名</Label>
            <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
          </div>
          <div className="space-y-2">
            <Label htmlFor="password">密码</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </div>
        </div>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <Button
        type="submit"
        className="w-full"
        disabled={submitting}
      >
        {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
        {effectiveMode === "access" ? "使用授权码登录" : "管理员登录"}
      </Button>
    </form>
  )

  return (
    <div className="min-h-screen flex flex-col items-center justify-center gap-6 bg-background p-4">
      <div className="flex items-center gap-2.5">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <BookOpen className="h-5 w-5" />
        </div>
        <span className="text-xl font-semibold tracking-tight text-foreground">LegadoHub</span>
      </div>

      <Card className="w-full max-w-sm border-border bg-card shadow-sm">
        <CardHeader className="space-y-1">
          <CardTitle className="text-lg">{effectiveEntrypoint === "admin" ? "管理员登录" : "登录 LegadoHub"}</CardTitle>
          <CardDescription>
            {effectiveEntrypoint === "public"
              ? "输入个人授权码，进入订阅和书库。"
              : effectiveEntrypoint === "admin"
                ? "使用管理员账户进入系统控制台。"
                : "受邀用户使用个人授权码，管理员使用管理账户。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {authError && (
            <Alert variant="destructive" className="mb-4">
              <AlertDescription className="space-y-3">
                <p>{authError}</p>
                <Button type="button" size="sm" variant="outline" onClick={() => { void retryAuth() }}>
                  重新连接
                </Button>
              </AlertDescription>
            </Alert>
          )}
          {effectiveEntrypoint === "combined" ? (
            <Tabs value={mode} onValueChange={(value) => { setMode(value as "access" | "admin"); setError(null) }}>
              <TabsList className="mb-4 grid w-full grid-cols-2">
                <TabsTrigger value="access"><KeyRound className="mr-2 h-4 w-4" />授权码</TabsTrigger>
                <TabsTrigger value="admin"><ShieldCheck className="mr-2 h-4 w-4" />管理员</TabsTrigger>
              </TabsList>
              {loginForm}
            </Tabs>
          ) : loginForm}
        </CardContent>
      </Card>
    </div>
  )
}
