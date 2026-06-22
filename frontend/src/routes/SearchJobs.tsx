import { useEffect, useMemo, useRef, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertCircle, BookOpen, Check, Loader2, Search, Filter, ChevronDown, ChevronUp, ChevronRight, MessageSquare, ThumbsUp, MessageCircle, X } from "lucide-react"

import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Skeleton } from "@/components/ui/skeleton"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"

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
  if (status === "partial") return "warning"
  if (status === "timed_out" || status === "timeout") return "destructive"
  if (status === "failed" || status === "error") return "destructive"
  return "outline"
}

function jobStatusText(status?: string) {
  if (status === "completed") return "已完成"
  if (status === "running") return "搜索中"
  if (status === "cancelled") return "已取消"
  if (status === "partial") return "部分完成"
  if (status === "timed_out") return "整体超时"
  if (status === "failed") return "失败"
  if (status === "pending") return "等待调度"
  return status || "未知"
}

function isTerminalStatus(status?: string) {
  return ["completed", "partial", "timed_out", "failed", "cancelled"].includes(status || "")
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
    source_complete: "书源完成",
    source_done: "书源完成",
    source_empty: "无搜索结果",
    source_timeout: "书源超时",
    source_error: "书源报错",
    result: "结果返回",
    stage_boundary: "阶段边界",
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
  const pid = paragraphDisplayNumber(index + 1)
  const oneBased = paragraphs[String(pid)]
  if (Array.isArray(oneBased)) return oneBased
  const zeroBased = paragraphs[String(index)]
  return Array.isArray(zeroBased) ? zeroBased : []
}

function chapterEndReviews(reviews: any) {
  return Array.isArray(reviews?.chapterEnd) ? reviews.chapterEnd : []
}

function chapterEndHotReviews(reviews: any) {
  return Array.isArray(reviews?.chapterEndHot) ? reviews.chapterEndHot : []
}

function authorReviews(reviews: any) {
  return Array.isArray(reviews?.authorReviews) ? reviews.authorReviews : []
}

function hasReviewContent(reviews: any) {
  const summary = reviews?.summary || {}
  const paragraphs = reviews?.paragraphs || {}
  return Boolean(
    Object.keys(paragraphs).length ||
    chapterEndReviews(reviews).length ||
    chapterEndHotReviews(reviews).length ||
    authorReviews(reviews).length ||
    summary.totalReviews ||
    summary.totalParagraphs
  )
}

function formatReviewCount(count?: number) {
  if (typeof count !== "number" || count <= 0) return "0"
  if (count > 9999) return "9999+"
  if (count > 99) return "99+"
  return String(count)
}

function UserBadges({ review }: { review: any }) {
  const level = typeof review?.level === "number" ? review.level : 0
  const badges: string[] = Array.isArray(review?.badges) ? review.badges : []
  if (!level && !badges.length) return null
  return (
    <span className="inline-flex items-center gap-1 flex-wrap">
      {level > 0 && (
        <span className="rounded px-1 py-0 text-[10px] leading-tight bg-amber-100 text-amber-700">
          Lv.{level}
        </span>
      )}
      {badges.map((badge: string, idx: number) => (
        <span
          key={idx}
          className="rounded px-1 py-0 text-[10px] leading-tight bg-orange-100 text-orange-700"
        >
          {badge}
        </span>
      ))}
    </span>
  )
}

function ReviewMeta({ review }: { review: any }) {
  return (
    <div className="flex items-center gap-2 text-xs text-amber-900/80 flex-wrap">
      <span className="font-medium text-amber-900">{review?.userName || "匿名读者"}</span>
      <UserBadges review={review} />
      {review?.reviewTime && <span className="text-amber-700/70">{review.reviewTime}</span>}
      {review?.ipAddress && <span className="text-amber-700/70">{review.ipAddress}</span>}
    </div>
  )
}

function ReviewActions({ review }: { review: any }) {
  return (
    <div className="flex items-center gap-4 text-xs text-amber-700/80">
      <span className="inline-flex items-center gap-1">
        <ThumbsUp className="w-3 h-3" />
        {formatReviewCount(review?.likeNum)}
      </span>
      {typeof review?.replyCount === "number" && review.replyCount > 0 && (
        <span className="inline-flex items-center gap-1">
          <MessageSquare className="w-3 h-3" />
          {formatReviewCount(review.replyCount)}
        </span>
      )}
    </div>
  )
}

