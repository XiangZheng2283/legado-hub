import { useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  ChevronLeft,
  Loader2,
  ScrollText,
  Waypoints,
} from "lucide-react"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ScrollArea } from "@/components/ui/scroll-area"

interface TraceSummary {
  chapterStatus?: string
  selectedSource?: string
  selectedContentSource?: string
  fallbackSourceId?: string
  alignmentPassed?: boolean | null
  alignmentReason?: string
  titleSimilarity?: number | null
  previewSimilarity?: number | null
  aiModel?: string
  aiTokens?: number
  processedAt?: string
  traceHash?: string
}

interface ChapterProgressDetail {
  found?: boolean
  bookId: string
  chapterId: string
  chapterIndex: number
  title: string
  status: string
  previewOnly: boolean
  contentLength: number
  sourceWordCount: number
  traceSummary?: TraceSummary
}

function statusBadge(status?: string) {
  const map: Record<
    string,
    { label: string; variant: "success" | "warning" | "info" | "destructive" | "outline" }
  > = {
    processed: { label: "已处理", variant: "success" },
    completed: { label: "已完成", variant: "success" },
    fallback: { label: "回退", variant: "warning" },
    error: { label: "失败", variant: "destructive" },
    pending: { label: "待处理", variant: "outline" },
    active: { label: "处理中", variant: "info" },
  }
  const entry = map[status || ""] || { label: status || "未知", variant: "outline" as const }
  return <Badge variant={entry.variant}>{entry.label}</Badge>
}

function formatDate(value?: string | null) {
  if (!value) return "-"
  try {
    return new Date(value).toLocaleString("zh-CN")
  } catch {
    return value
  }
}

function formatDecimal(value?: number | null) {
  return value == null ? "-" : value.toFixed(3)
}

function deriveStageState(progress?: ChapterProgressDetail) {
  const trace = progress?.traceSummary || {}
  const status = progress?.status || trace.chapterStatus || ""
  const hasSelection = Boolean(trace.selectedSource || trace.selectedContentSource)
  const hasAiResult = Boolean(trace.aiModel || (trace.aiTokens || 0) > 0 || trace.processedAt)
  const isDone = status === "processed" || status === "fallback" || status === "completed"
  const isError = status === "error"

  const currentStage = isDone ? "Stage 3" : hasAiResult ? "Stage 3" : hasSelection ? "Stage 2" : "Stage 1"
  const failureReason =
    trace.alignmentReason ||
    (isError ? "处理失败" : status === "fallback" ? "已回退到备用结果" : "")

  return {
    currentStage,
    failureReason,
    nodes: [
      {
        id: "stage1",
        label: "Stage 1",
        state: hasSelection || hasAiResult || isDone ? "done" : "current",
        detail: trace.selectedSource || "选源中",
      },
      {
        id: "stage2",
        label: "Stage 2",
        state: hasAiResult || isDone ? "done" : hasSelection ? "current" : "waiting",
        detail: trace.selectedContentSource || trace.aiModel || "处理中",
      },
      {
        id: "stage3",
        label: "Stage 3",
        state: isDone ? "done" : hasAiResult ? "current" : "waiting",
        detail: statusBadgeText(status),
      },
    ] as const,
  }
}

function statusBadgeText(status?: string) {
  if (status === "processed") return "已处理"
  if (status === "fallback") return "回退"
  if (status === "error") return "失败"
  if (status === "pending") return "待处理"
  return status || "等待中"
}

function stageNodeClass(state: string) {
  if (state === "done") return "border-green-200 bg-green-50 text-green-800"
  if (state === "current") return "border-blue-200 bg-blue-50 text-blue-800"
  return "border-border bg-muted/40 text-muted-foreground"
}

