import { useCallback, useEffect, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, LogIn, LogOut, RefreshCw, XCircle, Monitor, ShieldCheck } from "lucide-react"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { OfficialSourceLoginDialog } from "@/components/auth/OfficialSourceLoginDialog"

const TERMINAL_LOGIN_STATUSES = new Set(["success", "pending", "failed", "timeout", "cancelled", "none"])

export function OfficialSourcesPage() {
  const queryClient = useQueryClient()
  const { data, isLoading, error: queryError, refetch } = useQuery({ queryKey: ["official-sources"], queryFn: api.officialSources, refetchInterval: 5000 })
  const [loginSession, setLoginSession] = useState<any>(null)
  const [loginDialogOpen, setLoginDialogOpen] = useState(false)
  const [selectedPlugin, setSelectedPlugin] = useState<{ id: string; name: string } | null>(null)
  const [operationError, setOperationError] = useState("")
  const intervalRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const refreshMutation = useMutation({
    mutationFn: ({ pluginId }: { pluginId: string; name: string }) => api.pluginAuthCheck(pluginId),
    onMutate: () => setOperationError(""),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["official-sources"] }),
    onError: (_err, { name }) => setOperationError(`${name} 登录状态刷新失败，请稍后重试。`),
  })
  const globalRefreshMutation = useMutation({
    mutationFn: (pluginIds: string[]) => Promise.all(pluginIds.map(api.pluginAuthCheck)),
    onMutate: () => setOperationError(""),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["official-sources"] }),
    onError: () => setOperationError("官方源登录状态刷新失败，请稍后重试。"),
  })
  const logoutMutation = useMutation({
    mutationFn: ({ pluginId }: { pluginId: string; name: string }) => api.loginLogout(pluginId),
    onMutate: () => setOperationError(""),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["official-sources"] }),
    onError: (_err, { name }) => setOperationError(`${name} 注销失败，请稍后重试。`),
  })
  const clearCookiesMutation = useMutation({
    mutationFn: ({ pluginId }: { pluginId: string; name: string }) => api.pluginCookiesClear(pluginId),
    onMutate: () => setOperationError(""),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["official-sources"] }),
    onError: (_err, { name }) => setOperationError(`${name} Cookie 清除失败，请稍后重试。`),
  })
  const cancelLoginMutation = useMutation({
    mutationFn: (pluginId: string) => api.cancelLoginBrowser(pluginId),
    onMutate: () => {
      setOperationError("")
      setLoginSession((current: any) => current ? { ...current, status: "cancelling", message: "正在取消登录...", polling: false } : current)
    },
    onSuccess: (result, pluginId) => {
      setLoginSession({
        pluginId,
        status: result?.cancelled ? "cancelled" : "failed",
        message: result?.cancelled ? "登录已取消" : "取消失败：没有活跃的登录会话",
        polling: false,
      })
    },
    onError: (err, pluginId) => setLoginSession({
      pluginId,
      status: "failed",
      message: err instanceof Error ? err.message : "取消登录失败",
      polling: false,
    }),
  })

  const startBrowserLogin = useCallback(async (pluginId: string) => {
    if (loginSession?.polling || cancelLoginMutation.isPending) return
    setOperationError("")
    setLoginSession({
      pluginId,
      status: "starting",
      message: "正在启动浏览器登录...",
      polling: true,
    })
    try {
      const result = await api.startLoginBrowser(pluginId)
      if (result?.error) throw new Error(result.error)
      const status = result.status || "running"
      setLoginSession({
        pluginId,
        status,
        message: result.message || "请在浏览器窗口完成登录",
        polling: !TERMINAL_LOGIN_STATUSES.has(status),
      })
      if (status === "success") {
        queryClient.invalidateQueries({ queryKey: ["official-sources"] })
      }
    } catch (err) {
      setLoginSession({
        pluginId,
        status: "failed",
        message: err instanceof Error ? err.message : "浏览器登录启动失败",
        polling: false,
      })
    }
  }, [cancelLoginMutation.isPending, loginSession?.polling, queryClient])

  useEffect(() => {
    const handleBrowserLogin = (event: Event) => {
      const pluginId = (event as CustomEvent<{ pluginId?: string }>).detail?.pluginId
      if (pluginId) void startBrowserLogin(pluginId)
    }
    window.addEventListener("official-source-browser-login", handleBrowserLogin)
    return () => window.removeEventListener("official-source-browser-login", handleBrowserLogin)
  }, [startBrowserLogin])

  useEffect(() => {
    if (!loginSession?.polling || !loginSession.pluginId) return
    let active = true
    const poll = async () => {
      try {
        const result = await api.getLoginBrowserStatus(loginSession.pluginId)
        if (!active) return
        if (result?.error) throw new Error(result.error)
        const status = result.status || "failed"
        const polling = !TERMINAL_LOGIN_STATUSES.has(status)
        setLoginSession({ pluginId: loginSession.pluginId, status, message: result.message || "登录中...", polling })
        if (status === "success") queryClient.invalidateQueries({ queryKey: ["official-sources"] })
        if (polling) intervalRef.current = setTimeout(poll, 3000)
      } catch (err) {
        if (!active) return
        setLoginSession({
          pluginId: loginSession.pluginId,
          status: "failed",
          message: err instanceof Error ? err.message : "登录状态查询失败",
          polling: false,
        })
      }
    }
    intervalRef.current = setTimeout(poll, 3000)
    return () => {
      active = false
      if (intervalRef.current) clearTimeout(intervalRef.current)
      intervalRef.current = null
    }
  }, [loginSession?.pluginId, loginSession?.polling, queryClient])

  const items = data?.items || []
  const validCount = items.filter((i: any) => i.authStatus?.authenticated).length
  const invalidCount = items.length - validCount
  const browserLoginBusy = Boolean(loginSession?.polling) || cancelLoginMutation.isPending
  const confirmLogout = (item: any) => {
    if (window.confirm(`确定注销 ${item.name}？已保存的登录状态将被清除。`)) {
      logoutMutation.mutate({ pluginId: item.pluginId, name: item.name })
    }
  }
  const confirmClearCookies = (item: any) => {
    if (window.confirm(`确定清除 ${item.name} 的 Cookie？清除后需要重新登录。`)) {
      clearCookiesMutation.mutate({ pluginId: item.pluginId, name: item.name })
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">官方源管理</h1>
          <p className="mt-1 text-sm text-slate-500">管理正版官方书源的登录态与 Cookie 注入。</p>
        </div>
        <Button
          variant="outline"
          aria-busy={globalRefreshMutation.isPending}
          disabled={isLoading || Boolean(queryError) || globalRefreshMutation.isPending || refreshMutation.isPending || items.length === 0}
          onClick={() => globalRefreshMutation.mutate(items.map((item: any) => item.pluginId))}
        >
          <RefreshCw className={`h-4 w-4 mr-2 ${globalRefreshMutation.isPending ? "animate-spin" : ""}`} />
          {globalRefreshMutation.isPending ? "刷新中..." : "全局刷新状态"}
        </Button>
      </div>

      {queryError && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="flex-1">官方源加载失败，请稍后重试。</span>
          <Button type="button" size="sm" variant="outline" onClick={() => { void refetch() }}>重试</Button>
        </div>
      )}

      {operationError && (
        <div role="alert" className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{operationError}</span>
        </div>
      )}

      {isLoading ? (
        <div role="status" className="py-10 text-center text-sm text-slate-500">正在加载官方源...</div>
      ) : !queryError && (
        <>
      <div className="grid md:grid-cols-3 gap-4 mb-6">
        <Card className="bg-slate-800 text-white border-slate-700">
          <CardContent className="p-6">
            <div className="flex justify-between items-start">
              <div><p className="text-slate-400 text-sm">已配置官方源</p><h3 className="text-3xl font-bold mt-2">{items.length}</h3></div>
              <ShieldCheck className="h-8 w-8 text-slate-500 opacity-50" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6"><div className="flex justify-between items-start"><div><p className="text-slate-500 text-sm">有效登录</p><h3 className="text-3xl font-bold mt-2 text-emerald-600">{validCount}</h3></div></div></CardContent>
        </Card>
        <Card>
          <CardContent className="p-6"><div className="flex justify-between items-start"><div><p className="text-slate-500 text-sm">失效 / 未登录</p><h3 className="text-3xl font-bold mt-2 text-rose-500">{invalidCount}</h3></div></div></CardContent>
        </Card>
      </div>

      {loginSession && (
        <Card className={loginSession.polling ? "border-blue-300 bg-blue-50/30" : ""}>
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div><div className="font-medium text-sm">{loginSession.polling ? "正在登录" : "登录结果"}</div><div className="text-xs text-slate-500">{loginSession.message}</div></div>
              </div>
              {loginSession.polling && <Button size="sm" variant="outline" disabled={cancelLoginMutation.isPending} onClick={() => cancelLoginMutation.mutate(loginSession.pluginId)}><XCircle className="w-3 h-3 mr-1" /> 取消</Button>}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
          <CardHeader><CardTitle>官方源列表</CardTitle><CardDescription>需要认证才能获取完整正文或VIP章节的官方源。</CardDescription></CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称/标识</TableHead>
                  <TableHead>认证模式</TableHead>
                  <TableHead>账号状态</TableHead>
                  <TableHead>当前账号</TableHead>
                  <TableHead>最后检查</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="py-10 text-center text-sm text-slate-500">暂无已配置的官方源</TableCell>
                  </TableRow>
                )}
                {items.map((item: any) => {
                  const auth = item.authStatus || {}
                  const isCurrentSession = loginSession?.pluginId === item.pluginId
                  const isRefreshing = refreshMutation.isPending && refreshMutation.variables?.pluginId === item.pluginId
                  const isLoggingOut = logoutMutation.isPending && logoutMutation.variables?.pluginId === item.pluginId
                  const isClearing = clearCookiesMutation.isPending && clearCookiesMutation.variables?.pluginId === item.pluginId
                  return (
                    <TableRow key={item.pluginId}>
                      <TableCell>
                        <div className="font-medium text-slate-900 flex items-center gap-2">
                          {item.name}
                          <Badge variant="secondary" className="text-xs"><ShieldCheck className="w-3 h-3 mr-1" />官方</Badge>
                        </div>
                      </TableCell>
                      <TableCell><Badge variant="outline">{item.auth?.mode || "none"}</Badge></TableCell>
                      <TableCell>
                        {auth.authenticated ? <Badge variant="success">有效</Badge>
                         : auth.hasCookies ? <Badge variant="secondary">待校验</Badge>
                         : <Badge variant="secondary">未登录</Badge>}
                      </TableCell>
                      <TableCell className="text-sm text-slate-600">{auth.accountName || "-"}</TableCell>
                      <TableCell className="text-sm text-slate-500">{auth.lastCheckedAt || "-"}</TableCell>
                      <TableCell className="text-right">
                        <div className="flex justify-end gap-2">
                          {auth.authenticated ? (
                            <Button type="button" aria-label={`注销 ${item.name}`} aria-busy={isLoggingOut} title="注销" variant="ghost" size="sm" className="h-8" disabled={isLoggingOut} onClick={() => confirmLogout(item)}><LogOut className={`h-4 w-4 ${isLoggingOut ? "animate-pulse" : ""}`} /></Button>
                          ) : (
                            <Button variant="outline" size="sm" className="h-8" disabled={browserLoginBusy} onClick={() => { setSelectedPlugin({ id: item.pluginId, name: item.name }); setLoginDialogOpen(true) }}>
                              {isCurrentSession && loginSession?.polling ? <><Monitor className="h-3 w-3 mr-1 animate-pulse" /> 登录中...</> : <><LogIn className="h-3 w-3 mr-1" /> 登录</>}
                            </Button>
                          )}
                          {!auth.authenticated && auth.hasCookies && (
                            <Button type="button" aria-label={`清除 ${item.name} Cookie`} aria-busy={isClearing} title="清除 Cookie" variant="ghost" size="sm" className="h-8" disabled={isClearing} onClick={() => confirmClearCookies(item)}><XCircle className={`h-4 w-4 ${isClearing ? "animate-pulse" : ""}`} /></Button>
                          )}
                          <Button type="button" aria-label={`刷新 ${item.name} 登录状态`} aria-busy={isRefreshing} title="刷新登录状态" variant="ghost" size="sm" className="h-8" disabled={refreshMutation.isPending || globalRefreshMutation.isPending} onClick={() => refreshMutation.mutate({ pluginId: item.pluginId, name: item.name })}><RefreshCw className={`h-4 w-4 ${isRefreshing ? "animate-spin" : ""}`} /></Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
      </Card>
        </>
      )}

      {selectedPlugin && loginDialogOpen && (
        <OfficialSourceLoginDialog key={selectedPlugin.id} pluginId={selectedPlugin.id} sourceName={selectedPlugin.name} open={loginDialogOpen} onOpenChange={setLoginDialogOpen}
          onSuccess={() => { queryClient.invalidateQueries({ queryKey: ["official-sources"] }) }} />
      )}
    </div>
  )
}