function ReviewCard({ review }: { review: any }) {
  return (
    <div className="space-y-1.5 border-b border-amber-100/70 pb-3 last:border-b-0 last:pb-0">
      <ReviewMeta review={review} />
      <div className="whitespace-pre-wrap text-sm leading-6 text-[#5a4331]">
        {review?.content || "暂无评论内容"}
      </div>
      <ReviewActions review={review} />
      {Array.isArray(review?.replies) && review.replies.length > 0 && (
        <div className="mt-2 space-y-2 rounded-md bg-amber-50/60 px-3 py-2">
          {review.replies.slice(0, 3).map((reply: any, idx: number) => (
            <div key={reply?.id || `reply-${idx}`} className="text-xs text-[#5a4331]">
              <span className="font-medium text-amber-800">{reply?.userName || "匿名读者"}：</span>
              <span>{reply?.content || ""}</span>
            </div>
          ))}
          {review.replies.length > 3 && (
            <div className="text-xs text-amber-700">查看更多 {review.replies.length - 3} 条回复</div>
          )}
        </div>
      )}
    </div>
  )
}

export function ReviewList({
  reviews,
  limit = 10,
  step = 10,
}: {
  reviews: any[]
  limit?: number
  step?: number
}) {
  const [visibleCount, setVisibleCount] = useState(limit)
  const display = reviews.slice(0, visibleCount)
  const hasMore = reviews.length > visibleCount
  const remaining = Math.max(0, reviews.length - visibleCount)

  return (
    <div className="space-y-3">
      <div className="space-y-3">
        {display.map((review: any, idx: number) => (
          <ReviewCard key={review?.id || `review-${idx}`} review={review} />
        ))}
      </div>
      {reviews.length > limit && (
        <div className="pt-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 text-xs text-amber-700 hover:text-amber-900"
            onClick={() =>
              setVisibleCount((prev) => (hasMore ? Math.min(prev + step, reviews.length) : limit))
            }
          >
            {hasMore ? `展开更多 ${Math.min(step, remaining)} 条` : "收起"}
            {hasMore ? <ChevronDown className="ml-1 w-3 h-3" /> : <ChevronUp className="ml-1 w-3 h-3" />}
          </Button>
        </div>
      )}
    </div>
  )
}

function ParagraphReviewBubble({
  reviews,
  paragraphIndex,
}: {
  reviews: any[]
  paragraphIndex: number
}) {
  const [open, setOpen] = useState(false)
  if (!reviews.length) return null
  return (
    <>
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>
            <button
              type="button"
              onClick={() => setOpen(true)}
              className="inline-flex items-center gap-1 rounded-full border border-amber-300/60 bg-white/90 px-2.5 py-0.5 text-xs text-amber-700 shadow-sm hover:bg-amber-50 transition-colors"
            >
              <MessageSquare className="w-3 h-3" />
              {formatReviewCount(reviews.length)}
            </button>
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-xs">
            <div className="text-xs">点击展开第 {paragraphDisplayNumber(paragraphIndex + 1)} 段评论（{reviews.length} 条）</div>
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-lg max-h-[80vh] flex flex-col">
          <DialogHeader>
            <DialogTitle className="text-base">第 {paragraphDisplayNumber(paragraphIndex + 1)} 段 · {reviews.length} 条评论</DialogTitle>
          </DialogHeader>
          <ScrollArea className="flex-1 pr-2">
            <ReviewList reviews={reviews} limit={10} />
          </ScrollArea>
        </DialogContent>
      </Dialog>
    </>
  )
}

function paragraphDisplayNumber(pid: number): number {
  // Backend paragraph IDs are 1-based and aligned with the in-text paragraph order.
  return pid
}

