import { useQuery } from "@tanstack/react-query"
import { Link, useNavigate } from "react-router-dom"
import { Activity, BookMarked, Database, Search, ShieldCheck, AlertCircle, BookOpen, ShieldAlert, RefreshCw } from "lucide-react"
import { api, apiErrorMessage } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription } from "@/components/ui/alert"

function formatUptime(value: unknown) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0))
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days} 天 ${hours} 小时`
  if (hours > 0) return `${hours} 小时 ${minutes} 分钟`
  if (minutes > 0) return `${minutes} 分钟`
  return `${seconds} 秒`
}

export function Dashboard() {
  const navigate = useNavigate()
  const { user, entrypoint } = useAuth()
  const isAdmin = entrypoint !== "public" && user?.role === "admin"

  const { data: statsData, isLoading: statsLoading, isFetching: statsFetching, error: statsError, refetch: refetchStats } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
    enabled: isAdmin,
    refetchInterval: 30_000,
  })

  if (isAdmin) {
    const stats = statsData || {}
    const pluginStats = stats.pluginStats || stats.plugins || {}
    const metric = (value: unknown) => statsLoading ? "加载中" : statsError ? "N/A" : String(value ?? 0)
    return (
      <div className="space-y-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">仪表盘</h1>
            <p className="mt-1 text-sm text-slate-500">欢迎回来，这是 LegadoHub 系统的当前状态。</p>
          </div>
          <Button type="button" variant="outline" size="sm" disabled={statsFetching} onClick={() => { void refetchStats() }}>
            <RefreshCw className={`mr-2 h-4 w-4 ${statsFetching ? "animate-spin" : ""}`} />
            {statsFetching ? "刷新中" : "刷新状态"}
          </Button>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">服务运行时间</CardTitle>
              <Activity className={`h-4 w-4 ${statsError ? "text-rose-500" : "text-blue-600"}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-slate-900">{statsLoading ? "加载中" : statsError ? "未知" : formatUptime(stats.uptimeSeconds)}</div>
              <p className="mt-1 text-xs text-slate-500">{statsLoading ? "正在读取状态" : statsError ? "状态接口暂时不可用" : `后端进程 · v${stats.version || "-"}`}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">书源总数</CardTitle>
              <Database className="h-4 w-4 text-slate-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-slate-900">{metric(pluginStats.total)}</div>
              <p className="mt-1 text-xs text-slate-500">启用 {metric(pluginStats.enabled)} · 停用 {metric(pluginStats.disabled)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">健康书源</CardTitle>
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-emerald-600">{metric(pluginStats.healthy)}</div>
              <p className="mt-1 text-xs text-slate-500">已检测 {metric(pluginStats.checked)} / {metric(pluginStats.enabled)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">异常书源</CardTitle>
              <AlertCircle className="h-4 w-4 text-rose-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-rose-600">{metric(pluginStats.unhealthy)}</div>
              <p className="mt-1 text-xs text-slate-500">{Number(pluginStats.unknown || 0) > 0 ? `另有 ${pluginStats.unknown} 个待检测` : Number(pluginStats.unhealthy || 0) > 0 ? "需要管理员检查" : "当前无异常"}</p>
            </CardContent>
          </Card>
        </div>
        {statsError && (
          <Alert variant="destructive">
            <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
              <span>系统状态加载失败：{apiErrorMessage(statsError, "请稍后重试。")}</span>
              <Button type="button" size="sm" variant="outline" onClick={() => { void refetchStats() }}>重试</Button>
            </AlertDescription>
          </Alert>
        )}
        <div className="grid gap-4 md:grid-cols-2">
          <Card>
            <CardHeader><CardTitle>快速入口</CardTitle><CardDescription>常用操作捷径</CardDescription></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Button variant="outline" className="h-24 flex-col gap-2" onClick={() => navigate("/console/subscription")}><Search className="h-6 w-6 text-slate-500" /><span>订阅新书</span></Button>
              <Button variant="outline" className="h-24 flex-col gap-2" onClick={() => navigate("/console/library")}><BookMarked className="h-6 w-6 text-slate-500" /><span>进入书库</span></Button>
              <Button variant="outline" className="h-24 flex-col gap-2" onClick={() => navigate("/console/plugins")}><Database className="h-6 w-6 text-slate-500" /><span>管理书源</span></Button>
              <Button variant="outline" className="h-24 flex-col gap-2" onClick={() => navigate("/console/search")}><ShieldAlert className="h-6 w-6 text-slate-500" /><span>搜索工作台</span></Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>状态口径</CardTitle><CardDescription>当前指标来自书源 Ping 探测</CardDescription></CardHeader>
            <CardContent>
              <p className="text-sm text-slate-500 leading-relaxed">书源可达性不等于正文可用性；具体章节处理日志仍以对应书籍详情为准。</p>
            </CardContent>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="max-w-4xl mx-auto w-full space-y-10">
      <div className="flex flex-col items-center text-center space-y-4 py-8">
        <div className="w-20 h-20 bg-slate-900 rounded-full flex items-center justify-center shadow-lg shadow-slate-200 mb-2">
          <BookOpen className="h-10 w-10 text-white" />
        </div>
        <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-slate-900">欢迎回来。</h1>
        <p className="text-base text-slate-500 max-w-lg mx-auto">发现并订阅书籍，跟踪共享正文的处理与发布状态。</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Link to="/console/subscription" className="group rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2">
          <Card className="h-full hover:shadow-lg transition-shadow border-slate-200 overflow-hidden relative">
            <div className="absolute top-0 right-0 p-6 opacity-10 group-hover:opacity-20 transition-opacity"><Search className="w-32 h-32" /></div>
            <CardHeader className="relative z-10 pb-4">
              <div className="w-12 h-12 bg-blue-50 text-blue-600 rounded-2xl flex items-center justify-center mb-4 shadow-sm"><Search className="h-6 w-6" /></div>
              <CardTitle className="text-xl">探索与订阅</CardTitle>
              <CardDescription className="text-sm mt-1">搜索全网书源，一键添加至你的个人书库</CardDescription>
            </CardHeader>
            <CardContent className="relative z-10 pt-0">
              <div className="text-blue-600 font-medium text-sm flex items-center group-hover:translate-x-1 transition-transform">开始探索 →</div>
            </CardContent>
          </Card>
        </Link>
        <Link to="/console/library" className="group rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2">
          <Card className="h-full hover:shadow-lg transition-shadow border-slate-200 overflow-hidden relative">
            <div className="absolute top-0 right-0 p-6 opacity-10 group-hover:opacity-20 transition-opacity"><BookMarked className="w-32 h-32" /></div>
            <CardHeader className="relative z-10 pb-4">
              <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-2xl flex items-center justify-center mb-4 shadow-sm"><BookMarked className="h-6 w-6" /></div>
              <CardTitle className="text-xl">我的书库</CardTitle>
              <CardDescription className="text-sm mt-1">管理个人订阅、章节覆盖与自动归档</CardDescription>
            </CardHeader>
            <CardContent className="relative z-10 pt-0">
              <div className="text-emerald-600 font-medium text-sm flex items-center group-hover:translate-x-1 transition-transform">管理书库 →</div>
            </CardContent>
          </Card>
        </Link>
      </div>
    </div>
  )
}
