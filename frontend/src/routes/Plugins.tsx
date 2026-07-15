import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { Globe, RotateCw, Power, Search, AlertCircle, SlidersHorizontal, KeyRound } from "lucide-react"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Progress } from "@/components/ui/progress"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Alert, AlertDescription } from "@/components/ui/alert"

const CAPABILITY_MAP: Record<string, string> = { search: "搜索", detail: "详情", toc: "目录", chapter: "正文", content: "正文", explore: "发现", auth: "登录" }
const CAP_COLORS: Record<string, string> = {
  search: "bg-blue-50 text-blue-600", detail: "bg-emerald-50 text-emerald-600",
  toc: "bg-purple-50 text-purple-600", chapter: "bg-amber-50 text-amber-600", content: "bg-amber-50 text-amber-600",
  explore: "bg-cyan-50 text-cyan-600", auth: "bg-rose-50 text-rose-600",
}

const CATEGORIES = ["全部", "小说", "漫画", "轻小说"]
const FORMATS = ["全部格式", "HTTP", "Browser"]
const STATUSES = ["全部状态", "已启用", "已禁用"]

function getPluginCategory(p: any): string {
  const tags = (p.tags || []).map((t: string) => t.toLowerCase())
  const name = (p.name || "").toLowerCase()
  if (tags.includes("漫画") || name.includes("漫画")) return "漫画"
  if (tags.includes("轻小说") || name.includes("轻小说")) return "轻小说"
  return "小说"
}

function getPluginLatency(p: any): number {
  const value = Number(p.health?.pingLatencyMs ?? p.latency ?? 0)
  return Number.isFinite(value) ? value : 0
}

function getPluginSuccessRate(p: any): number | null {
  const explicit = Number(p.health?.successRate ?? p.successRate)
  if (!Number.isFinite(explicit)) return null
  return Math.max(0, Math.min(100, explicit))
}

function getSuccessRateIndicatorClass(rate: number): string {
  if (rate > 90) return "bg-emerald-500"
  if (rate > 60) return "bg-amber-500"
  return "bg-rose-500"
}

function getLatencyClass(latency: number): string {
  if (latency === 0) return "text-slate-400"
  if (latency < 100) return "text-emerald-500"
  if (latency < 300) return "text-amber-500"
  return "text-rose-500"
}

