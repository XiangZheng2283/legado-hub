import { useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowLeft, RefreshCw, Trash2, Code2, Link, Terminal, MoreVertical, Crown, Search, Loader2, ChevronLeft, ChevronRight, Settings2, Play, Pause, Archive,
} from "lucide-react"
import { api, apiErrorMessage } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { executeLibraryBookMaintenanceAction } from "@/lib/library-actions"
import { LogStream } from "@/components/shared/LogStream"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"

interface SourceMapSummaryItem {
  sourceId: string; sourceName: string; score: number; chapterCount: number; lastChapter: string; bookStatus: string
}
interface BookStateSummary {
  status?: string; searchVisibilityStatus?: string; chapterCount?: number; processedChapterCount?: number
  readableChapterCount?: number; previewChapterCount?: number; suspectChapterCount?: number
  failedChapterCount?: number; lastUpdateCheckAt?: string
}
interface LibraryBookDetail {
  found?: boolean; aggregateBookId: string; displayName: string; displayAuthor: string
  coverUrl?: string; intro?: string; wordCount?: string; totalChapters: number; processedChapters: number
  visibleProcessedChapters: number; failedChapters?: number; status: string; bookStatus: string
  primarySourceId?: string; primarySourceName?: string; addedByUsername?: string; lastChapterTitle?: string
  lastCheckedAt?: string; startChapterIndex?: number; totalChaptersAtSubscribe?: number
  currentPolicyVersion?: number; autoArchiveOnComplete?: boolean; searchVisibilityStatus?: string
  lastError?: string; nextCheckTime?: string; bookState?: BookStateSummary; freeChapterEndIndex?: number
  sourceMapSummary?: SourceMapSummaryItem[]; sourceMapRefresh?: { completed?: boolean; status?: string; lastVerifiedAt?: string; missingCriticalSource?: boolean }
  processingSettings?: { updateIntervalMinutes: number; backlogChapterLimit: number }; intervalMinutes?: number
  subscription?: { status: "active" | "paused" | "archived"; startChapterIndex: number; autoArchiveOnComplete: boolean }
  personalProgress?: { rangeStartIndex: number; rangeEndIndex: number; fullCount: number; previewCount: number; failedCount: number; pendingCount: number; continuousReadableThroughIndex: number; coverageRatio: number }
}
interface LibraryChapterListItem {
  chapterId: string; chapterIndex: number; title: string; status: string; sourceId?: string; error?: string; isVip?: boolean; previewOnly?: boolean; sourceWordCount?: number; contentLength?: number; hasContent?: boolean; readChapterId?: string
}

function processStatusMap(status: string) {
  const m: Record<string, { label: string; color: string }> = {
    active: { label: "处理中", color: "bg-blue-100 text-blue-700" },
    paused: { label: "已暂停", color: "bg-orange-100 text-orange-700" },
    error: { label: "异常", color: "bg-rose-100 text-rose-700" },
    archived: { label: "已归档", color: "bg-slate-100 text-slate-700" },
    completed: { label: "已完成", color: "bg-emerald-100 text-emerald-700" },
  }
  return m[status] || { label: status || "未知", color: "bg-slate-100 text-slate-700" }
}

function chapterStatusLabel(status: string) {
  const m: Record<string, string> = { readable: "可阅读", supplemented: "可阅读", proofread_complete: "可阅读", fetched: "预览", preview: "预览", suspect: "存疑", failed: "失败", pending: "待处理", fallback: "可阅读", error: "失败" }
  return m[status] || "待处理"
}
function chapterStatusColor(status: string) {
  if (["readable", "supplemented", "proofread_complete", "fallback"].includes(status)) return "text-emerald-600"
  if (["fetched", "preview"].includes(status)) return "text-orange-500"
  if (["suspect", "failed", "error"].includes(status)) return "text-rose-600"
  return "text-slate-400"
}

const readableChapterStatuses = new Set(["readable", "supplemented", "proofread_complete", "fallback"])
const previewChapterStatuses = new Set(["fetched", "preview", "suspect"])

function canReadChapter(chapter: LibraryChapterListItem) {
  if (!chapter.readChapterId) return false
  if (readableChapterStatuses.has(chapter.status)) return true
  return previewChapterStatuses.has(chapter.status) && Boolean(chapter.hasContent || chapter.contentLength)
}

function formatDate(v?: string | null) { if (!v) return "-"; try { return new Date(v).toLocaleString("zh-CN") } catch { return v } }

