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

function ReviewItem({ review }: { review: any }) {
  const badges = review.badges || []
  return (
    <div className="rounded-md border p-3 text-sm space-y-1">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium truncate">{review.userName || "匿名"}</span>
          {badges.map((b: string, i: number) => (
            <Badge key={i} variant="secondary" className="text-xs shrink-0">{b}</Badge>
          ))}
          {review.authorReview && <Badge variant="outline" className="text-xs shrink-0">作者</Badge>}
        </div>
        <span className="text-muted-foreground text-xs shrink-0">{review.reviewTime || ""}</span>
      </div>
      <p className="text-muted-foreground">{review.content || "-"}</p>
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        {review.likeNum != null && review.likeNum > 0 && <span>赞 {review.likeNum}</span>}
        {review.replyCount != null && review.replyCount > 0 && <span>回复 {review.replyCount}</span>}
        {review.ipAddress && <span>{review.ipAddress}</span>}
      </div>
      {review.replies && review.replies.length > 0 && (
        <div className="pl-3 mt-2 space-y-2 border-l-2 border-muted">
          {review.replies.map((reply: any, idx: number) => (
            <ReviewItem key={idx} review={reply} />
          ))}
        </div>
      )}
    </div>
  )
}

function ReviewSection({ title, reviews }: { title: string; reviews: any[] }) {
  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">{title}</h4>
      <div className="space-y-2">
        {reviews.map((review: any, idx: number) => (
          <ReviewItem key={review.id || idx} review={review} />
        ))}
      </div>
    </div>
  )
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

  // Reviews contract from backend:
  // chapterEndHot / chapterEnd / authorReviews / hotParagraphReviews / paragraphs / summary
  const summary = reviewsData?.summary || {}
  const chapterEndHot = reviewsData?.chapterEndHot || []
  const chapterEnd = reviewsData?.chapterEnd || []
  const authorReviews = reviewsData?.authorReviews || []
  const hotParagraphReviews = reviewsData?.hotParagraphReviews || []
  const paragraphReviews = reviewsData?.paragraphs || {}
  const hasAnyReviews =
    chapterEndHot.length > 0 ||
    chapterEnd.length > 0 ||
    authorReviews.length > 0 ||
    hotParagraphReviews.length > 0 ||
    Object.keys(paragraphReviews).length > 0

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
              <span className="text-muted-foreground">回退源：</span>
              <span className="font-medium">{alignment.fallbackSourceId || chapter.fallbackSourceId || "-"}</span>
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
              <span className="text-muted-foreground">Prompt Tokens：</span>
              <span className="font-medium">
                {ai.promptTokens?.toLocaleString() ?? "-"}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Completion Tokens：</span>
              <span className="font-medium">
                {ai.completionTokens?.toLocaleString() ?? "-"}
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
            <div>
              <span className="text-muted-foreground">AI 自评分：</span>
              <span className="font-medium">
                {ai.aiSelfScore != null ? ai.aiSelfScore.toFixed(3) : chapter.aiSelfScore != null ? chapter.aiSelfScore.toFixed(3) : "-"}
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
            ) : !hasAnyReviews ? (
              <div className="space-y-2 py-4 text-sm text-muted-foreground">
                <div>暂无评论数据</div>
                {reviewsData?.mappingReason && (
                  <div className="text-xs">
                    映射原因：{reviewsData.mappingReason}
                    {reviewsData.mappedSourceId && ` / 源：${reviewsData.mappedSourceId}`}
                    {reviewsData.mappedChapterId && ` / 章节：${reviewsData.mappedChapterId}`}
                  </div>
                )}
              </div>
            ) : (
              <div className="space-y-4">
                {summary && (
                  <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                    {summary.chapterEndHot != null && <Badge variant="outline">章末热评 {summary.chapterEndHot}</Badge>}
                    {summary.chapterEnd != null && <Badge variant="outline">本章说 {summary.chapterEnd}</Badge>}
                    {summary.authorReviews != null && <Badge variant="outline">作家说 {summary.authorReviews}</Badge>}
                    {summary.hotParagraphReviews != null && <Badge variant="outline">热段评 {summary.hotParagraphReviews}</Badge>}
                    {summary.paragraphReviewCount != null && <Badge variant="outline">段评总数 {summary.paragraphReviewCount}</Badge>}
                  </div>
                )}

                {authorReviews.length > 0 && (
                  <ReviewSection title="作家说" reviews={authorReviews} />
                )}
                {chapterEndHot.length > 0 && (
                  <ReviewSection title="章末热评" reviews={chapterEndHot} />
                )}
                {chapterEnd.length > 0 && (
                  <ReviewSection title="本章说" reviews={chapterEnd} />
                )}
                {hotParagraphReviews.length > 0 && (
                  <ReviewSection title="热段评" reviews={hotParagraphReviews} />
                )}
                {Object.keys(paragraphReviews).length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-sm font-medium">段落评论</h4>
                    {Object.entries(paragraphReviews).map(([pid, list]: [string, any]) => (
                      <ReviewSection key={pid} title={`段落 #${pid}`} reviews={list as any[]} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  )
}
