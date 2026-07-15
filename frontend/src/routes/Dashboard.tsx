import { useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { Activity, BookMarked, Database, Search, ShieldCheck, AlertCircle, BookOpen, ShieldAlert } from "lucide-react"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Alert, AlertDescription } from "@/components/ui/alert"

export function Dashboard() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  const { data: statsData, isLoading: statsLoading, error: statsError } = useQuery({ queryKey: ["status"], queryFn: api.status, enabled: isAdmin })

  if (isAdmin) {
    const stats = statsData || {}
    const pluginStats = stats.pluginStats || stats.plugins || {}
    const metric = (value: unknown) => statsLoading ? "加载中" : statsError ? "N/A" : String(value ?? 0)
    return (
      <div className="space-y-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">仪表盘</h1>
            <p className="mt-1 text-sm text-slate-500">欢迎回来，这是 LegadoHub 系统的当前状态。</p>
          </div>
        </div>
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">系统运行状态</CardTitle>
              <Activity className="h-4 w-4 text-emerald-500" />
            </CardHeader>
            <CardContent>
              <div className={`text-2xl font-bold ${statsError ? "text-rose-600" : "text-slate-900"}`}>{statsLoading ? "加载中" : statsError ? "未知" : "良好"}</div>
              <p className="text-xs text-slate-500 mt-1">{statsLoading ? "正在读取状态" : statsError ? "状态接口暂时不可用" : (stats.phase || "正常运行中")}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">书源总数</CardTitle>
              <Database className="h-4 w-4 text-slate-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-slate-900">{metric(pluginStats.total)}</div>
              <p className="text-xs text-slate-500 mt-1">已启用: {metric(pluginStats.enabled)}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">健康书源</CardTitle>
              <ShieldCheck className="h-4 w-4 text-emerald-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-emerald-600">{metric(pluginStats.healthy)}</div>
              <p className="text-xs text-slate-500 mt-1">Ping & Smoke 通行</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">异常书源</CardTitle>
              <AlertCircle className="h-4 w-4 text-rose-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold text-rose-600">{metric(pluginStats.unhealthy)}</div>
              <p className="text-xs text-slate-500 mt-1">需要管理员检查</p>
            </CardContent>
          </Card>
        </div>
        {statsError && (
          <Alert variant="destructive">
            <AlertDescription>系统状态加载失败：{(statsError as Error).message}</AlertDescription>
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
            <CardHeader><CardTitle>系统状态说明</CardTitle><CardDescription>当前页面只展示实时状态指标</CardDescription></CardHeader>
            <CardContent>
              <p className="text-sm text-slate-500 leading-relaxed">暂无实时动态流。需要查看具体处理进度时，请进入书库或对应书籍详情页。</p>
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
        <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight text-slate-900">欢迎回来，阅读者。</h1>
        <p className="text-base text-slate-500 max-w-lg mx-auto">准备好探索新的世界了吗？从全网海量书源中发现、订阅并管理你最喜爱的小说。</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card className="hover:shadow-lg transition-all cursor-pointer group border-slate-200 overflow-hidden relative" onClick={() => navigate("/console/subscription")}>
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
        <Card className="hover:shadow-lg transition-all cursor-pointer group border-slate-200 overflow-hidden relative" onClick={() => navigate("/console/library")}>
          <div className="absolute top-0 right-0 p-6 opacity-10 group-hover:opacity-20 transition-opacity"><BookMarked className="w-32 h-32" /></div>
          <CardHeader className="relative z-10 pb-4">
            <div className="w-12 h-12 bg-emerald-50 text-emerald-600 rounded-2xl flex items-center justify-center mb-4 shadow-sm"><BookMarked className="h-6 w-6" /></div>
            <CardTitle className="text-xl">我的书库</CardTitle>
            <CardDescription className="text-sm mt-1">沉浸式阅读体验，自动同步最新章节进度</CardDescription>
          </CardHeader>
          <CardContent className="relative z-10 pt-0">
            <div className="text-emerald-600 font-medium text-sm flex items-center group-hover:translate-x-1 transition-transform">查看书库 →</div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
