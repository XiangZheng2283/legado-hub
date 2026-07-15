import { useState, useMemo } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Search, Play, Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Alert, AlertDescription } from "@/components/ui/alert"

export function SearchJobs() {
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState("")
  const [jobId, setJobId] = useState<string | null>(null)

  const createMutation = useMutation({
    mutationFn: (payload: { keyword: string }) => api.createSearchJob({ keyword: payload.keyword, page: 1 }),
    onSuccess: (data) => {
      setJobId(data.jobId)
      queryClient.invalidateQueries({ queryKey: ["search-jobs"] })
      queryClient.setQueryData(["search-job", data.jobId], data)
    },
  })

  const { data: jobData, error: jobError } = useQuery({
    queryKey: ["search-job", jobId],
    queryFn: () => api.searchJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => {
      const data = q.state.data as any
      if (q.state.error || data?.liveSearchPending === false || ["completed", "partial", "timed_out", "failed", "cancelled", "unknown"].includes(data?.status)) return false
      return 1000
    },
  })

  const { data: eventsData, error: eventsError } = useQuery({
    queryKey: ["search-job-events", jobId],
    queryFn: () => api.searchJobEvents(jobId!),
    enabled: !!jobId,
    refetchInterval: jobData?.status !== "running" ? false : 500,
  })

  const events = useMemo(() => eventsData?.events || [], [eventsData?.events])
  const items = jobData?.result?.items || []
  const progress = useMemo(() => {
    const summary = events.find((e: any) => e.type === "summary") || {}
    return { completed: jobData?.completedCount || 0, total: jobData?.sourceCount || summary.sourceCount || 0 }
  }, [events, jobData])

  const handleSearch = () => {
    if (!keyword.trim() || createMutation.isPending) return
    setJobId(null)
    createMutation.mutate({ keyword: keyword.trim() })
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">搜索工作台</h1>
        <p className="mt-1 text-sm text-slate-500">管理员调试工具：验证聚合搜索效果、审查各个源的响应情况。</p>
      </div>

      <Card>
        <CardContent className="p-6">
          <div className="flex flex-col sm:flex-row gap-4 items-stretch sm:items-center">
            <div className="w-full relative group shadow-sm hover:shadow transition-shadow duration-300 rounded-full bg-slate-50 border border-slate-200 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-400/10 flex-1">
              <div className="flex items-center w-full px-1 py-1">
                <div className="pl-4 pr-2 text-slate-400 group-focus-within:text-blue-500 transition-colors"><Search className="h-4 w-4" /></div>
                <input type="text" placeholder="输入测试关键词..." value={keyword} onChange={(e) => setKeyword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                  className="flex-1 bg-transparent border-0 py-2 md:py-2.5 text-sm focus:outline-none focus:ring-0 text-slate-800 placeholder:text-slate-400" />
              </div>
            </div>
            <Button className="bg-slate-800 hover:bg-slate-900 rounded-full h-[46px] px-6 sm:flex-shrink-0" onClick={handleSearch} disabled={createMutation.isPending || !keyword.trim()}>
              {createMutation.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Play className="h-4 w-4 mr-2" />}
              发起调试搜索
            </Button>
          </div>

          {(createMutation.error || jobError || eventsError || ["failed", "timed_out", "unknown"].includes(jobData?.status || "")) && (
            <Alert variant="destructive" className="mt-4">
              <AlertDescription>
                {createMutation.error?.message || (jobError as Error)?.message || (eventsError as Error)?.message || jobData?.error || (jobData?.status === "timed_out" ? "搜索超时，已返回当前已完成的结果。" : "搜索任务失败，请重试。")}
              </AlertDescription>
            </Alert>
          )}

          {jobData && (
            <div className="mt-6 grid grid-cols-2 sm:grid-cols-4 gap-4 pt-6 border-t border-slate-100">
              <div><p className="text-xs text-slate-500 font-medium mb-1">参与源数</p><p className="text-2xl font-bold text-slate-900">{progress.total}</p></div>
              <div><p className="text-xs text-slate-500 font-medium mb-1">成功返回</p><p className="text-2xl font-bold text-emerald-600">{jobData.successCount || 0}</p></div>
              <div><p className="text-xs text-slate-500 font-medium mb-1">超时/失败</p><p className="text-2xl font-bold text-rose-500">{jobData.errorCount || 0}</p></div>
              <div><p className="text-xs text-slate-500 font-medium mb-1">聚合结果</p><p className="text-2xl font-bold text-indigo-600">{jobData?.resultCount ?? items.length}</p></div>
            </div>
          )}
        </CardContent>
      </Card>

      {items.length > 0 && (
        <div className="grid md:grid-cols-3 gap-6">
          <div className="md:col-span-2 space-y-6">
            <Card>
              <CardHeader><CardTitle>聚合结果矩阵</CardTitle><CardDescription>最终合并展现给用户的搜索结果</CardDescription></CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>书名/作者</TableHead>
                      <TableHead>匹配源数</TableHead>
                      <TableHead>最高评分</TableHead>
                      <TableHead>推荐源</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {items.map((item: any, idx: number) => (
                      <TableRow key={idx}>
                        <TableCell><p className="font-medium text-slate-900">{item.name || "-"}</p><p className="text-xs text-slate-500">{item.author || "-"}</p></TableCell>
                        <TableCell><Badge variant="secondary">{item.sourceCount || 1}</Badge></TableCell>
                        <TableCell><span className="text-emerald-600 font-medium">{item.score || 0}</span></TableCell>
                        <TableCell><code className="text-xs text-slate-500 bg-slate-50 px-1 py-0.5 rounded">{item.sourceName || item.sourceId || "-"}</code></TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </div>
          <div>
            <Card>
              <CardHeader><CardTitle className="text-sm">源执行流水</CardTitle></CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {events
                    .filter((e: any) => e.type !== "summary")
                    .slice(-20)
                    .map((e: any, i: number) => {
                      const status = e.status || (e.type === "source_error" ? "error" : e.type === "source_timeout" ? "timeout" : "success")
                      const label = status === "success" ? "OK" : status === "timeout" ? "TIMEOUT" : "ERR"
                      const badgeClass =
                        status === "success"
                          ? "bg-emerald-100 text-emerald-700 border-emerald-200"
                          : status === "timeout"
                            ? "bg-amber-100 text-amber-700 border-amber-200"
                            : "bg-rose-100 text-rose-700 border-rose-200"
                      return (
                        <div key={i} className="flex justify-between items-center text-sm border-b border-slate-50 pb-2 last:border-0 last:pb-0">
                          <span className="font-mono text-xs text-slate-600 truncate w-32">{e.sourceName || e.sourceId || "system"}</span>
                          <span className="text-slate-400 text-xs">{e.latencyMs != null ? `${e.latencyMs}ms` : new Date(e.ts * 1000).toLocaleTimeString()}</span>
                          <Badge variant="outline" className={`text-[10px] ${badgeClass}`}>{label}</Badge>
                        </div>
                      )
                    })}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {jobData?.status === "completed" && items.length === 0 && !createMutation.error && !jobError && (
        <div className="py-12 text-center text-sm text-slate-500">本次搜索没有返回可聚合的结果。</div>
      )}
    </div>
  )
}
