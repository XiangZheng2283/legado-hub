import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, Loader2, Search, Filter, ChevronDown, ChevronUp } from "lucide-react"

import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Switch } from "@/components/ui/switch"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"

function cacheReasonText(reason?: string) {
  if (reason === "timeout") return "命中（超时）"
  if (reason === "browser_required") return "命中（浏览器验证）"
  if (reason === "cloudflare_required") return "命中（风控）"
  if (reason === "network_error") return "命中（网络失败）"
  if (reason === "server_error") return "命中（服务异常）"
  if (reason === "live_failure") return "命中（失败）"
  return "命中"
}

function statusVariant(status?: string) {
  if (status === "completed" || status === "success" || status === "passed") return "success"
  if (status === "running") return "info"
  if (status === "failed" || status === "error" || status === "timeout") return "destructive"
  return "outline"
}

function sourceStatusLabel(event: any) {
  if (!event) return "pending"
  if (event.type === "source_empty") return "empty"
  if (event.type === "source_timeout") return "timeout"
  if (event.type === "source_error") return "error"
  return event.status || "success"
}

function sourceStatusText(status?: string) {
  if (status === "success") return "成功"
  if (status === "empty") return "无结果"
  if (status === "timeout") return "超时"
  if (status === "error" || status === "failed") return "失败"
  if (status === "running") return "搜索中"
  if (status === "pending") return "等待中"
  return status || "未知"
}

function eventLabel(event: any) {
  const labels: Record<string, string> = {
    queued: "已加入队列",
    summary: "开始搜索",
    source_start: "书源开始",
    source_done: "书源完成",
    source_empty: "无搜索结果",
    source_timeout: "书源超时",
    source_error: "书源报错",
    overall_timeout: "整体超时",
    batch_done: "批次完成",
    done: "搜索完成",
    cancelled: "已取消",
    filter_applied: "过滤应用",
  }
  return labels[event?.type] || event?.type || "事件"
}

function errorSummary(error: any) {
  if (!error) return ""
  if (typeof error === "string") return error

  const code = error.code || ""
  const message = error.message || error.error || ""
  let reason = "书源执行失败"
  if (code === "PLUGIN_TIMEOUT" || String(message).toLowerCase().includes("timeout")) {
    reason = "请求超时，当前已跳过该书源"
  } else if (String(message).includes("captcha") || String(message).includes("验证码")) {
    reason = "需要验证码，当前已跳过该书源"
  } else if (String(message).includes("bypass")) {
    reason = "绕过搜索失败，当前已跳过该书源"
  } else if (code === "BROWSER_REQUIRED" || code === "CLOUDFLARE_REQUIRED") {
    reason = "遇到验证或浏览器挑战，当前已跳过该书源"
  }

  const details = [code, message].filter(Boolean).join(" · ")
  return details ? `${reason}：${details}` : reason
}

function paragraphsFromContent(content?: string, title?: string) {
  const normalized = (content || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .trim()

  const blocks = normalized
    .split(/\n{2,}/)
    .map((block) =>
      block
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean)
        .join("\n")
    )
    .filter(Boolean)

  if (blocks[0] && title && blocks[0] === title.trim()) {
    return blocks.slice(1)
  }
  return blocks
}

function paragraphReviews(reviews: any, index: number) {
  const paragraphs = reviews?.paragraphs
  if (!paragraphs || typeof paragraphs !== "object") return []
  const oneBased = paragraphs[String(index + 1)]
  if (Array.isArray(oneBased)) return oneBased
  const zeroBased = paragraphs[String(index)]
  return Array.isArray(zeroBased) ? zeroBased : []
}

function chapterEndReviews(reviews: any) {
  return Array.isArray(reviews?.chapterEnd) ? reviews.chapterEnd : []
}

function hasReviewContent(reviews: any) {
  const summary = reviews?.summary || {}
  const paragraphs = reviews?.paragraphs || {}
  return Boolean(
    Object.keys(paragraphs).length ||
    chapterEndReviews(reviews).length ||
    summary.totalReviews ||
    summary.totalParagraphs
  )
}

