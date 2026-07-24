import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ChevronLeft, ChevronRight, Loader2, MessageCircle, MessagesSquare, X } from "lucide-react"
import { api, apiErrorMessage, type ChapterReviewsResponse, type ChapterReviewTab } from "@/lib/api"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"

const PAGE_GAP = 32
const SWIPE_THRESHOLD = 48

interface ReaderChapter {
  title: string
  readChapterId?: string
  sourceWordCount?: number
  contentLength?: number
}

interface PagedChapterReaderProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  chapter: ReaderChapter | null
  bookTitle: string
  bookAuthor: string
  previewMode: boolean
  content?: string | null
  contentLoading: boolean
  contentError: unknown
  onRetryContent: () => void
}

interface PageReviewSummary {
  commentCount: number
  paragraphIds: number[]
}

function countChapterReviews(reviews?: ChapterReviewsResponse): number {
  if (!reviews) return 0
  const summaryCount = Number(reviews.summary?.chapterEndCount || 0)
  if (summaryCount > 0) return summaryCount
  return Math.max(reviews.chapterEnd?.length || 0, reviews.chapterEndHot?.length || 0)
}

interface ReviewPreview {
  id: string
  userName: string
  content: string
}

function reviewStringField(review: Record<string, unknown>, fields: string[]): string {
  for (const field of fields) {
    const value = review[field]
    if (typeof value === "string" && value.trim()) return value.trim()
  }
  return ""
}

function collectReviewPreviews(
  groups: Array<Array<Record<string, unknown>> | undefined>,
  limit: number,
): ReviewPreview[] {
  const previews: ReviewPreview[] = []
  const seen = new Set<string>()
  for (const group of groups) {
    for (const review of group || []) {
      const content = reviewStringField(review, ["content", "Content"])
        .replace(/<[^>]*>/g, " ")
        .replace(/\[fn=\d+\]/g, "")
        .replace(/\s+/g, " ")
        .trim()
      if (!content) continue
      const userName = reviewStringField(review, ["userName", "UserName", "nickName"])
      const id = reviewStringField(review, ["id", "reviewId"]) || `${userName}\u0000${content}`
      if (seen.has(id)) continue
      seen.add(id)
      previews.push({ id, userName, content })
      if (previews.length >= limit) return previews
    }
  }
  return previews
}

function reviewCommentCount(item: NonNullable<ChapterReviewsResponse["hotParagraphReviews"]>[number]): number {
  return Number(item.commentCount || item.totalCommentCount || item.hotCommentCount || 0)
}