export function ChapterReviewDialog({
  reviews,
  loading,
  error,
  open,
  onOpenChange,
}: {
  reviews: any
  loading?: boolean
  error?: any
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const [tab, setTab] = useState("chapter")
  const summary = reviews?.summary || {}
  const total = summary.totalReviews || 0
  const chapterEnd = Array.isArray(reviews?.chapterEnd) ? reviews.chapterEnd : []
  const chapterEndHot = Array.isArray(reviews?.chapterEndHot) ? reviews.chapterEndHot : []
  const authorList = Array.isArray(reviews?.authorReviews) ? reviews.authorReviews : []
  const paragraphs = reviews?.paragraphs || {}
  const paragraphStats = summary.paragraphStats || {}

  const paragraphGroups = Object.entries(paragraphs)
    .filter(([, list]) => Array.isArray(list) && list.length > 0)
    .map(([pid, list]) => ({
      pid: Number(pid),
      count: (list as any[]).length,
      statCount: paragraphStats[pid] || 0,
      reviews: list as any[],
    }))
    .sort((a, b) => b.pid - a.pid)

  const chapterTabCount = chapterEnd.length + chapterEndHot.length
  const paragraphTabCount = paragraphGroups.length

  // Pick the first non-empty tab when the dialog opens.
  useEffect(() => {
    if (!open) return
    if (chapterEnd.length > 0 || chapterEndHot.length > 0) {
      setTab("chapter")
    } else if (paragraphGroups.length > 0) {
      setTab("paragraph")
    } else if (authorList.length > 0) {
      setTab("author")
    } else {
      setTab("chapter")
    }
  }, [open])

  // If the active tab becomes empty after reviews load, fall back to a non-empty tab.
  useEffect(() => {
    if (!open) return
    const empty = {
      chapter: chapterEnd.length === 0 && chapterEndHot.length === 0,
      paragraph: paragraphGroups.length === 0,
      author: authorList.length === 0,
    }
    if (!empty[tab as keyof typeof empty]) return
    if (chapterEnd.length > 0 || chapterEndHot.length > 0) setTab("chapter")
    else if (paragraphGroups.length > 0) setTab("paragraph")
    else if (authorList.length > 0) setTab("author")
  }, [chapterEnd, chapterEndHot, paragraphGroups, authorList, open, tab])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] flex flex-col overflow-hidden p-0">
        <DialogHeader className="shrink-0 px-6 pt-6 pb-2">
          <DialogTitle className="text-base">本章说 · 共 {formatReviewCount(total)} 条</DialogTitle>
        </DialogHeader>

        {error && (
          <div className="shrink-0 mx-6 mb-2 text-xs text-destructive">
            评论加载失败：{error.message || String(error)}
          </div>
        )}

        {summary.vipHint && (
          <div className="shrink-0 mx-6 mb-2 flex items-start gap-1.5 rounded-md bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800">
            <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
            <span>{summary.vipHint}</span>
          </div>
        )}

        <Tabs value={tab} onValueChange={setTab} className="flex flex-col min-h-0 flex-1 px-6 pb-6">
          <TabsList className="shrink-0 grid w-full grid-cols-3">
            <TabsTrigger value="author" className="text-xs">
              作家说{authorList.length > 0 ? ` (${formatReviewCount(authorList.length)})` : ""}
            </TabsTrigger>
            <TabsTrigger value="chapter" className="text-xs">
              本章说{chapterTabCount > 0 ? ` (${formatReviewCount(chapterTabCount)})` : ""}
            </TabsTrigger>
            <TabsTrigger value="paragraph" className="text-xs">
              段评说{paragraphTabCount > 0 ? ` (${formatReviewCount(paragraphTabCount)})` : ""}
            </TabsTrigger>
          </TabsList>

          <div className="flex-1 min-h-0 overflow-y-auto mt-4 pr-2" data-testid="review-scroll-container">
            <TabsContent value="author" className="mt-0">
                {authorList.length > 0 ? (
                  <ReviewList reviews={authorList} limit={10} />
                ) : (
                  <div className="py-8 text-center text-sm text-muted-foreground">暂无作家说</div>
                )}
              </TabsContent>

              <TabsContent value="chapter" className="mt-0 space-y-6">
                {chapterEndHot.length > 0 && (
                  <div>
                    <div className="mb-2 text-xs font-semibold text-amber-900">章末热评</div>
                    <ReviewList reviews={chapterEndHot} limit={10} />
                  </div>
                )}
                {chapterEnd.length > 0 && (
                  <div>
                    <div className="mb-2 text-xs font-semibold text-amber-900">
                      全部章评
                      <span className="ml-1 text-amber-700/70">{formatReviewCount(chapterEnd.length)} 条</span>
                    </div>
                    <ReviewList reviews={chapterEnd} limit={10} />
                  </div>
                )}
                {chapterEndHot.length === 0 && chapterEnd.length === 0 && (
                  <div className="py-8 text-center text-sm text-muted-foreground">暂无本章说</div>
                )}
              </TabsContent>

              <TabsContent value="paragraph" className="mt-0 space-y-6">
                {paragraphGroups.length > 0 ? (
                  paragraphGroups.map((group) => (
                    <div key={group.pid}>
                      <div className="mb-2 text-xs font-semibold text-amber-900">
                        第 {paragraphDisplayNumber(group.pid)} 段
                        <span className="ml-2 text-amber-700/70">{formatReviewCount(group.statCount || group.count)} 条</span>
                      </div>
                      <ReviewList reviews={group.reviews} limit={10} />
                    </div>
                  ))
                ) : (
                  <div className="py-8 text-center text-sm text-muted-foreground">暂无段评说</div>
                )}
              </TabsContent>
          </div>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}

