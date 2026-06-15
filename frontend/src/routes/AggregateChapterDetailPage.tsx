import { useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Separator } from "@/components/ui/separator"
import {
  ArrowLeft,
  RotateCcw,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquare,
} from "lucide-react"

function statusBadge(status?: string) {
  const map: Record<string, { label: string; variant: "success" | "warning" | "info" | "destructive" | "outline" }> = {
    processed: { label: "已完成", variant: "success" },
    completed: { label: "已完成", variant: "success" },
    success: { label: "成功", variant: "success" },
    fallback: { label: "回退", variant: "warning" },
    error: { label: "错误", variant: "destructive" },
    pending: { label: "等待中", variant: "outline" },
    running: { label: "处理中", variant: "info" },
    skipped: { label: "跳过", variant: "outline" },
  }
  const entry = map[status || ""] || { label: status || "未知", variant: "outline" as const }
  return <Badge variant={entry.variant}>{entry.label}</Badge>
}

export function AggregateChapterDetailPage() {
  const { bookId, chapterId } = useParams<{ bookId: string; chapterId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [reviewsOpen, setReviewsOpen] = useState(false)

  const { data: chapter, isLoading } = useQuery({
    queryKey: ["aggregateChapter", bookId, chapterId],
    queryFn: () => api.aggregateChapter(bookId!, chapterId!),
    enabled: !!bookId && !!chapterId,
  })

  const { data: book } = useQuery({
    queryKey: ["aggregateBook", bookId],
    queryFn: () => api.aggregateBook(bookId!),
    enabled: !!bookId,
  })

  const { data: reviewsData, isLoading: reviewsLoading } = useQuery({
    queryKey: ["aggregateChapterReviews", bookId, chapterId],
    queryFn: () => api.aggregateChapterReviews(bookId!, chapterId!),
    enabled: !!bookId && !!chapterId && reviewsOpen,
  })

  const retryMut = useMutation({
    mutationFn: () => api.retryAggregateChapter(bookId!, chapterId!),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["aggregateChapter", bookId, chapterId] }),
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        加载中...
      </div>
    )
  }

  if (!chapter) {
    return <div className="text-muted-foreground">章节未找到</div>
  }

  const alignment = chapter.sourceAlignment || chapter.alignment || {}
  const ai = chapter.aiInfo || {}
  const fallback = chapter.fallbackInfo || {}
  const reviews = reviewsData?.reviews || reviewsData?.items || []

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(`/console/aggregate-books/${bookId}`)}
        >
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <h1 className="text-xl font-semibold">{chapter.title}</h1>
        {statusBadge(chapter.status)}
      </div>

      {/* Chapter Info */}
      <Card>
        <CardContent className="py-4">
          <div className="grid grid-cols-3 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">书籍：</span>
              <span className="font-medium">{book?.name || bookId}</span>
            </div>
            <div>
              <span className="text-muted-foreground">章节序号：</span>
              <span className="font-medium">{chapter.index ?? chapter.chapterIndex ?? "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">内容长度：</span>
              <span className="font-medium">
                {chapter.contentLength?.toLocaleString() ?? "-"} 字
              </span>
            </div>
          </div>
          {(chapter.status === "error" || chapter.status === "fallback") && (
            <div className="mt-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => retryMut.mutate()}
                disabled={retryMut.isPending}
              >
                {retryMut.isPending ? (
                  <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                ) : (
                  <RotateCcw className="w-4 h-4 mr-1" />
                )}
                重试处理
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Content Preview */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">内容预览</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="max-h-80 overflow-y-auto rounded-md bg-muted/50 p-4">
            <pre className="whitespace-pre-wrap text-sm font-mono leading-relaxed">
              {chapter.content || chapter.contentPreview || "（暂无内容）"}
            </pre>
          </div>
        </CardContent>
      </Card>

      {/* Source Alignment */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">源对齐信息</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">选中内容源：</span>
              <span className="font-medium">{alignment.selectedContentSource || "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">主源：</span>
              <span className="font-medium">{alignment.primarySourceId || "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">候选源：</span>
              <span className="font-medium">{alignment.candidateSourceId || "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">标题相似度：</span>
              <span className="font-medium">
                {alignment.titleSimilarity != null
                  ? alignment.titleSimilarity.toFixed(3)
                  : "-"}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">预览相似度：</span>
              <span className="font-medium">
                {alignment.previewSimilarity != null
                  ? alignment.previewSimilarity.toFixed(3)
                  : "-"}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">对齐结果：</span>
              {alignment.alignmentPassed != null ? (
                alignment.alignmentPassed ? (
                  <Badge variant="success" className="ml-1">通过</Badge>
                ) : (
                  <Badge variant="destructive" className="ml-1">未通过</Badge>
                )
              ) : (
                <span className="font-medium">-</span>
              )}
            </div>
          </div>
          {alignment.alignmentReason && (
            <>
              <Separator className="my-3" />
              <div className="text-sm">
                <span className="text-muted-foreground">原因：</span>
                <span>{alignment.alignmentReason}</span>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* AI Info */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">AI 处理信息</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">模型：</span>
              <span className="font-medium">{ai.model || chapter.aiModel || "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">Tokens：</span>
              <span className="font-medium">
                {(ai.tokens || chapter.tokens)?.toLocaleString() ?? "-"}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">延迟：</span>
              <span className="font-medium">
                {ai.latency != null ? `${ai.latency}ms` : "-"}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">偏差分数：</span>
              <span
                className={
                  (ai.deviationScore || chapter.deviationScore) != null
                    ? (ai.deviationScore || chapter.deviationScore) < 0.8
                      ? "text-destructive font-medium"
                      : (ai.deviationScore || chapter.deviationScore) < 0.9
                        ? "text-yellow-600 font-medium"
                        : "font-medium"
                    : ""
                }
              >
                {(ai.deviationScore || chapter.deviationScore) != null
                  ? (ai.deviationScore || chapter.deviationScore).toFixed(3)
                  : "-"}
              </span>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Fallback Info */}
      {(fallback.fallbackSourceId || chapter.fallbackSourceId) && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">回退信息</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">回退源：</span>
                <span className="font-medium">
                  {fallback.fallbackSourceId || chapter.fallbackSourceId}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">错误信息：</span>
                <span className="text-destructive">
                  {fallback.error || chapter.errorMessage || "-"}
                </span>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Reviews */}
      <Card>
        <CardHeader className="pb-2 cursor-pointer" onClick={() => setReviewsOpen(!reviewsOpen)}>
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm flex items-center gap-2">
              <MessageSquare className="w-4 h-4" />
              评论审核
              {reviewsOpen ? (
                <ChevronDown className="w-4 h-4 text-muted-foreground" />
              ) : (
                <ChevronRight className="w-4 h-4 text-muted-foreground" />
              )}
            </CardTitle>
          </div>
        </CardHeader>
        {reviewsOpen && (
          <CardContent>
            {reviewsLoading ? (
              <div className="flex items-center py-4 text-muted-foreground">
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                加载评论中...
              </div>
            ) : reviews.length === 0 ? (
              <div className="text-muted-foreground text-sm py-4">暂无评论数据</div>
            ) : (
              <div className="space-y-3">
                {reviews.map((review: any, idx: number) => (
                  <div key={idx} className="rounded-md border p-3 text-sm">
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium">{review.user || "匿名"}</span>
                      <span className="text-muted-foreground text-xs">
                        {review.date
                          ? new Date(review.date).toLocaleString("zh-CN")
                          : ""}
                      </span>
                    </div>
                    <p className="text-muted-foreground">{review.content || review.text || "-"}</p>
                    {review.rating != null && (
                      <div className="mt-1">
                        <Badge variant="outline">评分: {review.rating}</Badge>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  )
}