function normalizeReviewMatchText(value: string): string {
  return value
    .replace(/^\s*[#>*+-]+\s*/, "")
    .replace(/\s+/g, "")
    .replace(/[^0-9A-Za-z\u3400-\u9fff]/g, "")
}

function reviewMatchScore(candidate: string, needle: string): number {
  if (!candidate || !needle) return 0
  if (candidate === needle) return 1
  const shorter = Math.min(candidate.length, needle.length)
  const longer = Math.max(candidate.length, needle.length)
  if (shorter < 12) return 0
  if (candidate.includes(needle) || needle.includes(candidate)) {
    const coverage = shorter / longer
    return coverage >= 0.45 ? 0.82 + coverage * 0.18 : 0
  }

  const grams = (value: string) => {
    const counts = new Map<string, number>()
    for (let index = 0; index < value.length - 1; index += 1) {
      const gram = value.slice(index, index + 2)
      counts.set(gram, (counts.get(gram) || 0) + 1)
    }
    return counts
  }
  const candidateGrams = grams(candidate)
  const needleGrams = grams(needle)
  let overlap = 0
  for (const [gram, count] of candidateGrams) {
    overlap += Math.min(count, needleGrams.get(gram) || 0)
  }
  return (2 * overlap) / Math.max(1, candidate.length + needle.length - 2)
}

function findMatchedParagraphIndex(paragraphs: string[], matchedText: string): number {
  const needle = normalizeReviewMatchText(matchedText)
  if (!needle) return -1
  const ranked = paragraphs
    .map((paragraph, index) => ({
      index,
      score: reviewMatchScore(normalizeReviewMatchText(paragraph), needle),
    }))
    .sort((left, right) => right.score - left.score)
  const best = ranked[0]
  const second = ranked[1]
  const exactMatches = ranked.filter((item) => item.score === 1)
  if (exactMatches.length === 1) return exactMatches[0].index
  if (exactMatches.length > 1) return -1
  if (!best || best.score < 0.72) return -1
  if (second && best.score - second.score < 0.08) return -1
  return best.index
}

function samePageReviewSummaries(left: PageReviewSummary[], right: PageReviewSummary[]): boolean {
  if (left.length !== right.length) return false
  return left.every((item, index) => (
    item.commentCount === right[index]?.commentCount
    && item.paragraphIds.join(",") === right[index]?.paragraphIds.join(",")
  ))
}

export function PagedChapterReader({
  open,
  onOpenChange,
  chapter,
  bookTitle,
  bookAuthor,
  previewMode,
  content,
  contentLoading,
  contentError,
  onRetryContent,
}: PagedChapterReaderProps) {
  const columnsRef = useRef<HTMLElement | null>(null)
  const touchStartXRef = useRef<number | null>(null)
  const [viewportElement, setViewportElement] = useState<HTMLDivElement | null>(null)
  const [pageWidth, setPageWidth] = useState(0)
  const [pageCount, setPageCount] = useState(1)
  const [currentPage, setCurrentPage] = useState(0)
  const [reviewTab, setReviewTab] = useState<ChapterReviewTab | null>(null)
  const [reviewParagraphIds, setReviewParagraphIds] = useState<number[]>([])
  const [pageReviewSummaries, setPageReviewSummaries] = useState<PageReviewSummary[]>([])

  const chapterId = chapter?.readChapterId || ""
  const paragraphs = useMemo(
    () => String(content || "").split(/\n+/).map((line) => line.trim()).filter(Boolean),
    [content],
  )
  const reviewsQuery = useQuery<ChapterReviewsResponse>({
    queryKey: ["reading", "chapter-reviews", chapterId],
    queryFn: () => api.reading.chapterReviews(chapterId),
    enabled: open && Boolean(chapterId),
    retry: false,
  })

  const goToPage = useCallback((page: number) => {
    setCurrentPage((current) => {
      const next = Math.max(0, Math.min(pageCount - 1, page))
      return next === current ? current : next
    })
  }, [pageCount])

  useLayoutEffect(() => {
    if (!open) return
    if (!viewportElement) return

    const updateWidth = () => {
      const nextWidth = Math.max(1, Math.floor(viewportElement.clientWidth || viewportElement.getBoundingClientRect().width))
      setPageWidth(nextWidth)
    }
    updateWidth()

    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", updateWidth)
      return () => window.removeEventListener("resize", updateWidth)
    }
    const observer = new ResizeObserver(updateWidth)
    observer.observe(viewportElement)
    return () => observer.disconnect()
  }, [open, viewportElement])

  useLayoutEffect(() => {
    if (!open || !pageWidth || contentLoading || contentError || !content) return
    const columns = columnsRef.current
    if (!columns) return

    const nextCount = Math.max(1, Math.ceil((columns.scrollWidth + PAGE_GAP) / (pageWidth + PAGE_GAP)))
    setPageCount(nextCount)
    setCurrentPage((page) => Math.min(page, nextCount - 1))
  }, [content, contentError, contentLoading, open, pageWidth])

  useLayoutEffect(() => {
    const columns = columnsRef.current
    const reviews = reviewsQuery.data?.hotParagraphReviews || []
    if (!open || !columns || !viewportElement || !pageWidth || !reviews.length) {
      setPageReviewSummaries((current) => current.length ? [] : current)
      return
    }

    const step = pageWidth + PAGE_GAP
    const viewportLeft = viewportElement.getBoundingClientRect().left
    const translatedDistance = currentPage * step
    const next = Array.from({ length: pageCount }, () => ({
      commentCount: 0,
      paragraphIds: [] as number[],
    }))

    for (const review of reviews) {
      let startIndex = Number(review.matchedParagraphIndex)
      if (!Number.isInteger(startIndex) || startIndex < 0) {
        startIndex = findMatchedParagraphIndex(paragraphs, String(review.matchedText || ""))
      }
      if (!review.matchedText || !Number.isInteger(startIndex) || startIndex < 0) continue
      const paragraphCount = Math.max(1, Number(review.matchedParagraphCount) || 1)
      const pages = new Set<number>()
      for (let index = startIndex; index < startIndex + paragraphCount; index += 1) {
        const paragraph = columns.querySelector<HTMLElement>(`[data-paragraph-index="${index}"]`)
        if (!paragraph) continue
        for (const rect of Array.from(paragraph.getClientRects())) {
          const intrinsicLeft = rect.left - viewportLeft + translatedDistance
          const page = Math.max(0, Math.min(pageCount - 1, Math.round(intrinsicLeft / step)))
          pages.add(page)
        }
      }
      const paragraphId = Number(review.paragraphId)
      for (const page of pages) {
        next[page].commentCount += reviewCommentCount(review)
        if (Number.isInteger(paragraphId) && paragraphId >= 0 && !next[page].paragraphIds.includes(paragraphId)) {
          next[page].paragraphIds.push(paragraphId)
        }
      }
    }

    setPageReviewSummaries((current) => samePageReviewSummaries(current, next) ? current : next)
  }, [currentPage, open, pageCount, pageWidth, paragraphs, reviewsQuery.data, viewportElement])

  useEffect(() => {
    if (!open || reviewTab) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "ArrowLeft") {
        event.preventDefault()
        goToPage(currentPage - 1)
      } else if (event.key === "ArrowRight") {
        event.preventDefault()
        goToPage(currentPage + 1)
      }
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [currentPage, goToPage, open, reviewTab])

  const chapterReviewCount = countChapterReviews(reviewsQuery.data)
  const authorPreview = collectReviewPreviews([reviewsQuery.data?.authorReviews], 1)[0]
  const chapterPreviews = collectReviewPreviews(
    [reviewsQuery.data?.chapterEndHot, reviewsQuery.data?.chapterEnd],
    3,
  )
  const currentPageReviews = pageReviewSummaries[currentPage] || { commentCount: 0, paragraphIds: [] }
  const wordCount = chapter?.sourceWordCount || chapter?.contentLength || String(content || "").replace(/\s/g, "").length
  const reviewViewTitle = reviewTab === "paragraph"
    ? (reviewParagraphIds.length > 0 ? "页热评" : "段落评论")
    : "本章评论"

  const openReviews = (tab: ChapterReviewTab, paragraphIds: number[] = []) => {
    if (!chapterId) return
    setReviewParagraphIds(paragraphIds)
    setReviewTab(tab)
  }

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setCurrentPage(0)
      setReviewTab(null)
      setReviewParagraphIds([])
      setPageReviewSummaries([])
    }
    onOpenChange(nextOpen)
  }

  const handleTouchStart = (clientX: number) => {
    touchStartXRef.current = clientX
  }
  const handleTouchEnd = (clientX: number) => {
    const startX = touchStartXRef.current
    touchStartXRef.current = null
    if (startX === null) return
    const distance = clientX - startX
    if (Math.abs(distance) < SWIPE_THRESHOLD) return
    goToPage(distance < 0 ? currentPage + 1 : currentPage - 1)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="h-[calc(100dvh-16px)] w-[calc(100vw-16px)] max-w-[860px] gap-0 overflow-hidden border-slate-300 bg-[#f5f1e8] p-0 sm:h-[min(90dvh,820px)] sm:rounded-lg">
        <DialogHeader className="h-[58px] shrink-0 justify-center border-b border-stone-300/80 bg-white/80 px-12 py-0 text-left backdrop-blur-sm">
          <div className="min-w-0 text-center">
            <DialogTitle className="truncate text-sm font-semibold text-slate-800">{bookTitle}</DialogTitle>
            <DialogDescription className="mt-1 truncate text-[11px] text-slate-500">{bookAuthor} · 正文模拟阅读</DialogDescription>
          </div>
        </DialogHeader>

        <div className="relative flex min-h-0 min-w-0 w-full flex-1 flex-col overflow-hidden">
          <div className="mx-auto flex min-h-0 min-w-0 w-full max-w-[760px] flex-1 flex-col px-5 py-5 sm:px-10 sm:py-7">
            <div
              ref={setViewportElement}
              data-testid="chapter-reader-viewport"
              className="min-h-0 flex-1 overflow-hidden touch-pan-y"
              onTouchStart={(event) => handleTouchStart(event.changedTouches[0]?.clientX || 0)}
              onTouchEnd={(event) => handleTouchEnd(event.changedTouches[0]?.clientX || 0)}
            >
              {contentLoading ? (
                <div className="flex h-full items-center justify-center gap-2 text-sm text-slate-500">
                  <Loader2 className="h-4 w-4 animate-spin" /> 章节内容加载中
                </div>
              ) : contentError ? (
                <Alert variant="destructive" className="mt-8">
                  <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                    <span>正文加载失败：{apiErrorMessage(contentError, "请稍后重试。")}</span>
                    <Button type="button" size="sm" variant="outline" onClick={onRetryContent}>重试</Button>
                  </AlertDescription>
                </Alert>
              ) : paragraphs.length > 0 ? (
                <article
                  ref={columnsRef}
                  data-testid="chapter-reader-columns"
                  className="h-full font-serif text-[17px] leading-[1.95] text-slate-800 transition-transform duration-200 ease-out sm:text-lg sm:leading-[2.05] motion-reduce:transition-none"
                  style={{
                    columnWidth: pageWidth ? `${pageWidth}px` : undefined,
                    columnGap: `${PAGE_GAP}px`,
                    columnFill: "auto",
                    width: pageWidth ? `${pageWidth}px` : "100%",
                    transform: `translate3d(-${currentPage * (pageWidth + PAGE_GAP)}px, 0, 0)`,
                  }}
                >
                  <header className="mb-7 break-inside-avoid border-b border-stone-300/80 pb-5 sm:mb-9 sm:pb-6">
                    <div className="min-w-0">
                      <h2 className="m-0 text-2xl font-bold leading-snug text-slate-900 sm:text-[28px]">{chapter?.title}</h2>
                      <p className="mt-2 text-xs font-sans text-slate-500">本章 {wordCount.toLocaleString("zh-CN")} 字</p>
                    </div>
                    {previewMode && <Badge variant="secondary" className="mt-3 border-transparent bg-orange-100 text-orange-700">预览正文</Badge>}
                    {reviewsQuery.isError && <p className="mt-3 font-sans text-xs text-rose-600">评论暂不可用：{apiErrorMessage(reviewsQuery.error, "加载失败")}</p>}
                  </header>
                  {paragraphs.map((line, index) => (
                    <p key={index} data-paragraph-index={index} className="mb-[1.12em] text-justify indent-[2em]">{line}</p>
                  ))}
                  {authorPreview && (
                    <aside
                      data-testid="chapter-author-say"
                      className="mt-8 break-inside-avoid rounded-md border border-stone-300 bg-white/55 p-4 font-sans shadow-sm"
                    >
                      <div className="flex min-w-0 items-center gap-2">
                        <strong className="truncate text-sm text-slate-800">{authorPreview.userName || bookAuthor || "作者"}</strong>
                        <Badge className="shrink-0 border-transparent bg-indigo-100 text-indigo-700 hover:bg-indigo-100">作家说</Badge>
                      </div>
                      <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-600">{authorPreview.content}</p>
                    </aside>
                  )}
                  {chapterReviewCount > 0 && (
                    <button
                      type="button"
                      className="mt-4 block w-full break-inside-avoid rounded-md border border-slate-300 bg-white/65 p-3 text-left font-sans shadow-sm transition-colors hover:border-slate-400 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
                      onClick={() => openReviews("chapter")}
                      disabled={reviewsQuery.isLoading || reviewsQuery.isError}
                      aria-label={`本章说 ${chapterReviewCount} 条评论`}
                    >
                      <span className="grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3">
                        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-sky-50 text-sky-700"><MessageCircle className="h-5 w-5" /></span>
                        <span className="min-w-0">
                          <strong className="block text-sm text-slate-800">本章说</strong>
                          <span className="mt-1 block text-xs text-slate-500">共 {chapterReviewCount.toLocaleString("zh-CN")} 条评论</span>
                        </span>
                        <ChevronRight className="h-4 w-4 text-slate-400" />
                      </span>
                      {chapterPreviews.length > 0 && (
                        <span className="mt-3 block divide-y divide-stone-200 border-t border-stone-200">
                          {chapterPreviews.map((preview) => (
                            <span key={preview.id} className="grid grid-cols-[minmax(72px,auto)_minmax(0,1fr)] gap-3 py-2 text-xs leading-5">
                              <strong className="truncate font-medium text-slate-600">{preview.userName || "书友"}</strong>
                              <span className="line-clamp-1 text-slate-500">{preview.content}</span>
                            </span>
                          ))}
                        </span>
                      )}
                    </button>
                  )}
                </article>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-slate-400">暂无可读正文。</div>
              )}
            </div>
          </div>

          <footer className="grid h-[54px] shrink-0 grid-cols-[44px_minmax(0,1fr)_44px] items-center border-t border-stone-300/80 bg-white/70 px-4 backdrop-blur-sm">
            <Button type="button" variant="ghost" size="icon" className="h-9 w-9" onClick={() => goToPage(currentPage - 1)} disabled={currentPage <= 0} aria-label="上一页" title="上一页">
              <ChevronLeft className="h-5 w-5" />
            </Button>
            <div className="flex min-w-0 items-center justify-center gap-3">
              <span data-testid="chapter-reader-page-indicator" className="font-mono text-xs text-slate-500" aria-live="polite">{currentPage + 1} / {pageCount}</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 shrink-0 rounded-full px-2.5 text-sky-800 hover:bg-sky-50"
                onClick={() => openReviews("paragraph", currentPageReviews.paragraphIds)}
                disabled={reviewsQuery.isLoading || reviewsQuery.isError || currentPageReviews.commentCount <= 0}
                aria-label={`页热评 ${currentPageReviews.commentCount} 条`}
              >
                {reviewsQuery.isLoading ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <MessagesSquare className="mr-1.5 h-4 w-4" />}
                热评 <span className="ml-1 font-mono text-xs">{currentPageReviews.commentCount}</span>
              </Button>
            </div>
            <Button type="button" variant="ghost" size="icon" className="h-9 w-9" onClick={() => goToPage(currentPage + 1)} disabled={currentPage >= pageCount - 1} aria-label="下一页" title="下一页">
              <ChevronRight className="h-5 w-5" />
            </Button>
          </footer>

          {reviewTab && chapterId && (
            <div className="absolute inset-0 z-30 flex items-end justify-center bg-slate-950/45 p-0 sm:p-5" onMouseDown={(event) => { if (event.target === event.currentTarget) setReviewTab(null) }}>
              <section className="relative h-[min(82dvh,700px)] w-full max-w-[720px] overflow-hidden rounded-t-2xl border border-b-0 border-slate-300 bg-white shadow-2xl sm:h-[min(78dvh,700px)] sm:rounded-b-lg sm:border-b" role="dialog" aria-label={reviewViewTitle}>
                <Button type="button" variant="ghost" size="icon" className="absolute right-3 top-3 z-10 h-8 w-8 bg-white/90" onClick={() => setReviewTab(null)} aria-label="关闭评论" title="关闭评论">
                  <X className="h-4 w-4" />
                </Button>
                <iframe
                  className="h-full w-full border-0"
                  src={api.reading.chapterReviewsViewUrl(chapterId, reviewTab, reviewParagraphIds)}
                  title={reviewViewTitle}
                />
              </section>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