function reviewMetaLine(review: any) {
  const parts = [
    review?.userName || "匿名读者",
    review?.reviewTime || "",
    typeof review?.likeNum === "number" ? `赞 ${review.likeNum}` : "",
    typeof review?.replyCount === "number" ? `回复 ${review.replyCount}` : "",
  ].filter(Boolean)
  return parts.join(" · ")
}

function sourceResultsFromEvents(events: any[]) {
  const items = new Map<string, any>()
  events
    .filter((event: any) => event.type === "result" && event.item)
    .forEach((event: any) => {
      const item = {
        ...event.item,
        sourceId: event.item.sourceId || event.sourceId,
        sourceName: event.item.sourceName || event.sourceName,
      }
      const key = `${item.sourceId || ""}::${item.bookUrl || ""}::${item.name || ""}`.trim()
      if (!key) return
      items.set(key, item)
    })
  return Array.from(items.values()).sort((left, right) => (right.score || 0) - (left.score || 0))
}

function visibleLogEvents(events: any[]) {
  return events.filter((event: any) => {
    if (event.type === "result" || event.type === "candidate_grouped") return false
    return true
  })
}

function formatLogLine(event: any, index: number): string {
  const ts = new Date().toLocaleTimeString("zh-CN", { hour12: false })
  const type = event.type || "unknown"
  const sourceName = event.sourceName || event.sourceId || "-"

  function _errDetail(err: any): string {
    if (!err) return ""
    const parts: string[] = []
    if (err.code) parts.push(`[${err.code}]`)
    if (err.message) parts.push(String(err.message))
    if (err.hint) parts.push(`提示: ${err.hint}`)
    if (err.url) parts.push(`URL: ${err.url}`)
    const extra = err.extra || err.error
    if (extra && typeof extra === "string") parts.push(`detail: ${extra}`)
    return parts.join(" | ") || "未知错误"
  }

  switch (type) {
    case "queued":
      return `${ts}  INFO  [search] 任务已加入队列: ${event.keyword || ""} (page=${event.page || 1})`
    case "summary":
      return `${ts}  INFO  [search] 开始搜索: 共 ${event.sourceCount || 0} 个书源, 批次大小 ${event.batchSize || 0}, 最大并发 ${event.maxConcurrency || 0}`
    case "source_start":
      return `${ts}  INFO  [search] 开始调用书源 → ${sourceName}`
    case "source_done": {
      const status = event.statusLabel || sourceStatusText(event.status)
      const latency = event.latencyMs != null ? `${event.latencyMs}ms` : "-"
      if (event.status === "error" && event.error) {
        return `${ts}  ERROR [search] 书源失败 ← ${sourceName} | ${_errDetail(event.error)} | 耗时 ${latency}`
      }
      return `${ts}  ${event.status === "error" ? "WARN" : "INFO"}  [search] 书源完成 ← ${sourceName} | ${status} | 结果 ${event.resultCount ?? 0} 条 | 耗时 ${latency}`
    }
    case "source_empty":
      return `${ts}  WARN  [search] 书源无结果 ← ${sourceName}`
    case "source_timeout":
      return `${ts}  WARN  [search] 书源超时 ← ${sourceName}${event.error ? " | " + _errDetail(event.error) : ""}`
    case "source_error":
      return `${ts}  ERROR [search] 书源报错 ← ${sourceName} | ${_errDetail(event.error)}`
    case "overall_timeout":
      return `${ts}  WARN  [search] 整体搜索超时 | 已耗时 ${event.elapsedMs || 0}ms`
    case "batch_done":
      return `${ts}  INFO  [search] 批次完成 | 进度 ${event.completedCount || 0}/${event.sourceCount || 0}`
    case "done": {
      const debug = event.debug || {}
      return `${ts}  INFO  [search] 搜索完成 | 成功 ${debug.successCount || 0} | 失败 ${debug.errorCount || 0} | 总耗时 ${debug.elapsedMs || 0}ms`
    }
    case "cancelled":
      return `${ts}  WARN  [search] 搜索已取消`
    case "filter_applied":
      return `${ts}  INFO  [search] ${event.message || ""}`
    default:
      return `${ts}  INFO  [search] ${event.message || eventLabel(event)}${event.sourceName ? ` | ${event.sourceName}` : ""}`
  }
}