export function LibraryChapterDetailPage() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>()
  const navigate = useNavigate()
  const [progressOpen, setProgressOpen] = useState(false)

  const bookQuery = useQuery({
    queryKey: ["library", "book", bookId, "summary"],
    queryFn: () => api.libraryBookSummary(bookId!),
    enabled: !!bookId,
  })

  const progressQuery = useQuery({
    queryKey: ["library", "book", bookId, "chapter", chapterId, "progress"],
    queryFn: () => api.libraryBookChapterProgress(bookId!, chapterId!),
    enabled: !!bookId && !!chapterId,
    refetchInterval: 5000,
  })

  const chapter = progressQuery.data as ChapterProgressDetail | undefined
  const trace = chapter?.traceSummary || {}
  const stageState = useMemo(() => deriveStageState(chapter), [chapter])

  if (progressQuery.isLoading) {
    return (
      <div className="flex min-h-[300px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!chapter || chapter.found === false) {
    return <div className="text-muted-foreground">章节不存在或已删除。</div>
  }

  return (
    <div className="space-y-4">
      <Button
        variant="outline"
        size="sm"
        onClick={() => navigate(`/console/library/${bookId}`)}
      >
        <ChevronLeft className="mr-1 h-4 w-4" />
        返回章节列表
      </Button>

      <div className="flex items-center gap-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{chapter.title}</h1>
            {statusBadge(chapter.status)}
          </div>
          <div className="text-sm text-muted-foreground">
            {bookQuery.data?.displayName || bookId} / 第 {chapter.chapterIndex} 章
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">章节概览</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 text-sm md:grid-cols-2">
              <div>
                <div className="text-xs text-muted-foreground">当前阶段</div>
                <div className="font-medium">{stageState.currentStage}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">失败原因</div>
                <div className="font-medium">{stageState.failureReason || "-"}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">内容长度</div>
                <div className="font-medium">{chapter.contentLength || 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">来源字数</div>
                <div className="font-medium">{chapter.sourceWordCount || 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">预览模式</div>
                <div className="font-medium">{chapter.previewOnly ? "是" : "否"}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">处理时间</div>
                <div className="font-medium">{formatDate(trace.processedAt)}</div>
              </div>
            </div>
            <div className="mt-4">
              <Button variant="outline" size="sm" onClick={() => setProgressOpen(true)}>
                <Waypoints className="h-4 w-4" />
                查看进度
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Trace 摘要</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">选中来源</div>
                <div className="font-medium">{trace.selectedSource || "-"}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">内容来源</div>
                <div className="font-medium">{trace.selectedContentSource || "-"}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">回退来源</div>
                <div className="font-medium">{trace.fallbackSourceId || "-"}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">AI 模型</div>
                <div className="font-medium">{trace.aiModel || "-"}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">AI Tokens</div>
                <div className="font-medium">{trace.aiTokens?.toLocaleString() || 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Trace Hash</div>
                <div className="break-all font-medium">{trace.traceHash || "-"}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">对齐与失败信息</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 text-sm md:grid-cols-2">
            <div>
              <div className="text-xs text-muted-foreground">对齐结果</div>
              <div className="font-medium">
                {trace.alignmentPassed == null ? "-" : trace.alignmentPassed ? "通过" : "未通过"}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">对齐原因</div>
              <div className="font-medium">{trace.alignmentReason || "-"}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">标题相似度</div>
              <div className="font-medium">{formatDecimal(trace.titleSimilarity)}</div>
            </div>
            <div>
              <div className="text-xs text-muted-foreground">预览相似度</div>
              <div className="font-medium">{formatDecimal(trace.previewSimilarity)}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      <Dialog open={progressOpen} onOpenChange={setProgressOpen}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>章节进度</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
            <div className="space-y-3">
              {stageState.nodes.map((node, index) => (
                <div key={node.id} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <div
                      className={`flex h-10 w-10 items-center justify-center rounded-full border text-xs font-semibold ${stageNodeClass(node.state)}`}
                    >
                      {index + 1}
                    </div>
                    {index < stageState.nodes.length - 1 && (
                      <div className="mt-1 h-8 w-px bg-border" />
                    )}
                  </div>
                  <div className="flex-1 rounded-lg border p-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-medium">{node.label}</div>
                      <Badge variant={node.state === "done" ? "success" : node.state === "current" ? "info" : "outline"}>
                        {node.state === "done" ? "完成" : node.state === "current" ? "当前" : "等待"}
                      </Badge>
                    </div>
                    <div className="mt-1 text-sm text-muted-foreground">{node.detail || "-"}</div>
                  </div>
                </div>
              ))}
            </div>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <ScrollText className="h-4 w-4" />
                  日志面板
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="h-[320px] pr-4">
                  <div className="space-y-3 text-sm">
                    <div className="rounded-lg border p-3">
                      <div className="text-xs text-muted-foreground">阶段</div>
                      <div className="font-medium">{stageState.currentStage}</div>
                    </div>
                    <div className="rounded-lg border p-3">
                      <div className="text-xs text-muted-foreground">失败原因</div>
                      <div className="font-medium">{stageState.failureReason || "-"}</div>
                    </div>
                    <div className="rounded-lg border p-3">
                      <div className="text-xs text-muted-foreground">选中来源</div>
                      <div className="font-medium">{trace.selectedSource || "-"}</div>
                    </div>
                    <div className="rounded-lg border p-3">
                      <div className="text-xs text-muted-foreground">内容来源</div>
                      <div className="font-medium">{trace.selectedContentSource || "-"}</div>
                    </div>
                    <div className="rounded-lg border p-3">
                      <div className="text-xs text-muted-foreground">处理时间</div>
                      <div className="font-medium">{formatDate(trace.processedAt)}</div>
                    </div>
                    <div className="rounded-lg border p-3">
                      <div className="text-xs text-muted-foreground">AI</div>
                      <div className="font-medium">
                        {trace.aiModel || "-"} / {(trace.aiTokens || 0).toLocaleString()}
                      </div>
                    </div>
                    <div className="rounded-lg border p-3">
                      <div className="text-xs text-muted-foreground">Trace Hash</div>
                      <div className="break-all font-medium">{trace.traceHash || "-"}</div>
                    </div>
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