export function Plugins() {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState("")
  const [categoryFilter, setCategoryFilter] = useState("全部")
  const [formatFilter, setFormatFilter] = useState("全部格式")
  const [statusFilter, setStatusFilter] = useState("全部状态")
  const [activeTab, setActiveTab] = useState<"thirdparty" | "official">("thirdparty")

  const { data, isLoading, error: pluginsError } = useQuery({ queryKey: ["plugins"], queryFn: api.plugins })
  const allPlugins = data?.items || []
  const thirdPartyCount = allPlugins.filter((p: any) => !p.official).length
  const officialCount = allPlugins.filter((p: any) => p.official).length
  const plugins = activeTab === "thirdparty" ? allPlugins.filter((p: any) => !p.official) : allPlugins.filter((p: any) => p.official)
  const pingAllMutation = useMutation({
    mutationFn: () => api.pingAllPlugins(plugins.map((p: any) => p.pluginId)),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugins"] }),
  })
  const batchEnableMutation = useMutation({
    mutationFn: ({ ids, enabled }: { ids: string[]; enabled: boolean }) => api.batchEnablePlugins(ids, enabled),
    onSuccess: () => { setSelectedIds(new Set()); queryClient.invalidateQueries({ queryKey: ["plugins"] }) },
  })
  const enabledCount = plugins.filter((p: any) => p.enabled).length
  const officialAuthCount = plugins.filter((p: any) => p.enabled && (p.capabilities || []).includes("auth")).length
  const smokePassed = plugins.filter((p: any) => p.health?.lastTestResult === "pass").length
  const smokedTotal = plugins.filter((p: any) => ["pass", "fail"].includes(p.health?.lastTestResult)).length
  const healthRate = smokedTotal > 0 ? ((smokePassed / smokedTotal) * 100).toFixed(1) : "0"

  const filteredPlugins = plugins.filter((p: any) => {
    const query = searchQuery.toLowerCase()
    const matchesSearch = !query
      || p.name.toLowerCase().includes(query)
      || p.pluginId.toLowerCase().includes(query)
      || (p.author || "").toLowerCase().includes(query)
      || (p.contributor || "").toLowerCase().includes(query)
    const matchesCategory = categoryFilter === "全部" || getPluginCategory(p) === categoryFilter
    const matchesFormat = formatFilter === "全部格式" || (p.accessType || p.sourceType) === formatFilter
    const matchesStatus = statusFilter === "全部状态"
      || (statusFilter === "已启用" && p.enabled)
      || (statusFilter === "已禁用" && !p.enabled)
    return matchesSearch && matchesCategory && matchesFormat && matchesStatus
  })

  const toggleSelectAll = () => {
    setSelectedIds((prev) => prev.size === filteredPlugins.length ? new Set() : new Set(filteredPlugins.map((p: any) => p.pluginId)))
  }

  const handleRowCheck = (pluginId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(pluginId)) next.delete(pluginId)
      else next.add(pluginId)
      return next
    })
  }

  return (
    <div className="space-y-6">
      {/* Stat Banner */}
      <div className="bg-gradient-to-r from-slate-900 to-slate-800 text-white rounded-xl p-6 shadow-sm border border-slate-700">
        <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="p-1.5 bg-slate-700/60 rounded-lg text-emerald-400"><Globe className="h-5 w-5" /></span>
              <h1 className="text-2xl font-bold tracking-tight">书源规则引擎</h1>
            </div>
            <p className="mt-1.5 text-slate-300 text-sm max-w-2xl">提供本地规则化嗅探及官方认证双引擎。管理分布式第三方爬虫规则，并维持官方站点的免限制登录。</p>
          </div>
          <Button
            variant="secondary"
            className="bg-white/10 text-white hover:bg-white/20 border-white/10"
            disabled={pingAllMutation.isPending || plugins.length === 0}
            onClick={() => pingAllMutation.mutate()}
          >
            <RotateCw className="h-4 w-4 mr-2" /> Ping 全部
          </Button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6 pt-6 border-t border-slate-700/60">
          <div className="bg-slate-800/40 p-3 rounded-lg border border-slate-700/40">
            <p className="text-xs text-slate-400">总插件数量</p>
            <div className="flex items-baseline gap-2 mt-1"><span className="text-xl font-bold font-mono">{plugins.length}</span><span className="text-xs text-slate-500">规则源</span></div>
          </div>
          <div className="bg-slate-800/40 p-3 rounded-lg border border-slate-700/40">
            <p className="text-xs text-slate-400">活跃启用中</p>
            <div className="flex items-baseline gap-2 mt-1"><span className="text-xl font-bold font-mono text-emerald-400">{enabledCount}</span><span className="text-xs text-slate-500">/{plugins.length} 运行中</span></div>
          </div>
          <div className="bg-slate-800/40 p-3 rounded-lg border border-slate-700/40">
            <p className="text-xs text-slate-400">官方登录能力</p>
            <div className="flex items-baseline gap-2 mt-1"><span className="text-xl font-bold font-mono text-cyan-400">{officialAuthCount}</span><span className="text-xs text-slate-500">/{plugins.length} 支持认证</span></div>
          </div>
          <div className="bg-slate-800/40 p-3 rounded-lg border border-slate-700/40">
            <p className="text-xs text-slate-400">规则连通度</p>
            <div className="flex items-baseline gap-2 mt-1"><span className="text-xl font-bold font-mono text-amber-400">{healthRate}%</span><span className="text-xs text-slate-500">测试通过率</span></div>
          </div>
        </div>
      </div>

      {(pluginsError || pingAllMutation.error || batchEnableMutation.error) && (
        <Alert variant="destructive">
          <AlertDescription>
            {(pingAllMutation.error as Error)?.message || (batchEnableMutation.error as Error)?.message || (pluginsError as Error)?.message || "书源操作失败，请稍后重试。"}
          </AlertDescription>
        </Alert>
      )}

      {/* Tabs */}
      <div className="flex justify-between items-center border-b border-slate-200 pb-px">
        <div className="bg-slate-100/80 p-1 rounded-lg inline-flex">
          <button
            type="button"
            onClick={() => { setActiveTab("thirdparty"); setSelectedIds(new Set()) }}
            className={`px-4 py-2 text-sm font-medium transition-all rounded-md ${activeTab === "thirdparty" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
          >
            <div className="flex items-center gap-2 whitespace-nowrap">
              <SlidersHorizontal className="h-4 w-4" />
              <span>第三方书源插件</span>
              <span className="bg-slate-200 text-slate-700 px-1.5 py-0.5 rounded-full text-[10px] font-mono font-bold">{thirdPartyCount}</span>
            </div>
          </button>
          <button
            type="button"
            onClick={() => { setActiveTab("official"); setSelectedIds(new Set()) }}
            className={`px-4 py-2 text-sm font-medium transition-all rounded-md ${activeTab === "official" ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-700"}`}
          >
            <div className="flex items-center gap-2 whitespace-nowrap">
              <KeyRound className="h-4 w-4" />
              <span>官方源账号认证</span>
              <span className="bg-slate-200 text-slate-700 px-1.5 py-0.5 rounded-full text-[10px] font-mono font-bold">{officialCount}</span>
            </div>
          </button>
        </div>
        <span className="text-xs text-slate-400 font-medium font-mono hidden sm:flex">ENGINE VERSION: v3.4.0-RELEASE</span>
      </div>

      {/* Search + Filters */}
      <div className="!mt-8 bg-white p-4 rounded-xl border border-slate-200 shadow-sm space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="搜索书源名称, ID, 或贡献者/作者..."
              value={searchQuery}
              onChange={(e) => { setSearchQuery(e.target.value); setSelectedIds(new Set()) }}
              className="w-full pl-9 pr-4 py-2 border border-slate-200 bg-slate-50/50 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-slate-400 transition-all text-slate-800"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-slate-400 font-medium">类目:</span>
            {CATEGORIES.map((t) => (
              <button key={t} type="button" onClick={() => { setCategoryFilter(t); setSelectedIds(new Set()) }}
                className={`px-3 py-1 text-xs rounded-full border transition-all ${categoryFilter === t ? "bg-slate-800 border-slate-800 text-white font-medium" : "bg-white border-slate-200 hover:bg-slate-50 text-slate-600"}`}>{t}</button>
            ))}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-4 pt-3 border-t border-slate-100">
          <div className="flex items-center gap-2">
            <span className="w-10 sm:w-auto text-xs text-slate-400 font-medium leading-tight">规则格式:</span>
            <select
              value={formatFilter}
              onChange={(e) => { setFormatFilter(e.target.value); setSelectedIds(new Set()) }}
              className="px-2 py-1 text-xs border border-slate-200 rounded-md bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-400"
            >
              {FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-10 sm:w-auto text-xs text-slate-400 font-medium leading-tight">运行状态:</span>
            <select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setSelectedIds(new Set()) }}
              className="px-2 py-1 text-xs border border-slate-200 rounded-md bg-white text-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-400"
            >
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* Bulk Action Bar */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center p-3 bg-slate-50 rounded-lg border border-slate-200 gap-3">
        <div className="flex items-center gap-2">
          <Checkbox checked={filteredPlugins.length > 0 && selectedIds.size === filteredPlugins.length} onCheckedChange={toggleSelectAll} disabled={batchEnableMutation.isPending} />
          <span className="text-sm text-slate-600 font-medium">
            {selectedIds.size > 0 ? `已选中 ${selectedIds.size} 项` : "选择书源批量操作"}
          </span>
        </div>
        {selectedIds.size > 0 && (
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" className="h-8 bg-white text-xs" disabled={batchEnableMutation.isPending} onClick={() => batchEnableMutation.mutate({ ids: Array.from(selectedIds), enabled: true })}>
              <Power className="h-3.5 w-3.5 mr-1 text-emerald-500" /> 批量启用
            </Button>
            <Button variant="outline" size="sm" className="h-8 bg-white text-xs" disabled={batchEnableMutation.isPending} onClick={() => batchEnableMutation.mutate({ ids: Array.from(selectedIds), enabled: false })}>
              <Power className="h-3.5 w-3.5 mr-1 text-slate-400" /> 批量禁用
            </Button>
          </div>
        )}
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="text-slate-500 py-10 text-center">加载中...</div>
      ) : (
        <Card className="border border-slate-200 overflow-hidden shadow-sm">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <Table>
                <TableHeader className="bg-slate-50/75 border-b border-slate-200">
                  <TableRow>
                    <TableHead className="w-10 text-center"></TableHead>
                    <TableHead className="py-3 text-slate-700 font-semibold">名称与版本</TableHead>
                    <TableHead className="text-slate-700 font-semibold">插件标识 (ID)</TableHead>
                    <TableHead className="text-slate-700 font-semibold">格式/分类</TableHead>
                    <TableHead className="text-slate-700 font-semibold">解析能力</TableHead>
                    <TableHead className="text-slate-700 font-semibold">健康指标</TableHead>
                    <TableHead className="text-slate-700 font-semibold">激活状态</TableHead>
                    <TableHead className="text-right text-slate-700 font-semibold pr-4">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody className="divide-y divide-slate-100">
                  {filteredPlugins.map((p: any) => {
                    const successRate = getPluginSuccessRate(p)
                    return (
                    <TableRow key={p.pluginId} className={`transition-colors duration-150 hover:bg-slate-50/50 ${!p.enabled ? "opacity-70 bg-slate-50/20" : ""}`}>
                      <TableCell className="text-center py-4">
                        <Checkbox checked={selectedIds.has(p.pluginId)} onCheckedChange={() => handleRowCheck(p.pluginId)} />
                      </TableCell>
                      <TableCell className="py-4">
                        <div className="flex flex-col">
                          <Link to={`/console/plugins/${p.pluginId}`} className="font-semibold text-slate-900 text-sm hover:text-blue-600 flex items-center gap-1.5">
                            {p.name}
                            {p.version && <span className="text-[10px] text-slate-400 font-mono font-normal">v{p.version}</span>}
                          </Link>
                          <span className="text-xs text-slate-400 mt-0.5">作者: {p.author || p.contributor || p.domain || p.baseUrls?.[0] || "-"}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-xs text-slate-500 font-mono">{p.pluginId}</TableCell>
                      <TableCell>
                        <div className="flex gap-1.5 items-center">
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-mono">{p.accessType || p.sourceType || "HTTP"}</Badge>
                          <Badge variant="secondary" className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0">{getPluginCategory(p)}</Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-0.5 flex-wrap w-44">
                          {p.capabilities?.map((c: string) => (
                            <span key={c} className={`text-[9px] font-medium px-1.5 py-0.5 rounded mr-1 ${CAP_COLORS[c] || "bg-slate-50 text-slate-500"}`}>{CAPABILITY_MAP[c] || c}</span>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-col gap-1.5 w-28">
                          <div className="flex justify-between items-center text-[10px] text-slate-400">
                            <span>延时:</span>
                            <span className={`font-mono font-bold ${getLatencyClass(getPluginLatency(p))}`}>
                              {getPluginLatency(p) === 0 ? "N/A" : `${getPluginLatency(p)}ms`}
                            </span>
                          </div>
                          <div className="flex justify-between items-center text-[10px] text-slate-400">
                            <span>成功率:</span>
                            <span className="font-mono font-bold text-slate-600">{successRate == null ? "N/A" : `${successRate}%`}</span>
                          </div>
                          {p.enabled && successRate != null && successRate > 0 && (
                            <Progress
                              value={successRate}
                              className="h-1 bg-slate-100"
                              indicatorClassName={getSuccessRateIndicatorClass(successRate)}
                            />
                          )}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center">
                          <button
                            type="button"
                            onClick={() => batchEnableMutation.mutate({ ids: [p.pluginId], enabled: !p.enabled })}
                            disabled={batchEnableMutation.isPending}
                            className={`relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${p.enabled ? "bg-slate-800" : "bg-slate-200"}`}
                            aria-label={p.enabled ? "禁用书源" : "启用书源"}
                          >
                            <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${p.enabled ? "translate-x-4" : "translate-x-0"}`} />
                          </button>
                          <span className="text-xs text-slate-500 ml-2 font-medium">{p.enabled ? "已启用" : "已禁用"}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right pr-4">
                        <div className="flex justify-end">
                          <Button variant="outline" size="sm" className="h-8 text-xs font-semibold" asChild>
                            <Link to={`/console/plugins/${p.pluginId}`}>详情与测试</Link>
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                    )
                  })}
                  {filteredPlugins.length === 0 && (
                    <TableRow><TableCell colSpan={8} className="text-center py-12 text-slate-400 text-sm"><AlertCircle className="h-8 w-8 mx-auto text-slate-300 mb-2" />没有找到符合筛选条件的书源。</TableCell></TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