export function SearchJobs() {
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState("")
  const [jobId, setJobId] = useState<string | null>(null)
  const [pendingJob, setPendingJob] = useState<any>(null)
  const [bookDetail, setBookDetail] = useState<any>(null)
  const [activeChapterIndex, setActiveChapterIndex] = useState(0)
  const [showSourceFilter, setShowSourceFilter] = useState(false)
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<string>>(new Set())
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [detailTarget, setDetailTarget] = useState<any>(null)

  const { data: pluginsData } = useQuery({
    queryKey: ["plugins"],
    queryFn: api.plugins,
  })
  const allPlugins = pluginsData?.items || []

  const createMutation = useMutation({
    mutationFn: (payload: { keyword: string; sourceIds?: string[] }) =>
      api.createSearchJob(payload.keyword, 1, undefined, payload.sourceIds),
    onSuccess: (data) => {
      if (!data.jobId) return
      const initialEvents = data.events || []
      setPendingJob(data)
      setJobId(data.jobId)
      queryClient.invalidateQueries({ queryKey: ["search-jobs"] })
      queryClient.setQueryData(["search-job", data.jobId], data)
      queryClient.setQueryData(["search-job-events", data.jobId], {
        jobId: data.jobId,
        events: initialEvents,
        nextAfter: initialEvents.length,
      })
      queryClient.invalidateQueries({ queryKey: ["search-job", data.jobId] })
      queryClient.invalidateQueries({ queryKey: ["search-job-events", data.jobId] })
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (id: string) => api.cancelSearchJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["search-job", jobId] }),
  })

  const verifyMutation = useMutation({
    mutationFn: ({ candidateId, chapterIndex }: { candidateId: string; chapterIndex?: number }) =>
      api.verifySearchCandidate(jobId!, candidateId, chapterIndex || 0),
    onSuccess: (data, variables) => {
      setActiveChapterIndex(variables.chapterIndex || 0)
      setBookDetail(data.result)
    },
  })

  const { data: jobData } = useQuery({
    queryKey: ["search-job", jobId],
    queryFn: () => api.searchJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => (query.state.data?.status === "completed" ? false : 500),
  })

  const { data: eventsData } = useQuery({
    queryKey: ["search-job-events", jobId],
    queryFn: () => api.searchJobEvents(jobId!),
    enabled: !!jobId,
    refetchInterval: jobData?.status === "completed" ? false : 500,
  })

  const events = useMemo(() => eventsData?.events || [], [eventsData?.events])
  const visibleJob = jobData || pendingJob
  const { data: recentJobsData } = useQuery({
    queryKey: ["search-jobs"],
    queryFn: api.searchJobs,
    refetchInterval: visibleJob?.status === "running" ? 1000 : false,
  })
  const recentJobs = recentJobsData?.items || []

  // Apply score filter on frontend as well for real-time events
  const scoreFilter = visibleJob?.result?.debug?.scoreFilter ?? 100
  const sourceResults = useMemo(() => {
    let items = visibleJob?.result?.items || []
    if (items.length) {
      items = items.filter((item: any) => (item.score || 0) >= scoreFilter)
    } else {
      items = sourceResultsFromEvents(events)
      items = items.filter((item: any) => (item.score || 0) >= scoreFilter)
    }
    return items
  }, [visibleJob, events, scoreFilter])

  const logEvents = useMemo(() => visibleLogEvents(events), [events])
  const progress = useMemo(() => {
    const summary = events.find((event: any) => event.type === "summary") || {}
    const doneBySource = new Map<string, any>()
    events.forEach((event: any) => {
      if (["source_done", "source_empty", "source_timeout", "source_error"].includes(event.type)) {
        doneBySource.set(event.sourceId || `${event.type}-${doneBySource.size}`, event)
      }
    })
    const running = events
      .filter((event: any) => event.type === "source_start" && !doneBySource.has(event.sourceId))
      .map((event: any) => ({ id: event.sourceId, name: event.sourceName }))
    const completed = visibleJob?.completedCount ?? doneBySource.size
    const total = visibleJob?.sourceCount ?? summary.sourceCount ?? 0
    const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0
    return { completed, total, percent, running, doneBySource }
  }, [events, visibleJob])

  const handleSearch = () => {
    const value = keyword.trim()
    if (!value) return
    setJobId(null)
    setBookDetail(null)
    setIsDetailOpen(false)
    setDetailTarget(null)
    setActiveChapterIndex(0)
    setPendingJob({
      status: "starting",
      keyword: value,
      sourceCount: 0,
      completedCount: 0,
      successCount: 0,
      errorCount: 0,
      elapsedMs: 0,
      result: { items: [] },
    })
    const sourceIds = selectedSourceIds.size > 0 ? Array.from(selectedSourceIds) : undefined
    createMutation.mutate({ keyword: value, sourceIds })
  }

  const handleOpenDetail = (item: any) => {
    if (!item.candidateId) return
    setDetailTarget(item)
    setBookDetail(null)
    setIsDetailOpen(true)
    setActiveChapterIndex(0)
    verifyMutation.mutate({ candidateId: item.candidateId })
  }

  const handleOpenJob = (job: any) => {
    if (!job.jobId) return
    setPendingJob(null)
    setBookDetail(null)
    setIsDetailOpen(false)
    setDetailTarget(null)
    setActiveChapterIndex(0)
    setKeyword(job.keyword || "")
    setJobId(job.jobId)
  }

  const toggleSource = (id: string) => {
    setSelectedSourceIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const selectAllSources = () => {
    setSelectedSourceIds(new Set(allPlugins.map((p: any) => p.pluginId)))
  }

  const clearAllSources = () => {
    setSelectedSourceIds(new Set())
  }

  const displayDetail = bookDetail || detailTarget
  const detailReviews = displayDetail?.reviews || {}
  const detailReviewSummary = detailReviews?.summary || {}
  const detailChapterEndReviews = chapterEndReviews(detailReviews)
  const showReviewSummary = hasReviewContent(detailReviews) || Boolean(detailReviews?.debug?.error)

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">搜索工作台</h1>
        <p className="text-sm text-muted-foreground">按书源直接返回结果，并实时显示当前调用的书源。</p>
      </div>

      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex flex-col gap-2 md:flex-row">
            <Input
              placeholder="输入书名或关键词"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && handleSearch()}
              className="h-10 flex-1"
            />
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => setShowSourceFilter((v) => !v)} className="h-10">
                <Filter className="mr-1 h-4 w-4" />
                书源
                {selectedSourceIds.size > 0 && (
                  <Badge variant="secondary" className="ml-1 text-xs">{selectedSourceIds.size}</Badge>
                )}
                {showSourceFilter ? <ChevronUp className="ml-1 h-3 w-3" /> : <ChevronDown className="ml-1 h-3 w-3" />}
              </Button>
              <Button onClick={handleSearch} disabled={createMutation.isPending} className="h-10">
                {createMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
                搜索
              </Button>
              {visibleJob?.status === "running" && jobId && (
                <Button variant="outline" onClick={() => cancelMutation.mutate(jobId)} className="h-10">
                  取消
                </Button>
              )}
            </div>
          </div>

          {showSourceFilter && (
            <div className="rounded-md border bg-muted/30 p-3 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={selectedSourceIds.size === allPlugins.length && allPlugins.length > 0}
                    onCheckedChange={(checked) => {
                      if (checked) selectAllSources()
                      else clearAllSources()
                    }}
                  />
                  <Label className="text-sm">全选</Label>
                </div>
                <span className="text-xs text-muted-foreground">
                  已选 {selectedSourceIds.size} / {allPlugins.length}
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {allPlugins.map((p: any) => {
                  const selected = selectedSourceIds.has(p.pluginId)
                  return (
                    <Badge
                      key={p.pluginId}
                      variant={selected ? "default" : "outline"}
                      className="cursor-pointer text-xs"
                      onClick={() => toggleSource(p.pluginId)}
                    >
                      {p.name || p.pluginId}
                    </Badge>
                  )
                })}
              </div>
            </div>
          )}

          {visibleJob && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={statusVariant(visibleJob.status) as any}>{visibleJob.status}</Badge>
                  <span className="font-medium">{progress.completed}/{progress.total} 书源</span>
                  <span className="text-muted-foreground">成功 {visibleJob.successCount || 0}</span>
                  <span className="text-muted-foreground">失败 {visibleJob.errorCount || 0}</span>
                  <span className="text-muted-foreground">耗时 {visibleJob.elapsedMs || 0}ms</span>
                  {scoreFilter > 0 && (
                    <span className="text-muted-foreground">过滤阈值 {scoreFilter}</span>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  <span className="text-muted-foreground">当前</span>
                  {progress.running.length === 0 ? (
                    <Badge variant="outline">{visibleJob.status === "completed" ? "已完成" : "等待调度"}</Badge>
                  ) : (
                    progress.running.map((source: any) => (
                      <Badge key={`${source.id}-${source.name}`} variant="info">{source.name || source.id}</Badge>
                    ))
                  )}
                </div>
              </div>
              <div className="h-2 overflow-hidden rounded bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${progress.percent}%` }} />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="rounded-md border bg-background">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <div className="text-sm font-semibold">书籍结果</div>
            <div className="text-xs text-muted-foreground">每一行对应一个书源返回的原始结果</div>
          </div>
          <Badge variant="outline">{sourceResults.length} 条</Badge>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>书名</TableHead>
              <TableHead>作者</TableHead>
              <TableHead>来源</TableHead>
              <TableHead>最新章节</TableHead>
              <TableHead>缓存</TableHead>
              <TableHead>评分</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sourceResults.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="h-28 text-center text-sm text-muted-foreground">
                  {visibleJob ? "搜索进行中，结果会实时出现" : "输入关键词后开始搜索"}
                </TableCell>
              </TableRow>
            )}
            {sourceResults.map((item: any) => (
              <TableRow key={item.candidateId || `${item.sourceId}-${item.bookUrl}`}>
                <TableCell className="font-medium">{item.name || "-"}</TableCell>
                <TableCell>{item.author || "-"}</TableCell>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <Badge variant="outline" className="w-fit">{item.sourceName || item.sourceId || "-"}</Badge>
                    {item.sourceId && <span className="font-mono text-xs text-muted-foreground">{item.sourceId}</span>}
                  </div>
                </TableCell>
                <TableCell className="max-w-64 truncate">{item.lastChapter || "-"}</TableCell>
                <TableCell>
                  {!item.aggregate && item.cacheHit ? (
                    <Badge variant="secondary">{cacheReasonText(item.cacheReason)}</Badge>
                  ) : (
                    <span className="text-xs text-muted-foreground">实时</span>
                  )}
                </TableCell>
                <TableCell>{item.score || 0}</TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={verifyMutation.isPending || !item.candidateId}
                    onClick={() => handleOpenDetail(item)}
                  >
                    {verifyMutation.isPending && detailTarget?.candidateId === item.candidateId ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <BookOpen className="h-4 w-4" />
                    )}
                    查看详情
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      {events.length > 0 && (
        <div className="rounded-md border bg-background">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div className="text-sm font-semibold">书源进度明细</div>
            <Badge variant="outline">{logEvents.length} 条</Badge>
          </div>
          <ScrollArea className="h-64">
            <div className="space-y-0">
              {logEvents
                .slice(-100)
                .map((event: any, index: number) => (
                  <div
                    key={`${event.type}-${index}`}
                    className={`px-4 py-0.5 font-mono text-xs leading-5 ${
                      event.type === "source_error" || event.type === "source_timeout"
                        ? "text-destructive bg-destructive/5"
                        : event.type === "done"
                          ? "text-green-700 bg-green-50"
                          : "text-muted-foreground hover:bg-muted/40"
                    }`}
                  >
                    {formatLogLine(event, index)}
                  </div>
                ))}
            </div>
          </ScrollArea>
        </div>
      )}

      {recentJobs.length > 0 && (
        <div className="rounded-md border bg-background">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div className="text-sm font-semibold">最近搜索</div>
            <Badge variant="outline">{recentJobs.length} 条</Badge>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>关键词</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>进度</TableHead>
                <TableHead>耗时</TableHead>
                <TableHead className="text-right">操作</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentJobs.map((job: any) => (
                <TableRow key={job.jobId}>
                  <TableCell className="font-medium">{job.keyword || "-"}</TableCell>
                  <TableCell>
                    <Badge variant={statusVariant(job.status) as any}>{job.status || "-"}</Badge>
                  </TableCell>
                  <TableCell>{job.completedCount || 0} 完成 / 成功 {job.successCount || 0}</TableCell>
                  <TableCell>{job.elapsedMs || 0}ms</TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => handleOpenJob(job)}>
                      查看
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <Dialog open={isDetailOpen} onOpenChange={(open) => { setIsDetailOpen(open); if (!open) { setBookDetail(null); setDetailTarget(null) } }}>
        <DialogContent className="max-h-[92vh] max-w-6xl overflow-hidden p-0">
          <DialogHeader>
            <DialogTitle className="px-6 pt-6">小说详情</DialogTitle>
          </DialogHeader>
          <div className="grid min-h-0 gap-0 border-t text-sm lg:grid-cols-[1fr_320px]">
            <ScrollArea className="max-h-[78vh]">
              <div className="space-y-5 p-6">
                <div className="grid gap-4 sm:grid-cols-[112px_1fr]">
                  <div className="h-40 w-28 overflow-hidden rounded border bg-muted">
                    {displayDetail?.detail?.coverUrl ? (
                      <img
                        src={displayDetail.detail.coverUrl}
                        alt={displayDetail.detail?.name || displayDetail.selectedCandidate?.name || displayDetail.name || "cover"}
                        className="h-full w-full object-cover"
                      />
                    ) : (
                      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
                        {verifyMutation.isPending && !bookDetail ? <Loader2 className="h-6 w-6 animate-spin" /> : "无封面"}
                      </div>
                    )}
                  </div>
                  <div className="min-w-0 space-y-3">
                    <div>
                      {verifyMutation.isPending && !bookDetail ? (
                        <div className="space-y-2">
                          <Skeleton className="h-8 w-48" />
                          <Skeleton className="h-4 w-32" />
                        </div>
                      ) : (
                        <>
                          <h2 className="text-2xl font-semibold">
                            {displayDetail?.detail?.name || displayDetail?.selectedCandidate?.name || displayDetail?.name || "-"}
                          </h2>
                          <div className="mt-2 flex flex-wrap items-center gap-2 text-muted-foreground">
                            <span>{displayDetail?.detail?.author || displayDetail?.selectedCandidate?.author || displayDetail?.author || "未知作者"}</span>
                            <Badge variant={statusVariant(bookDetail?.status) as any}>{bookDetail?.status || "loading"}</Badge>
                            <Badge variant="outline">{displayDetail?.selectedCandidate?.sourceName || displayDetail?.sourceName || displayDetail?.sourceId || "未知书源"}</Badge>
                            {displayDetail?.cacheHit && !displayDetail?.aggregate && (
                              <Badge variant="secondary">{cacheReasonText(displayDetail?.cacheReason)}</Badge>
                            )}
                            {!displayDetail?.aggregate && displayDetail?.detail?.debug?.cacheHit && (
                              <Badge variant="secondary">{cacheReasonText(displayDetail?.detail?.debug?.cacheReason)}</Badge>
                            )}
                            {!displayDetail?.aggregate && displayDetail?.toc?.debug?.cacheHit && (
                              <Badge variant="secondary">{cacheReasonText(displayDetail?.toc?.debug?.cacheReason)}</Badge>
                            )}
                            {!displayDetail?.aggregate && displayDetail?.chapter?.debug?.cacheHit && (
                              <Badge variant="secondary">{cacheReasonText(displayDetail?.chapter?.debug?.cacheReason)}</Badge>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                    {verifyMutation.isPending && !bookDetail ? (
                      <div className="space-y-2">
                        <Skeleton className="h-4 w-full" />
                        <Skeleton className="h-4 w-3/4" />
                        <Skeleton className="h-4 w-1/2" />
                      </div>
                    ) : (
                      <>
                        <div className="grid gap-2 text-muted-foreground sm:grid-cols-3">
                          <div>目录: {displayDetail?.toc?.chapterCount || displayDetail?.toc?.items?.length || displayDetail?.toc?.chapters?.length || 0} 章</div>
                          <div>正文: {displayDetail?.chapter?.contentLength || displayDetail?.chapter?.content?.length || 0} 字</div>
                          <div>字数: {displayDetail?.detail?.wordCountText || displayDetail?.detail?.wordCount || "未知"}</div>
                        </div>
                        <div className="grid gap-1 text-muted-foreground">
                          <div>最新: {displayDetail?.detail?.lastChapter || displayDetail?.selectedCandidate?.lastChapter || displayDetail?.lastChapter || "-"}</div>
                          <div className="truncate">来源: {displayDetail?.detail?.bookUrl || displayDetail?.selectedCandidate?.bookUrl || displayDetail?.bookUrl || "-"}</div>
                          {showReviewSummary && (
                            <div>
                              本章说: {detailReviewSummary.totalReviews || 0} 条 · 段评段落 {detailReviewSummary.totalParagraphs || 0} 个 · 章末评论 {detailReviewSummary.chapterEndCount || 0} 条
                            </div>
                          )}
                          {!displayDetail?.aggregate && displayDetail?.detail?.debug?.cacheHit && (
                            <div>详情: {cacheReasonText(displayDetail?.detail?.debug?.cacheReason)}</div>
                          )}
                          {!displayDetail?.aggregate && displayDetail?.toc?.debug?.cacheHit && (
                            <div>目录: {cacheReasonText(displayDetail?.toc?.debug?.cacheReason)}</div>
                          )}
                          {!displayDetail?.aggregate && displayDetail?.chapter?.debug?.cacheHit && (
                            <div>正文: {cacheReasonText(displayDetail?.chapter?.debug?.cacheReason)}</div>
                          )}
                        </div>
                        <p className="line-clamp-4 leading-7 text-muted-foreground">
                          {displayDetail?.detail?.intro || displayDetail?.intro || "暂无简介"}
                        </p>
                        {showReviewSummary && (
                          <div className="rounded-md border bg-background/70 p-4 text-sm">
                            <div className="font-medium text-foreground">起点本章说预览</div>
                            <div className="mt-2 grid gap-2 text-xs text-muted-foreground sm:grid-cols-3">
                              <div>评论总数: {detailReviewSummary.totalReviews || 0}</div>
                              <div>有段评的段落: {detailReviewSummary.totalParagraphs || 0}</div>
                              <div>认证模式: {detailReviewSummary.authMode || "unknown"}</div>
                            </div>
                            {!!detailReviewSummary.fetchedParagraphs?.length && (
                              <div className="mt-2 text-xs text-muted-foreground">
                                已预取段落: {detailReviewSummary.fetchedParagraphs.join(", ")}
                              </div>
                            )}
                            {detailReviews?.debug?.error && (
                              <div className="mt-2 text-xs text-amber-700">
                                评论接口提示: {detailReviews.debug.error}
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>

                {verifyMutation.isPending && !bookDetail ? (
                  <div className="space-y-4">
                    <Skeleton className="h-6 w-32 mx-auto" />
                    <div className="space-y-3">
                      {Array.from({ length: 8 }).map((_, i) => (
                        <Skeleton key={i} className="h-4 w-full" />
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-md border bg-[#f8f3e8] px-8 py-7 text-[#2f261d]">
                    <div className="mb-6 text-center text-xl font-semibold">
                      {displayDetail?.chapter?.title || "请选择章节"}
                    </div>
                    <div className="space-y-5 text-lg leading-9">
                      {paragraphsFromContent(displayDetail?.chapter?.content, displayDetail?.chapter?.title).length > 0 ? (
                        paragraphsFromContent(displayDetail?.chapter?.content, displayDetail?.chapter?.title).map((paragraph, index) => (
                          <div key={index} className="space-y-3">
                            <p className="whitespace-pre-wrap indent-8">
                              {paragraph}
                            </p>
                            {paragraphReviews(detailReviews, index).length > 0 && (
                              <div className="ml-8 rounded-md border border-amber-300/70 bg-white/80 px-4 py-3 text-sm leading-6 text-[#5a4331]">
                                <div className="mb-2 text-xs font-medium text-amber-800">
                                  段评 · 第 {index + 1} 段 · {paragraphReviews(detailReviews, index).length} 条
                                </div>
                                <div className="space-y-3">
                                  {paragraphReviews(detailReviews, index).map((review: any, reviewIndex: number) => (
                                    <div key={review?.id || `${index}-${reviewIndex}`} className="space-y-1 border-b border-amber-100/70 pb-2 last:border-b-0 last:pb-0">
                                      <div className="text-xs text-amber-900">{reviewMetaLine(review)}</div>
                                      <div className="whitespace-pre-wrap text-sm leading-6">{review?.content || "暂无评论内容"}</div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        ))
                      ) : (
                        <p className="text-center text-sm text-muted-foreground">暂无正文</p>
                      )}
                    </div>
                    {detailChapterEndReviews.length > 0 && (
                      <div className="mt-8 rounded-md border border-amber-400/70 bg-white/85 px-5 py-4 text-sm text-[#5a4331]">
                        <div className="mb-3 text-sm font-semibold text-amber-900">章末评论</div>
                        <div className="space-y-3">
                          {detailChapterEndReviews.map((review: any, reviewIndex: number) => (
                            <div key={review?.id || `chapter-end-${reviewIndex}`} className="space-y-1 border-b border-amber-100/70 pb-2 last:border-b-0 last:pb-0">
                              <div className="text-xs text-amber-900">{reviewMetaLine(review)}</div>
                              <div className="whitespace-pre-wrap leading-6">{review?.content || "暂无评论内容"}</div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {displayDetail?.diagnostics?.length > 0 && (
                  <div className="space-y-1">
                    <div className="font-medium">诊断</div>
                    {displayDetail.diagnostics.map((item: any, index: number) => (
                      <div key={index} className="rounded bg-muted px-2 py-1 text-xs">
                        {item.stage} · {item.code} · {item.message}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </ScrollArea>

            <div className="border-l bg-muted/20">
              <div className="border-b px-4 py-3">
                <div className="font-semibold">目录</div>
                <div className="text-xs text-muted-foreground">点击章节可切换阅读内容</div>
              </div>
              <ScrollArea className="h-[72vh]">
                <div className="space-y-1 p-3">
                  {(displayDetail?.search?.groups?.[0]?.items || []).length > 1 && (
                    <div className="mb-3 rounded border bg-background p-2 text-xs text-muted-foreground">
                      当前来源: {displayDetail?.selectedCandidate?.sourceName || displayDetail?.selectedCandidate?.sourceId || displayDetail?.sourceName}
                    </div>
                  )}
                  {verifyMutation.isPending && !bookDetail ? (
                    <div className="space-y-2 p-2">
                      {Array.from({ length: 10 }).map((_, i) => (
                        <Skeleton key={i} className="h-8 w-full" />
                      ))}
                    </div>
                  ) : (
                    <>
                      {(displayDetail?.toc?.items || displayDetail?.toc?.chapters || []).length === 0 && (
                        <div className="p-4 text-center text-muted-foreground">暂无目录</div>
                      )}
                      {(displayDetail?.toc?.items || displayDetail?.toc?.chapters || []).map((chapter: any, index: number) => (
                        <Button
                          key={chapter.chapterUrl || index}
                          variant={activeChapterIndex === index ? "secondary" : "ghost"}
                          className="h-auto w-full justify-start whitespace-normal px-3 py-2 text-left"
                          disabled={verifyMutation.isPending}
                          onClick={() =>
                            verifyMutation.mutate({
                              candidateId: bookDetail?.selectedCandidate?.candidateId || detailTarget?.candidateId,
                              chapterIndex: index,
                            })
                          }
                        >
                          <span className="mr-2 text-xs text-muted-foreground">{index + 1}</span>
                          <span>{chapter.title || `第 ${index + 1} 章`}</span>
                        </Button>
                      ))}
                    </>
                  )}
                </div>
              </ScrollArea>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