export function LibraryBookDetailPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  const [chapterKeyword, setChapterKeyword] = useState("")
  const [chapterStatusFilter, setChapterStatusFilter] = useState("all")
  const [chapterPage, setChapterPage] = useState(1)
  const [readingChapter, setReadingChapter] = useState<LibraryChapterListItem | null>(null)
  const [previewMode, setPreviewMode] = useState(false)
  const [openAdminMenu, setOpenAdminMenu] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [startChapterIndex, setStartChapterIndex] = useState("1")
  const [autoArchiveOnComplete, setAutoArchiveOnComplete] = useState(true)
  const [processingSettingsOpen, setProcessingSettingsOpen] = useState(false)
  const [updateIntervalMinutes, setUpdateIntervalMinutes] = useState("60")
  const [backlogChapterLimit, setBacklogChapterLimit] = useState("25")

  const { data: book, isLoading, error: bookError, refetch: refetchBook } = useQuery<LibraryBookDetail | null>({
    queryKey: ["library", "book", bookId, "summary"],
    queryFn: () => isAdmin ? api.libraryBookSummary(bookId!) : api.subscribe.book(bookId!),
    enabled: !!bookId,
    refetchInterval: 5000,
  })
  const { data: chaptersData, isFetching: chaptersFetching, error: chaptersError, refetch: refetchChapters } = useQuery({
    queryKey: ["library", "book", bookId, "chapters", { status: chapterStatusFilter, keyword: chapterKeyword, page: chapterPage }],
    queryFn: () => {
      const params: Record<string, string> = { page: String(chapterPage), pageSize: "200" }
      if (chapterStatusFilter !== "all") params.status = chapterStatusFilter
      if (chapterKeyword) params.keyword = chapterKeyword
      return isAdmin ? api.libraryBookChapters(bookId!, params) : api.subscribe.chapters(bookId!, params)
    },
    enabled: !!bookId,
  })

  const refreshQueries = () => {
    queryClient.invalidateQueries({ queryKey: ["library", "book", bookId] })
    queryClient.invalidateQueries({ queryKey: ["library"] })
  }
  const actionMutation = useMutation({
    mutationFn: (action: string) => executeLibraryBookMaintenanceAction(bookId!, action),
    onSuccess: refreshQueries,
  })
  const chapterProcessMutation = useMutation({
    mutationFn: (chapterId: string) => api.processLibraryBookChapter(bookId!, chapterId),
    onSuccess: refreshQueries,
  })
  const deleteMutation = useMutation({
    mutationFn: () => api.deleteLibraryBook(bookId!),
    onSuccess: () => navigate("/console/library"),
  })
  const subscriptionMutation = useMutation({
    mutationFn: (payload: { status?: "active" | "paused" | "archived"; startChapterIndex?: number; autoArchiveOnComplete?: boolean }) =>
      api.subscribe.updateSubscription(bookId!, payload),
    onSuccess: () => {
      setSettingsOpen(false)
      refreshQueries()
    },
  })
  const processingSettingsMutation = useMutation({
    mutationFn: (payload: { updateIntervalMinutes: number; backlogChapterLimit: number }) =>
      api.updateLibraryBookSettings(bookId!, payload),
    onSuccess: () => {
      setProcessingSettingsOpen(false)
      refreshQueries()
    },
  })

  const chapterBodyQuery = useQuery({
    queryKey: ["library", "chapter-body", readingChapter?.readChapterId],
    queryFn: () => isAdmin
      ? api.chapter(readingChapter!.readChapterId!)
      : api.subscribe.chapter(readingChapter!.readChapterId!),
    enabled: !!(readingChapter?.readChapterId),
  })
  const maintenanceBusy = actionMutation.isPending || chapterProcessMutation.isPending || deleteMutation.isPending || subscriptionMutation.isPending || processingSettingsMutation.isPending

  if (isLoading) return <div className="flex min-h-[300px] items-center justify-center"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div>
  if (bookError) return (
    <Alert variant="destructive">
      <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
        <span>书籍加载失败：{apiErrorMessage(bookError, "请稍后重试。")}</span>
        <Button type="button" size="sm" variant="outline" onClick={() => { void refetchBook() }}>重试</Button>
      </AlertDescription>
    </Alert>
  )
  if (!book || book.found === false) return <div className="text-slate-500">书籍不存在或已删除。</div>

  const chapters: LibraryChapterListItem[] = chaptersData?.items || chaptersData?.chapters || []
  const chapterPageSize = Number(chaptersData?.pageSize || 200)
  const chapterTotal = Number(chaptersData?.total ?? chapters.length)
  const chapterPageCount = Math.max(1, Math.ceil(chapterTotal / chapterPageSize))
  const personal = book.personalProgress
  const subscription = book.subscription
  const progress = isAdmin
    ? (book.totalChapters > 0 ? Math.round((book.processedChapters / book.totalChapters) * 100) : 0)
    : Math.round(Math.max(0, Math.min(1, personal?.coverageRatio ?? 0)) * 100)
  const bs = book.bookState || {}
  const readable = isAdmin ? (bs.readableChapterCount ?? book.visibleProcessedChapters) : (personal?.fullCount ?? 0)
  const previewCount = isAdmin ? (bs.previewChapterCount ?? 0) : (personal?.previewCount ?? 0)
  const failedCount = isAdmin ? (bs.failedChapterCount ?? book.failedChapters ?? 0) : (personal?.failedCount ?? 0)
  const displayStatus = isAdmin ? book.status : subscription?.status || "unknown"
  const psm = processStatusMap(displayStatus)
  const sourceMap = book.sourceMapSummary || []

  const handleChapterClick = (c: LibraryChapterListItem) => {
    if (!canReadChapter(c)) return
    setPreviewMode(c.previewOnly || c.status === "fetched" || c.status === "preview")
    setReadingChapter(c)
  }

  const openSubscriptionSettings = () => {
    setStartChapterIndex(String(subscription?.startChapterIndex ?? 1))
    setAutoArchiveOnComplete(subscription?.autoArchiveOnComplete ?? true)
    setSettingsOpen(true)
  }
  const openProcessingSettings = () => {
    setUpdateIntervalMinutes(String(book.processingSettings?.updateIntervalMinutes ?? book.intervalMinutes ?? 60))
    setBacklogChapterLimit(String(book.processingSettings?.backlogChapterLimit ?? 25))
    processingSettingsMutation.reset()
    setProcessingSettingsOpen(true)
  }
  const processingInterval = Number(updateIntervalMinutes)
  const processingBacklog = Number(backlogChapterLimit)
  const processingSettingsValid = Number.isInteger(processingInterval)
    && processingInterval >= 10
    && processingInterval <= 1440
    && Number.isInteger(processingBacklog)
    && processingBacklog >= 5
    && processingBacklog <= 100

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-10">
      <Button variant="ghost" className="mb-4 -ml-4" onClick={() => navigate(-1)}>
        <ArrowLeft className="h-4 w-4 mr-2" /> 返回书库
      </Button>

      {(actionMutation.error || chapterProcessMutation.error || deleteMutation.error || subscriptionMutation.error || processingSettingsMutation.error || chaptersError) && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{apiErrorMessage(actionMutation.error || chapterProcessMutation.error || deleteMutation.error || subscriptionMutation.error || processingSettingsMutation.error || chaptersError, "操作失败，请稍后重试。")}</span>
            {chaptersError && (
              <Button type="button" size="sm" variant="outline" onClick={() => { void refetchChapters() }}>
                重试章节列表
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      {/* Hero */}
      <div className="bg-white rounded-2xl p-6 shadow-sm border border-slate-200 flex flex-col md:flex-row gap-8 relative">
        <div className="relative w-32 h-48 md:w-40 md:h-60 bg-slate-200 rounded-lg overflow-hidden shrink-0 shadow-md">
          {book.coverUrl ? <img src={book.coverUrl} alt={book.displayName} width={128} height={176} loading="lazy" className="w-full h-full object-cover" /> : <div className="flex h-full w-full items-center justify-center text-slate-400"><Search className="h-8 w-8" /></div>}
        </div>
        <div className="flex flex-col flex-1">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-slate-900">{book.displayName}</h1>
              <p className="text-lg text-slate-500 mt-1">{book.displayAuthor || "未知作者"}</p>
            </div>
            {isAdmin && (
              <div className="flex items-center gap-2 relative">
                <Button variant="outline" size="sm" onClick={openProcessingSettings} disabled={maintenanceBusy}><Settings2 className="h-4 w-4 mr-2" /> 处理设置</Button>
                <Button variant="outline" size="sm" onClick={() => actionMutation.mutate("check-update")} disabled={maintenanceBusy}><RefreshCw className="h-4 w-4 mr-2" /> 检查更新</Button>
                <Button variant="ghost" size="icon" onClick={() => setOpenAdminMenu(!openAdminMenu)}><MoreVertical className="h-5 w-5" /></Button>
                {openAdminMenu && (
                  <div className="absolute right-0 top-full mt-1 w-40 bg-white rounded-md shadow-lg border border-slate-100 overflow-hidden z-10" onClick={() => setOpenAdminMenu(false)}>
                    <button disabled={maintenanceBusy} className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50" onClick={() => actionMutation.mutate("refresh-sources")}>刷新源映射</button>
                    <button disabled={maintenanceBusy} className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50" onClick={() => actionMutation.mutate("repair")}>重新计算状态</button>
                    <button disabled={maintenanceBusy} className="w-full text-left px-4 py-2 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50" onClick={() => actionMutation.mutate("rebuild")}>重建</button>
                    <div className="h-px bg-slate-100 my-1" />
                    <button disabled={maintenanceBusy} className="w-full text-left px-4 py-2 text-sm text-rose-600 hover:bg-rose-50 disabled:opacity-50 flex items-center" onClick={() => { if (confirm("确定要删除这本书吗？")) deleteMutation.mutate() }}>
                      <Trash2 className="h-3 w-3 mr-2" /> 删除书籍
                    </button>
                  </div>
                )}
              </div>
            )}
            {!isAdmin && subscription && (
              <div className="flex flex-wrap items-center justify-start gap-2 sm:justify-end">
                {subscription.status === "active" ? (
                  <Button variant="outline" size="sm" onClick={() => subscriptionMutation.mutate({ status: "paused" })} disabled={maintenanceBusy}>
                    <Pause className="mr-2 h-4 w-4" /> 暂停
                  </Button>
                ) : (
                  <Button variant="outline" size="sm" onClick={() => subscriptionMutation.mutate({ status: "active" })} disabled={maintenanceBusy}>
                    <Play className="mr-2 h-4 w-4" /> 恢复
                  </Button>
                )}
                {subscription.status !== "archived" && (
                  <Button variant="outline" size="sm" onClick={() => subscriptionMutation.mutate({ status: "archived" })} disabled={maintenanceBusy}>
                    <Archive className="mr-2 h-4 w-4" /> 归档
                  </Button>
                )}
                <Button variant="ghost" size="icon" onClick={openSubscriptionSettings} disabled={maintenanceBusy} title="订阅设置" aria-label="订阅设置">
                  <Settings2 className="h-5 w-5" />
                </Button>
              </div>
            )}
          </div>

          <div className="flex flex-wrap gap-2 mt-4 items-center">
            <Badge variant={book.bookStatus === "completed" ? "secondary" : "outline"}>{book.bookStatus === "completed" ? "已完结" : "连载中"}</Badge>
            {book.wordCount && <Badge variant="outline">{book.wordCount.replace(/字$/, "")} 字</Badge>}
            {book.lastChapterTitle && <Badge variant="outline">最新: {book.lastChapterTitle}</Badge>}
            <span className={`px-2.5 py-0.5 rounded-full text-xs font-medium ${psm.color}`}>{psm.label}</span>
          </div>

          {book.intro && (
            <div className="mt-4 text-sm text-slate-600 bg-slate-50 p-4 rounded-xl border border-slate-100 leading-relaxed max-w-3xl">
              <span className="font-semibold text-slate-700 block mb-1">书籍简介</span>
              {book.intro}
            </div>
          )}

          <div className="mt-auto pt-6">
            <div className="flex justify-between text-sm mb-2">
              <span className="text-slate-700 font-medium">{isAdmin ? "共享处理进度" : "订阅范围覆盖率"}</span>
              <span className="text-slate-500">
                {isAdmin
                  ? `${book.processedChapters} / ${book.totalChapters} 章 (${progress}%)`
                  : `全文 ${personal?.fullCount ?? 0} · 预览 ${personal?.previewCount ?? 0} · ${progress}%`}
              </span>
            </div>
            <Progress value={progress} className="h-2" />
          </div>
        </div>
      </div>

      {/* Metadata + Source Map */}
      <div className={isAdmin ? "grid lg:grid-cols-2 gap-6" : "w-full"}>
        <Card>
          <CardHeader className="py-4 border-b border-slate-100"><CardTitle className="text-sm font-medium flex items-center"><Code2 className="h-4 w-4 mr-2 text-slate-400" /> {isAdmin ? "元数据" : "订阅状态"}</CardTitle></CardHeader>
          <CardContent className="p-4 text-sm space-y-4">
            {isAdmin ? (
              <>
            <div className="grid sm:grid-cols-2 gap-6">
              <div className="space-y-2">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">基本信息</h4>
                <div className="grid grid-cols-2 gap-y-2">
                  <div className="text-slate-500">添加人</div><div className="text-slate-900 text-right">{book.addedByUsername || "-"}</div>
                  <div className="text-slate-500">订阅起始章节</div><div className="text-slate-900 text-right">第 {book.startChapterIndex || 1} 章</div>
                  <div className="text-slate-500">订阅快照总章节</div><div className="text-slate-900 text-right">{book.totalChaptersAtSubscribe || book.totalChapters}</div>
                  <div className="text-slate-500">当前策略版本</div><div className="text-slate-900 text-right">{book.currentPolicyVersion || 1}</div>
                  <div className="text-slate-500">自动归档</div><div className="text-slate-900 text-right">{book.autoArchiveOnComplete ? "开启" : "关闭"}</div>
                </div>
              </div>
              <div className="space-y-2">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">书籍状态</h4>
                <div className="grid grid-cols-2 gap-y-2">
                  <div className="text-slate-500">订阅处理状态</div><div className="text-slate-900 text-right">{psm.label}</div>
                  <div className="text-slate-500">搜索可见状态</div><div className="text-slate-900 text-right">{book.searchVisibilityStatus === "visible" ? "可发现" : book.searchVisibilityStatus === "hidden" ? "已隐藏" : "-"}</div>
                  <div className="text-slate-500">最后检查时间</div><div className="text-slate-900 text-right">{formatDate(book.lastCheckedAt)}</div>
                  <div className="text-slate-500">下次检查时间</div><div className="text-slate-900 text-right">{formatDate(book.nextCheckTime)}</div>
                  {book.lastError && <><div className="text-rose-500 font-medium">最近错误</div><div className="text-rose-600 text-right font-medium text-xs break-all">{book.lastError}</div></>}
                </div>
              </div>
            </div>
            <div className="grid sm:grid-cols-2 gap-6 pt-4 border-t border-slate-100">
              <div className="space-y-2">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">免费 / VIP</h4>
                <div className="grid grid-cols-2 gap-y-2">
                  <div className="text-slate-500">免费章节截止</div>
                  <div className="text-slate-900 text-right">{book.freeChapterEndIndex != null ? `第 ${book.freeChapterEndIndex} 章` : "暂未识别"}</div>
                  <div className="text-slate-500">VIP 章节数</div>
                  <div className="text-slate-900 text-right">{book.freeChapterEndIndex != null ? Math.max(0, book.totalChapters - book.freeChapterEndIndex) : "暂未识别"}</div>
                </div>
              </div>
              <div className="space-y-2">
                <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">处理细分</h4>
                <div className="grid grid-cols-2 gap-y-2">
                  <div className="text-slate-500">可阅读</div><div className="text-emerald-600 font-medium text-right">{readable} 章</div>
                  <div className="text-slate-500">仅预览</div><div className="text-orange-500 font-medium text-right">{previewCount} 章</div>
                  <div className="text-slate-500">失败</div><div className="text-rose-500 font-medium text-right">{failedCount} 章</div>
                </div>
              </div>
            </div>
              </>
            ) : (
              <div className="grid gap-6 sm:grid-cols-2">
                <div className="space-y-3">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">个人设置</h4>
                  <div className="grid grid-cols-2 gap-y-2">
                    <div className="text-slate-500">订阅状态</div><div className="text-right text-slate-900">{psm.label}</div>
                    <div className="text-slate-500">起始章节</div><div className="text-right text-slate-900">第 {subscription?.startChapterIndex ?? 1} 章</div>
                    <div className="text-slate-500">自动归档</div><div className="text-right text-slate-900">{subscription?.autoArchiveOnComplete ? "开启" : "关闭"}</div>
                    <div className="text-slate-500">连续可读至</div><div className="text-right text-slate-900">第 {personal?.continuousReadableThroughIndex ?? 0} 章</div>
                  </div>
                </div>
                <div className="space-y-3">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">订阅范围</h4>
                  <div className="grid grid-cols-2 gap-y-2">
                    <div className="text-slate-500">章节范围</div><div className="text-right text-slate-900">{personal ? `${personal.rangeStartIndex} - ${personal.rangeEndIndex}` : "-"}</div>
                    <div className="text-slate-500">全文</div><div className="text-right font-medium text-emerald-600">{readable} 章</div>
                    <div className="text-slate-500">预览</div><div className="text-right font-medium text-orange-500">{previewCount} 章</div>
                    <div className="text-slate-500">失败</div><div className="text-right font-medium text-rose-500">{failedCount} 章</div>
                    <div className="text-slate-500">待处理</div><div className="text-right text-slate-900">{personal?.pendingCount ?? 0} 章</div>
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {isAdmin && (
          <Card>
            <CardHeader className="py-4 border-b border-slate-100 flex flex-row items-center justify-between">
              <CardTitle className="text-sm font-medium flex items-center"><Link className="h-4 w-4 mr-2 text-slate-400" /> 源映射摘要</CardTitle>
            </CardHeader>
            <CardContent className="p-4 text-sm space-y-4">
              <div className="flex justify-between items-center bg-emerald-50 p-3 rounded-lg border border-emerald-100">
                <div>
                  <div className="font-semibold text-emerald-700">源映射{book.sourceMapRefresh?.completed ? "健康" : book.sourceMapRefresh?.missingCriticalSource ? "缺关键源" : "未完成"}</div>
                  {book.sourceMapRefresh?.lastVerifiedAt && <div className="text-xs text-emerald-600 mt-0.5">上次刷新: {formatDate(book.sourceMapRefresh.lastVerifiedAt)}</div>}
                </div>
                <Button size="sm" variant="outline" className="bg-white" onClick={() => actionMutation.mutate("refresh-sources")} disabled={maintenanceBusy}><RefreshCw className="h-3 w-3 mr-2" /> 刷新</Button>
              </div>
              {book.primarySourceName && (
                <div className="space-y-2">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">主源信息</h4>
                  <div className="grid grid-cols-2 gap-y-2 bg-slate-50 p-3 rounded-lg border border-slate-100">
                    <div className="text-slate-500">名称</div><div className="text-slate-900 text-right">{book.primarySourceName} {(book.primarySourceId?.includes("official") || false) ? "(官方)" : ""}</div>
                    <div className="text-slate-500">最新章节</div><div className="text-slate-900 text-right">{book.lastChapterTitle || "-"}</div>
                    <div className="text-slate-500">总章节数</div><div className="text-slate-900 text-right">{book.totalChapters}</div>
                  </div>
                </div>
              )}
              {sourceMap.length > 0 && (
                <div className="space-y-2 flex flex-col">
                  <h4 className="text-xs font-bold text-slate-400 uppercase tracking-wider">候选源列表</h4>
                  <div className="border border-slate-200 rounded-lg overflow-y-auto max-h-[180px]">
                    <Table>
                      <TableHeader className="bg-slate-50 sticky top-0 z-10">
                        <TableRow>
                          <TableHead className="py-2 h-auto text-xs bg-slate-50">来源</TableHead>
                          <TableHead className="py-2 h-auto text-xs bg-slate-50">匹配分</TableHead>
                          <TableHead className="py-2 h-auto text-xs bg-slate-50">最新章节</TableHead>
                          <TableHead className="py-2 h-auto text-xs bg-slate-50">章节数</TableHead>
                          <TableHead className="py-2 h-auto text-xs bg-slate-50">状态</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {sourceMap.map((s) => (
                          <TableRow key={s.sourceId}>
                            <TableCell className="py-2 text-xs">{s.sourceName || s.sourceId}</TableCell>
                            <TableCell className="py-2 text-xs">{s.score}</TableCell>
                            <TableCell className="py-2 text-xs">{s.lastChapter || "-"}</TableCell>
                            <TableCell className="py-2 text-xs">{s.chapterCount > 0 ? `${s.chapterCount}章` : "未知"}</TableCell>
                            <TableCell className="py-2 text-xs">{s.bookStatus || "-"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        )}
      </div>

      {/* Chapter List */}
      <Card>
        <CardHeader className="py-4 border-b border-slate-100">
          <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
            <CardTitle>章节列表</CardTitle>
            <div className="flex items-center gap-2 w-full sm:w-auto">
              <div className="relative flex-1 sm:w-48">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                <input type="text" name="chapter-search" autoComplete="off" aria-label="搜索章节" placeholder="搜索章节…" value={chapterKeyword} onChange={(e) => { setChapterKeyword(e.target.value); setChapterPage(1) }}
                  className="w-full pl-8 pr-3 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-blue-400 focus:ring-1 focus:ring-blue-400" />
              </div>
              <Select value={chapterStatusFilter} onValueChange={(value) => { setChapterStatusFilter(value); setChapterPage(1) }}>
                <SelectTrigger className="h-9 w-24 text-sm"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部</SelectItem>
                  <SelectItem value="readable">可阅读</SelectItem>
                  <SelectItem value="fetched">预览</SelectItem>
                  <SelectItem value="suspect">存疑</SelectItem>
                  <SelectItem value="failed">失败</SelectItem>
                  <SelectItem value="pending">待处理</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="h-[500px] overflow-y-auto">
            <Table>
              <TableHeader className="sticky top-0 bg-white z-10 shadow-sm">
                <TableRow>
                  <TableHead className="w-16">序号</TableHead>
                  <TableHead>标题</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>类型</TableHead>
                  {isAdmin && (
                    <>
                      <TableHead>来源</TableHead>
                      <TableHead>字数</TableHead>
                      <TableHead>错误</TableHead>
                      <TableHead className="text-right">操作</TableHead>
                    </>
                  )}
                </TableRow>
              </TableHeader>
              <TableBody>
                {chaptersFetching && !chaptersData ? (
                  <TableRow><TableCell colSpan={isAdmin ? 8 : 4} className="py-8 text-center text-slate-400"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />章节加载中…</TableCell></TableRow>
                ) : chapters.length === 0 ? (
                  <TableRow><TableCell colSpan={isAdmin ? 8 : 4} className="text-center text-slate-400 py-8">暂无章节数据</TableCell></TableRow>
                ) : (
                  chapters.map((c) => {
                    const readableChapter = canReadChapter(c)
                    return (
                      <TableRow
                        key={c.chapterId}
                        className={`${readableChapter ? "cursor-pointer hover:bg-slate-50 transition-colors" : "cursor-not-allowed opacity-60"}`}
                        onClick={() => handleChapterClick(c)}
                        title={readableChapter ? "" : "暂不可读"}
                      >
                        <TableCell className="font-medium text-slate-500">{c.chapterIndex}</TableCell>
                        <TableCell>{c.title}</TableCell>
                        <TableCell><span className={`text-xs font-medium ${chapterStatusColor(c.status)}`}>{chapterStatusLabel(c.status)}</span></TableCell>
                        <TableCell>
                          {c.isVip ? <span className="flex items-center text-amber-500 text-xs font-medium"><Crown className="h-3 w-3 mr-1" /> VIP</span>
                           : c.previewOnly ? <span className="text-orange-500 text-xs">预览</span>
                           : <span className="text-slate-400 text-xs">免费</span>}
                        </TableCell>
                        {isAdmin && (
                          <>
                            <TableCell className="text-slate-500 text-xs">{c.sourceId || "-"}</TableCell>
                            <TableCell className="text-slate-500 text-xs">{c.sourceWordCount || c.contentLength || "-"}</TableCell>
                            <TableCell className="text-rose-500 text-xs">{c.error || "-"}</TableCell>
                            <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                              <Button variant="ghost" size="sm" className="h-8" onClick={() => chapterProcessMutation.mutate(c.chapterId)} disabled={maintenanceBusy}>处理本章</Button>
                            </TableCell>
                          </>
                        )}
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </div>
          {chapterPageCount > 1 && (
            <div className="flex items-center justify-between border-t border-slate-100 px-4 py-3 text-sm text-slate-500">
              <span>第 {chapterPage} / {chapterPageCount} 页，共 {chapterTotal} 章</span>
              <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={() => setChapterPage((page) => Math.max(1, page - 1))} disabled={chapterPage <= 1 || !!chaptersError} aria-label="上一页">
                  <ChevronLeft className="h-4 w-4 mr-1" /> 上一页
                </Button>
                <Button variant="outline" size="sm" onClick={() => setChapterPage((page) => Math.min(chapterPageCount, page + 1))} disabled={chapterPage >= chapterPageCount || !!chaptersError} aria-label="下一页">
                  下一页 <ChevronRight className="h-4 w-4 ml-1" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {isAdmin && (
        <Card>
          <CardHeader className="py-4 border-b border-slate-100"><CardTitle className="text-sm font-medium flex items-center"><Terminal className="h-4 w-4 mr-2 text-slate-400" /> 实时日志</CardTitle></CardHeader>
          <CardContent className="p-0 h-48"><LogStream key={bookId} url={api.streamLibraryBookLogsUrl(bookId!)} /></CardContent>
        </Card>
      )}

      <Dialog open={processingSettingsOpen} onOpenChange={setProcessingSettingsOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>共享处理设置</DialogTitle>
            <DialogDescription>这些设置影响本书的共享后台任务，对所有订阅者统一生效。</DialogDescription>
          </DialogHeader>
          <div className="space-y-5 py-2">
            <div className="space-y-2">
              <Label htmlFor="detail-update-interval">更新检查间隔（分钟）</Label>
              <Input
                id="detail-update-interval"
                type="number"
                min={10}
                max={1440}
                step={1}
                value={updateIntervalMinutes}
                onChange={(event) => setUpdateIntervalMinutes(event.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="detail-backlog-limit">单轮积压章节上限</Label>
              <Input
                id="detail-backlog-limit"
                type="number"
                min={5}
                max={100}
                step={1}
                value={backlogChapterLimit}
                onChange={(event) => setBacklogChapterLimit(event.target.value)}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setProcessingSettingsOpen(false)}>取消</Button>
              <Button
                onClick={() => processingSettingsMutation.mutate({ updateIntervalMinutes: processingInterval, backlogChapterLimit: processingBacklog })}
                disabled={processingSettingsMutation.isPending || !processingSettingsValid}
              >
                {processingSettingsMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                保存
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>订阅设置</DialogTitle>
            <DialogDescription>这些设置只影响你的订阅，不会改变共享抓取任务。</DialogDescription>
          </DialogHeader>
          <div className="space-y-5 py-2">
            <div className="space-y-2">
              <Label htmlFor="detail-start-chapter">起始章节</Label>
              <Input
                id="detail-start-chapter"
                type="number"
                min={1}
                step={1}
                value={startChapterIndex}
                onChange={(event) => setStartChapterIndex(event.target.value)}
              />
            </div>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor="detail-auto-archive" className="leading-5">完结且处理完成后自动归档</Label>
              <Switch
                id="detail-auto-archive"
                checked={autoArchiveOnComplete}
                onCheckedChange={setAutoArchiveOnComplete}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => setSettingsOpen(false)}>取消</Button>
              <Button
                onClick={() => subscriptionMutation.mutate({ startChapterIndex: Math.max(1, Number(startChapterIndex) || 1), autoArchiveOnComplete })}
                disabled={subscriptionMutation.isPending}
              >
                {subscriptionMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                保存
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!readingChapter} onOpenChange={(open) => { if (!open) setReadingChapter(null) }}>
        <DialogContent className="max-w-3xl h-[80vh] flex flex-col p-0 overflow-hidden">
          <DialogHeader className="p-4 md:p-6 pb-0 shrink-0">
            <div className="flex items-center gap-3">
              <DialogTitle className="text-xl md:text-2xl font-bold">{readingChapter?.title}</DialogTitle>
              {previewMode && <Badge variant="secondary" className="bg-orange-100 text-orange-700 border-transparent">预览模式</Badge>}
            </div>
            <DialogDescription className="text-slate-500">正文抽查 · {book.displayName} · {book.displayAuthor}</DialogDescription>
          </DialogHeader>
          <div className="flex-1 overflow-y-auto p-4 md:p-6 text-slate-800 leading-relaxed space-y-6 text-lg bg-[#FDFBF7] mt-4 rounded-b-xl font-serif">
            {chapterBodyQuery.isLoading ? (
              <p className="text-slate-400 text-center pt-20">章节内容加载中…</p>
            ) : chapterBodyQuery.error ? (
              <Alert variant="destructive">
                <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
                  <span>正文加载失败：{apiErrorMessage(chapterBodyQuery.error, "请稍后重试。")}</span>
                  <Button type="button" size="sm" variant="outline" onClick={() => { void chapterBodyQuery.refetch() }}>重试</Button>
                </AlertDescription>
              </Alert>
            ) : chapterBodyQuery.data?.content ? (
              String(chapterBodyQuery.data.content)
                .split(/\n+/)
                .filter(Boolean)
                .map((line, index) => <p key={index}>{line}</p>)
            ) : (
              <p className="text-slate-400 text-center pt-20">暂无可读正文。</p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
