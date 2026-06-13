import { useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ShieldCheck, RefreshCw, LogIn, LogOut, Monitor, XCircle, CheckCircle, Clock, AlertCircle } from "lucide-react"

import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { OfficialSourceLoginDialog } from "@/components/auth/OfficialSourceLoginDialog"

interface LoginSession {
  pluginId: string
  status: string
  message: string
  polling: boolean
}

function translateLoginMode(mode: string): string {
  switch (mode) {
    case "none":
      return "无需登录"
    case "optional":
      return "可选登录"
    case "required":
      return "必须登录"
    case "manual":
      return "手动登录"
    default:
      return mode || "未知"
  }
}

function translateContentAccess(access: string): string {
  switch (access) {
    case "free":
      return "免费"
    case "paid":
      return "付费"
    case "mixed":
      return "混合"
    case "unknown":
    default:
      return access || "未知"
  }
}

function translateAccountStatus(auth: any): { label: string; variant: "success" | "outline" | "destructive" | "secondary" } {
  if (auth.authenticated) {
    return { label: "已登录", variant: "success" }
  }

  const status = auth.authStatus
  const hasCookies = Boolean(auth.hasCookies)
  const accountName = auth.accountName
  const requiresCheck = Array.isArray(auth.requiredActions) && auth.requiredActions.includes("check_auth_status")

  // Has cookies but still needs server-side verification.
  if (hasCookies && (requiresCheck || status === "pending")) {
    return { label: accountName ? "登录态待确认" : "待校验", variant: "outline" }
  }

  // Cookies saved but auth state not yet verified.
  if (hasCookies && (!status || status === "unknown")) {
    return { label: "已保存 Cookie", variant: "secondary" }
  }

  // Explicit anonymous / no-cookie state.
  if (!hasCookies || status === "anonymous") {
    return { label: "未登录", variant: "outline" }
  }

  return { label: "未登录", variant: "outline" }
}

