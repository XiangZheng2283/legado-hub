import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery } from "@tanstack/react-query"
import { Loader2, Shield, User } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { api } from "@/lib/api"

export function LoginPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [isBootstrap, setIsBootstrap] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const { data: meData, isLoading: checking } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: api.auth.me,
    retry: false,
  })

  const bootstrapMutation = useMutation({
    mutationFn: api.auth.bootstrap,
    onSuccess: () => navigate("/console", { replace: true }),
    onError: (err: any) => setError(err?.message || "初始化失败"),
  })

  const loginMutation = useMutation({
    mutationFn: api.auth.login,
    onSuccess: () => navigate("/console", { replace: true }),
    onError: (err: any) => setError(err?.message || "登录失败"),
  })

  if (checking) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (meData?.user) {
    navigate("/console", { replace: true })
    return null
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!username || !password) {
      setError("请输入用户名和密码")
      return
    }
    if (isBootstrap) {
      bootstrapMutation.mutate({ username, password })
    } else {
      loginMutation.mutate({ username, password })
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader className="space-y-1">
          <div className="flex items-center gap-2">
            {isBootstrap ? <Shield className="w-5 h-5" /> : <User className="w-5 h-5" />}
            <CardTitle className="text-lg">
              {isBootstrap ? "初始化管理员账号" : "登录 LegadoHub"}
            </CardTitle>
          </div>
          <CardDescription>
            {isBootstrap
              ? "系统尚未创建用户，请先设置管理员账号。"
              : "请输入管理员账号登录控制台。"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="username">用户名</Label>
              <Input
                id="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="admin"
                autoComplete="username"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="password">密码</Label>
              <Input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                autoComplete={isBootstrap ? "new-password" : "current-password"}
              />
            </div>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <Button
              type="submit"
              className="w-full"
              disabled={loginMutation.isPending || bootstrapMutation.isPending}
            >
              {(loginMutation.isPending || bootstrapMutation.isPending) && (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              )}
              {isBootstrap ? "创建管理员" : "登录"}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="w-full text-xs"
              onClick={() => {
                setIsBootstrap(!isBootstrap)
                setError(null)
              }}
            >
              {isBootstrap ? "已有账号？去登录" : "首次使用？初始化账号"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