function ChapterReviewPanel({ reviews, loading, error }: { reviews: any; loading?: boolean; error?: any }) {
  const [open, setOpen] = useState(false)
  const summary = reviews?.summary || {}
  const total = summary.totalReviews || 0
  const chapterEndCount = summary.chapterEndCount || 0
  const paragraphCount = summary.totalParagraphs || 0
  const authorCount = summary.authorReviewCount || 0
  const chapterEndHot = Array.isArray(reviews?.chapterEndHot) ? reviews.chapterEndHot : []
  const hotPreview = chapterEndHot.slice(0, 3)

  if (!loading && !error && !total && !chapterEndCount && !paragraphCount && !authorCount) return null

  return (
    <>
      <div className="mb-5 rounded-xl border border-amber-200/80 bg-white/90 px-4 py-3 shadow-sm">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="flex w-full items-center justify-between"
        >
          <div className="flex items-center gap-2 text-sm font-medium text-amber-900">
            <MessageCircle className="w-4 h-4" />
            <span>本章说</span>
            {loading ? (
              <Badge variant="outline" className="text-xs flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                加载中
              </Badge>
            ) : (
              <Badge variant="secondary" className="text-xs">{formatReviewCount(total)}</Badge>
            )}
          </div>
          <div className="flex items-center gap-1 text-xs text-amber-700">
            查看评论
            <ChevronRight className="w-3 h-3" />
          </div>
        </button>

        {error && (
          <div className="mt-2 text-xs text-destructive">
            评论加载失败：{error.message || String(error)}
          </div>
        )}

        {!loading && !error && summary.vipHint && (
          <div className="mt-2 flex items-start gap-1.5 text-xs text-amber-700">
            <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
            <span>{summary.vipHint}</span>
          </div>
        )}

        {!loading && !error && hotPreview.length > 0 && (
          <div className="mt-2 space-y-2">
            {hotPreview.map((review: any, idx: number) => (
              <div key={review?.id || `hot-${idx}`} className="flex items-start gap-2 text-xs text-[#5a4331]">
                <ThumbsUp className="mt-0.5 w-3 h-3 text-amber-600 shrink-0" />
                <div className="line-clamp-2">
                  <span className="font-medium text-amber-800">{review?.userName || "匿名读者"}：</span>
                  {review?.content || "暂无评论内容"}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <ChapterReviewDialog
        reviews={reviews}
        loading={loading}
        error={error}
        open={open}
        onOpenChange={setOpen}
      />
    </>
  )
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
    case "source_done":
    case "source_complete": {
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
    case "stage_boundary":
      return `${ts}  INFO  [search] 阶段边界 | stage=${event.stage || "-"} | reason=${event.reason || "-"} | 已耗时 ${event.elapsedMs || 0}ms`
    case "overall_timeout":
      return `${ts}  WARN  [search] 整体超时截断 | reason=${event.reason || "-"} | 已耗时 ${event.elapsedMs || 0}ms`
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
  const [refreshedSourceIds, setRefreshedSourceIds] = useState<Set<string>>(new Set())
  const [bookDetail, setBookDetail] = useState<any>(null)
  const [activeChapterIndex, setActiveChapterIndex] = useState(0)
  const [showSourceFilter, setShowSourceFilter] = useState(false)
  const [selectedSourceIds, setSelectedSourceIds] = useState<Set<string>>(new Set())
  const [searchMode, setSearchMode] = useState<"source" | "aggregate">("source")
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [detailTarget, setDetailTarget] = useState<any>(null)
  // Reviews are fetched asynchronously so VIP chapter previews don't block.
  const [asyncReviews, setAsyncReviews] = useState<any>(null)
  const [asyncReviewsLoading, setAsyncReviewsLoading] = useState(false)
  const [asyncReviewsError, setAsyncReviewsError] = useState<any>(null)
  // Used to ignore stale review responses when the user switches chapters quickly.
  const latestReviewRequestKey = useRef<string>("")

  const { data: pluginsData } = useQuery({
    queryKey: ["plugins"],
    queryFn: api.plugins,
  })
  const allPlugins = pluginsData?.items || []

  const createMutation = useMutation({
    mutationFn: (payload: { keyword: string; sourceIds?: string[]; mode: "source" | "aggregate" }) =>
      payload.mode === "aggregate"
        ? api.createAggregateSearch({ keyword: payload.keyword, page: 1, sourceIds: payload.sourceIds })
        : api.createSearchJob({ keyword: payload.keyword, page: 1, sourceIds: payload.sourceIds }),
    onSuccess: (data) => {
      if (!data.jobId) return
      const initialEvents = data.events || []
      // Cache hit: the same job is reused for the background refresh.  Seed the
      // query cache with the cached response so the UI can show it immediately.
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

  const fetchReviewsMutation = useMutation({
    mutationFn: ({ candidateId, chapterIndex }: { candidateId: string; chapterIndex: number }) => {
      latestReviewRequestKey.current = `${candidateId}:${chapterIndex}`
      return api.fetchCandidateReviews(jobId!, candidateId, chapterIndex)
    },
    onMutate: () => {
      setAsyncReviewsLoading(true)
      setAsyncReviewsError(null)
    },
    onSuccess: (data, variables) => {
      const key = `${variables.candidateId}:${variables.chapterIndex}`
      if (key !== latestReviewRequestKey.current) return
      setAsyncReviews(data.result?.reviews || null)
      setAsyncReviewsLoading(false)
    },
    onError: (error, variables) => {
      const key = `${variables.candidateId}:${variables.chapterIndex}`
      if (key !== latestReviewRequestKey.current) return
      setAsyncReviewsError(error)
      setAsyncReviewsLoading(false)
    },
  })

  const verifyMutation = useMutation({
    mutationFn: ({ candidateId, chapterIndex }: { candidateId: string; chapterIndex?: number }) =>
      api.verifySearchCandidate(jobId!, candidateId, chapterIndex || 0, false),
    onMutate: () => {
      // Clear stale async reviews while new chapter content loads.
      setAsyncReviews(null)
      setAsyncReviewsError(null)
    },
    onSuccess: (data, variables) => {
      setActiveChapterIndex(variables.chapterIndex || 0)
      setBookDetail(data.result)
      fetchReviewsMutation.mutate({
        candidateId: variables.candidateId,
        chapterIndex: variables.chapterIndex || 0,
      })
    },
  })

  const { data: jobData } = useQuery({
    queryKey: ["search-job", jobId],
    queryFn: () => api.searchJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => (isTerminalStatus(query.state.data?.status) ? false : 1000),
  })

  const { data: eventsData } = useQuery({
    queryKey: ["search-job-events", jobId],
    queryFn: () => api.searchJobEvents(jobId!),
    enabled: !!jobId,
    refetchInterval: isTerminalStatus(jobData?.status) ? false : 500,
  })

  const events = useMemo(() => eventsData?.events || [], [eventsData?.events])
  const visibleJob = jobData
  const { data: recentJobsData } = useQuery({
    queryKey: ["search-jobs"],
    queryFn: api.searchJobs,
    refetchInterval: visibleJob?.status === "running" ? 3000 : false,
  })
  const recentJobs = recentJobsData?.items || []

  // Apply score filter on frontend as well for real-time events
  const scoreFilter = visibleJob?.result?.debug?.scoreFilter ?? 100

  const sourceResults = useMemo(() => {
    const isAggregateMode = visibleJob?.debug?.searchMode === "aggregate"
    const allItems = visibleJob?.result?.items || []

    if (isAggregateMode) {
      // Aggregate mode: only show aggregate items.
      return allItems.filter((item: any) => item.displayType === "aggregate")
    }

    // Source mode: show source items (live + cached fallback).
    return allItems.filter((item: any) =>
      item.displayType === "source" || !item.displayType
    ).filter((item: any) => (item.score || 0) >= scoreFilter)
  }, [visibleJob, scoreFilter])

  useEffect(() => {
    // Track sourceIds that have produced live results so we can switch the
    // cache-column badge from "刷新中" to "已刷新".
    const liveIds = new Set<string>()
    for (const event of events) {
      const sid = event.sourceId || event.item?.sourceId
      if (sid && (event.type === "result" || event.type === "source_complete")) {
        liveIds.add(sid)
      }
    }
    if (liveIds.size === 0) return
    setRefreshedSourceIds((prev) => {
      const next = new Set(prev)
      let changed = false
      for (const id of liveIds) {
        if (!next.has(id)) {
          next.add(id)
          changed = true
        }
      }
      return changed ? next : prev
    })
  }, [events])

  const logEvents = useMemo(() => visibleLogEvents(events), [events])

  const progress = useMemo(() => {
    const summary = events.find((event: any) => event.type === "summary") || {}
    const doneBySource = new Map<string, any>()
    events.forEach((event: any) => {
      if (
        event.type === "source_complete" ||
        ["source_empty", "source_timeout", "source_error"].includes(event.type)
      ) {
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
    setAsyncReviews(null)
    setAsyncReviewsError(null)
    setRefreshedSourceIds(new Set())
    const sourceIds = selectedSourceIds.size > 0 ? Array.from(selectedSourceIds) : undefined
    createMutation.mutate({ keyword: value, sourceIds, mode: searchMode })
  }

  const handleOpenDetail = (item: any) => {
    if (item.resultKind === "aggregate") {
      // Aggregate item: show aggregate info directly (no verify_candidate).
      setDetailTarget(item)
      setBookDetail({
        selectedCandidate: item,
        detail: {
          name: item.name,
          author: item.author,
          coverUrl: item.coverUrl,
          intro: item.intro,
          wordCount: item.wordCount,
          lastChapter: item.lastChapter,
          bookUrl: item.bookUrl,
          sourceName: item.sourceName,
          debug: { sourceCount: item.sourceCount },
        },
        toc: { items: [], chapterCount: 0 },
        chapter: { title: "聚合源", content: "这是一个 AI 聚合书籍，包含多个书源的结果。\n\n点击目录中的章节可从主源获取内容。", contentLength: 0 },
        status: "aggregate",
        sourceName: item.sourceName,
        aggregate: true,
        sourceCount: item.sourceCount,
      })
      setIsDetailOpen(true)
      setActiveChapterIndex(0)
      return
    }
    if (!item.candidateId) return
    setDetailTarget(item)
    setBookDetail(null)
    setIsDetailOpen(true)
    setActiveChapterIndex(0)
    verifyMutation.mutate({ candidateId: item.candidateId })
  }

  const handleOpenJob = (job: any) => {
    if (!job.jobId) return
    setBookDetail(null)
    setIsDetailOpen(false)
    setDetailTarget(null)
    setActiveChapterIndex(0)
    setAsyncReviews(null)
    setAsyncReviewsError(null)
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
  // Async reviews overlay the verify response so chapter content renders first.
  const detailReviews = asyncReviews || displayDetail?.reviews || {}
  const detailReviewSummary = detailReviews?.summary || {}
  const detailChapterEndReviews = chapterEndReviews(detailReviews)
  const showReviewSummary = hasReviewContent(detailReviews) || Boolean(detailReviews?.debug?.error) || asyncReviewsLoading || asyncReviewsError

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

          <div className="flex items-center gap-2">
            <Label className="text-sm text-muted-foreground">模式:</Label>
            <Button
              variant={searchMode === "source" ? "default" : "outline"}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setSearchMode("source")}
            >
              普通书源
            </Button>
            <Button
              variant={searchMode === "aggregate" ? "default" : "outline"}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setSearchMode("aggregate")}
            >
              书源聚合
            </Button>
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
                  {visibleJob?.status === "running" ? (
                    <Badge variant="info">搜索中</Badge>
                  ) : (
                    <Badge variant={statusVariant(visibleJob.status) as any}>{jobStatusText(visibleJob.status)}</Badge>
                  )}
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
                    <Badge variant="outline">{jobStatusText(visibleJob.status)}</Badge>
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
              <TableHead>获取时间</TableHead>
              <TableHead>评分</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sourceResults.length === 0 && (
              <TableRow>
                 <TableCell colSpan={8} className="h-28 text-center text-sm text-muted-foreground">
                  {visibleJob ? "搜索进行中，结果会实时出现" : "输入关键词后开始搜索"}
                </TableCell>
              </TableRow>
            )}
            {sourceResults.map((item: any) => {
              const sid = item.sourceId
              const isRefreshing = sid ? progress.running.some((r: any) => r.id === sid) : false
              const isRefreshed = sid ? refreshedSourceIds.has(sid) : false
              return (
                <TableRow key={item.candidateId || `${item.sourceId}-${item.bookUrl}`}>
                  <TableCell className="font-medium">{item.name || "-"}</TableCell>
                  <TableCell>{item.author || "-"}</TableCell>
                  <TableCell>
                    <div className="flex flex-col gap-1">
                      <Badge variant="outline" className="w-fit">{item.sourceName || item.sourceId || "-"}</Badge>
                      {sid && <span className="font-mono text-xs text-muted-foreground">{sid}</span>}
                    </div>
                  </TableCell>
                  <TableCell className="max-w-64 truncate">{item.lastChapter || "-"}</TableCell>
                  <TableCell>
                    <span className={`text-xs ${item.freshness === "cached" ? "text-muted-foreground" : "text-green-600"}`}>
                      {item.fetchedAt
                        ? new Date(item.fetchedAt).toLocaleString("zh-CN", {
                            month: "2-digit",
                            day: "2-digit",
                            hour: "2-digit",
                            minute: "2-digit",
                            second: "2-digit",
                          })
                        : "-"}
                    </span>
                    {item.displayType === "aggregate" && (
                      <Badge variant="secondary" className="ml-1 text-xs">聚合</Badge>
                    )}
                  </TableCell>
                  <TableCell>{item.score || 0}</TableCell>
                  <TableCell className="text-right">
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={verifyMutation.isPending || (!item.candidateId && item.resultKind !== "aggregate")}
                      onClick={() => handleOpenDetail(item)}
                    >
                      {verifyMutation.isPending && detailTarget?.candidateId === item.candidateId ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <BookOpen className="h-4 w-4" />
                      )}
                      {item.resultKind === "aggregate" ? "聚合详情" : "查看详情"}
                    </Button>
                  </TableCell>
                </TableRow>
              )
            })}
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
                        : event.type === "overall_timeout"
                          ? "text-amber-700 bg-amber-50"
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
                    <Badge variant={statusVariant(job.status) as any}>{jobStatusText(job.status)}</Badge>
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

      <Dialog open={isDetailOpen} onOpenChange={(open) => { setIsDetailOpen(open); if (!open) { setBookDetail(null); setDetailTarget(null); setAsyncReviews(null); setAsyncReviewsError(null) } }}>
        <DialogContent className="max-h-[92vh] max-w-6xl overflow-hidden p-0">
          <DialogHeader>
            <DialogTitle className="px-6 pt-6">{displayDetail?.aggregate ? "聚合书籍详情" : "小说详情"}</DialogTitle>
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
                            {detailReviewSummary.paragraphsWithReviews?.length > 0 && (
                              <div className="mt-2 text-xs text-muted-foreground">
                                有评论的段落ID: {detailReviewSummary.paragraphsWithReviews.join(", ")}
                              </div>
                            )}
                            {detailReviews?.debug?.rawSummarySnippet && (
                              <div className="mt-2 text-xs text-muted-foreground break-all">
                                summary: {detailReviews.debug.rawSummarySnippet}
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

                    <ChapterReviewPanel
                      reviews={detailReviews}
                      loading={asyncReviewsLoading}
                      error={asyncReviewsError}
                    />

                    <div className="space-y-5 text-lg leading-9">
                      {paragraphsFromContent(displayDetail?.chapter?.content, displayDetail?.chapter?.title).length > 0 ? (
                        paragraphsFromContent(displayDetail?.chapter?.content, displayDetail?.chapter?.title).map((paragraph, index) => (
                          <div key={index} className="space-y-2">
                            <div className="flex items-start gap-2">
                              <ParagraphReviewBubble
                                reviews={paragraphReviews(detailReviews, index)}
                                paragraphIndex={index}
                              />
                            </div>
                            <p className="whitespace-pre-wrap indent-8">
                              {paragraph}
                            </p>
                          </div>
                        ))
                      ) : (
                        <p className="text-center text-sm text-muted-foreground">暂无正文</p>
                      )}
                    </div>
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