export function OfficialSourcesPage() {
  const queryClient = useQueryClient()
  const { data, isLoading, refetch } = useQuery({
    queryKey: ["official-sources"],
    queryFn: api.officialSources,
    refetchInterval: 5000,
  })

  const [loginSession, setLoginSession] = useState<LoginSession | null>(null)
  const [loginDialogOpen, setLoginDialogOpen] = useState(false)
  const [selectedPlugin, setSelectedPlugin] = useState<{ id: string; name: string } | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const refreshMutation = useMutation({
    mutationFn: (pluginId: string) => api.pluginAuthCheck(pluginId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["official-sources"] }),
  })

  const logoutMutation = useMutation({
    mutationFn: (pluginId: string) => api.loginLogout(pluginId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["official-sources"] }),
  })

  const clearCookiesMutation = useMutation({
    mutationFn: (pluginId: string) => api.pluginCookiesClear(pluginId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["official-sources"] }),
  })

  // Poll login-browser status
  useEffect(() => {
    if (!loginSession?.polling) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
      return
    }

    intervalRef.current = setInterval(async () => {
      try {
        const result = await api.getLoginBrowserStatus(loginSession.pluginId)
        const status = result.status

        if (status === "success") {
          setLoginSession({
            pluginId: loginSession.pluginId,
            status: "success",
            message: result.message || "登录成功",
            polling: false,
          })
          refreshMutation.mutate(loginSession.pluginId)
        } else if (["failed", "timeout", "cancelled", "none"].includes(status)) {
          setLoginSession({
            pluginId: loginSession.pluginId,
            status,
            message: result.message || "登录未完成",
            polling: false,
          })
        } else {
          setLoginSession({
            pluginId: loginSession.pluginId,
            status,
            message: result.message || "登录中...",
            polling: true,
          })
        }
      } catch {
        // Keep polling on transient errors
      }
    }, 3000)

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [loginSession?.polling, loginSession?.pluginId])

  // Listen for browser-login event from dialog
  useEffect(() => {
    const handler = (e: CustomEvent) => {
      const { pluginId } = e.detail
      handleBrowserLogin(pluginId)
    }
    window.addEventListener("official-source-browser-login", handler as EventListener)
    return () => window.removeEventListener("official-source-browser-login", handler as EventListener)
  }, [loginSession])

  const handleOpenLoginDialog = (pluginId: string, name: string) => {
    setSelectedPlugin({ id: pluginId, name })
    setLoginDialogOpen(true)
  }

  const handleBrowserLogin = async (pluginId: string) => {
    // Cancel any previous session first
    if (loginSession?.polling) {
      await api.cancelLoginBrowser(loginSession.pluginId)
    }
    setLoginSession({ pluginId, status: "pending", message: "正在启动浏览器...", polling: true })
    try {
      await api.startLoginBrowser(pluginId)
    } catch (err: any) {
      setLoginSession({ pluginId, status: "failed", message: `启动失败: ${err.message}`, polling: false })
    }
  }

  const handleCancel = async () => {
    if (!loginSession) return
    await api.cancelLoginBrowser(loginSession.pluginId)
    setLoginSession({ ...loginSession, status: "cancelled", message: "已取消", polling: false })
  }

  const items = data?.items || []

  const statusIcon = (status: string) => {
    switch (status) {
      case "success":
        return <CheckCircle className="w-4 h-4 text-green-500" />
      case "failed":
      case "timeout":
        return <XCircle className="w-4 h-4 text-red-500" />
      case "cancelled":
        return <AlertCircle className="w-4 h-4 text-amber-500" />
      case "running":
      case "pending":
        return <Clock className="w-4 h-4 text-blue-500 animate-pulse" />
      default:
        return null
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">官方源</h1>
          <p className="text-sm text-muted-foreground">管理官方书源的启用状态、登录状态与 Cookie</p>
        </div>
        <Badge variant="outline">{items.length} 个官方源</Badge>
      </div>

      {loginSession && (
        <Card className={loginSession.polling ? "border-blue-300 bg-blue-50/30" : ""}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {statusIcon(loginSession.status)}
                <div>
                  <div className="font-medium text-sm">
                    {loginSession.polling ? "正在登录" : "登录结果"}
                  </div>
                  <div className="text-xs text-muted-foreground">
                    {loginSession.status === "running" && "浏览器窗口已弹出，请在窗口中完成手机号验证和登录"}
                    {loginSession.status === "pending" && "正在启动浏览器..."}
                    {loginSession.status === "success" && "登录成功，Cookie 已保存"}
                    {loginSession.status === "failed" && loginSession.message}
                    {loginSession.status === "timeout" && loginSession.message}
                    {loginSession.status === "cancelled" && loginSession.message}
                  </div>
                </div>
              </div>
              {loginSession.polling && (
                <Button size="sm" variant="outline" onClick={handleCancel}>
                  <XCircle className="w-3 h-3 mr-1" />
                  取消
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="text-muted-foreground">加载中...</div>
      ) : items.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            暂无官方源
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">官方源管理</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称</TableHead>
                  <TableHead>版本</TableHead>
                  <TableHead>修改时间</TableHead>
                  <TableHead>登录模式</TableHead>
                  <TableHead>账号状态</TableHead>
                  <TableHead>账号名称</TableHead>
                  <TableHead>内容访问</TableHead>
                  <TableHead>最后检查</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((item: any) => {
                  const auth = item.authStatus || {}
                  const isCurrentSession = loginSession?.pluginId === item.pluginId
                  const accountStatus = translateAccountStatus(auth)
                  return (
                    <TableRow key={item.pluginId}>
                      <TableCell>
                        <div className="font-medium flex items-center gap-2">
                          {item.name}
                          <Badge variant="secondary" className="text-xs">
                            <ShieldCheck className="w-3 h-3 mr-1" />
                            官方
                          </Badge>
                        </div>
                      </TableCell>
                      <TableCell>{item.version || "-"}</TableCell>
                      <TableCell>{item.lastModified || "-"}</TableCell>
                      <TableCell>{translateLoginMode(item.auth?.mode)}</TableCell>
                      <TableCell>
                        <Badge variant={accountStatus.variant}>{accountStatus.label}</Badge>
                      </TableCell>
                      <TableCell>{auth.accountName || ""}</TableCell>
                      <TableCell>{translateContentAccess(item.content?.access)}</TableCell>
                      <TableCell>{auth.lastCheckedAt || "-"}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-2">
                          {auth.authenticated ? (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => logoutMutation.mutate(item.pluginId)}
                              disabled={logoutMutation.isPending}
                            >
                              <LogOut className="w-3 h-3 mr-1" />
                              注销
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              variant={isCurrentSession && loginSession?.polling ? "default" : "outline"}
                              disabled={isCurrentSession && loginSession?.polling}
                              onClick={() => handleOpenLoginDialog(item.pluginId, item.name)}
                            >
                              {isCurrentSession && loginSession?.polling ? (
                                <>
                                  <Monitor className="w-3 h-3 mr-1 animate-pulse" />
                                  登录中...
                                </>
                              ) : (
                                <>
                                  <LogIn className="w-3 h-3 mr-1" />
                                  登录
                                </>
                              )}
                            </Button>
                          )}
                          {!auth.authenticated && auth.hasCookies && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => clearCookiesMutation.mutate(item.pluginId)}
                              disabled={clearCookiesMutation.isPending}
                            >
                              <XCircle className="w-3 h-3 mr-1" />
                              清除
                            </Button>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => refreshMutation.mutate(item.pluginId)}
                          >
                            <RefreshCw className="w-3 h-3 mr-1" />
                            刷新状态
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {selectedPlugin && (
        <OfficialSourceLoginDialog
          pluginId={selectedPlugin.id}
          sourceName={selectedPlugin.name}
          open={loginDialogOpen}
          onOpenChange={setLoginDialogOpen}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ["official-sources"] })
          }}
        />
      )}
    </div>
  )
}
