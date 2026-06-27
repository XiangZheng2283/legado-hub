import { useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowUpRight,
  BookOpen,
  ChevronLeft,
  ChevronLeftIcon,
  ChevronRightIcon,
  Clock,
  FileText,
  Loader2,
  RefreshCw,
  ScrollText,
  Search,
  ShieldAlert,
  Sparkles,
  Wrench,
} from "lucide-react"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface SourceMapSummaryItem {
  bookId?: string
  sourceId: string
  sourceName: string
  score: number
  chapterCount: number
  lastChapter: string
  bookStatus: string
  name: string
  author: string
}

interface BookStateSummary {
  status?: string
  searchVisibilityStatus?: string
  chapterCount?: number
  processedChapterCount?: number
  readableChapterCount?: number
  previewChapterCount?: number
  proofreadCompleteCount?: number
  suspectChapterCount?: number
  failedChapterCount?: number
  latestChapterIndex?: number
  latestChapterTitle?: string
  lastUpdateCheckAt?: string
}

interface LibraryBookDetail {
  found?: boolean
  aggregateBookId: string
  displayName: string
  displayAuthor: string
  coverUrl?: string
  intro?: string
  wordCount?: string
  totalChapters: number
  processedChapters: number
  visibleProcessedChapters: number
  failedChapters?: number
  status: string
  bookStatus: string
  primarySourceId?: string
  primarySourceName?: string
  addedByUsername?: string
  lastChapterTitle?: string
  lastCheckedAt?: string
  startChapterIndex?: number
  totalChaptersAtSubscribe?: number
  currentPolicyVersion?: number
  autoArchiveOnComplete?: boolean
  searchVisibilityStatus?: string
  lastError?: string
  nextCheckTime?: string
  bookState?: BookStateSummary
  sourceMapSummary?: SourceMapSummaryItem[]
  sourceMapRefresh?: {
    completed?: boolean
    status?: string
    lastVerifiedAt?: string
    missingCriticalSource?: boolean
  }
}

interface LibraryChapterListItem {
  chapterId: string
  chapterIndex: number
  title: string
  status: string
  hasContent?: boolean
  processedAt?: string
}

interface ProcessingLogItem {
  chapterId: string
  chapterIndex: number
  title: string
  status: string
  previewOnly: boolean
  wordCount: number
  source: string
  aiModel: string
  aiTokens: number
  processedAt: string | null
  error: string
  alignment: {
    passed?: boolean
    reason?: string
    titleSimilarity?: number
    previewSimilarity?: number
  }
}

function statusBadge(status?: string) {
  const map: Record<
    string,
    { label: string; variant: "success" | "warning" | "info" | "destructive" | "outline" | "secondary" }
  > = {
    active: { label: "处理中", variant: "info" },
    paused: { label: "已暂停", variant: "warning" },
    archived: { label: "已归档", variant: "secondary" },
    error: { label: "异常", variant: "destructive" },
    pending: { label: "待处理", variant: "outline" },
    processed: { label: "已处理", variant: "success" },
    fallback: { label: "回退", variant: "warning" },
    completed: { label: "已完成", variant: "success" },
  }
  const entry = map[status || ""] || { label: status || "未知", variant: "outline" as const }
  return <Badge variant={entry.variant}>{entry.label}</Badge>
}

function visibilityBadge(status?: string) {
  if (status === "visible") return <Badge variant="success">可发现</Badge>
  if (status === "hidden") return <Badge variant="outline">隐藏</Badge>
  return <Badge variant="outline">{status || "未知"}</Badge>
}

function bookStatusBadge(status?: string) {
  if (status === "completed") return <Badge variant="secondary">已完结</Badge>
  return <Badge variant="outline">连载中</Badge>
}

function operationLabel(type?: string) {
  const labels: Record<string, string> = {
    rebuild: "重建",
    refresh_source_map: "刷新源映射",
    repair: "修复",
    update_check: "检查更新",
    settings: "更新设置",
  }
  return labels[type || ""] || type || "操作"
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-"
  try {
    return new Date(value).toLocaleString("zh-CN")
  } catch {
    return String(value)
  }
}

export function LibraryBookDetailPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  const [chapterStatusFilter, setChapterStatusFilter] = useState("all")
  const [chapterKeyword, setChapterKeyword] = useState("")
  const [chapterPage, setChapterPage] = useState(1)
  const [logsOpen, setLogsOpen] = useState(false)
  const pageSize = 30

  const summaryQuery = useQuery({
    queryKey: ["library", "book", bookId, "summary"],
    queryFn: () => api.libraryBookSummary(bookId!),
    enabled: !!bookId,
    refetchInterval: 5000,
  })

  const chapterParams = useMemo(() => {
    const params: Record<string, string> = {
      page: String(chapterPage),
      pageSize: String(pageSize),
    }
    if (chapterStatusFilter !== "all") params.status = chapterStatusFilter
    if (chapterKeyword.trim()) params.keyword = chapterKeyword.trim()
    return params
  }, [chapterKeyword, chapterPage, chapterStatusFilter])

  const chaptersQuery = useQuery({
    queryKey: ["library", "book", bookId, "chapters", chapterParams],
    queryFn: () => api.libraryBookChapters(bookId!, chapterParams),
    enabled: !!bookId,
    refetchInterval: 5000,
  })

  const operationLogsQuery = useQuery({
    queryKey: ["library", "book", bookId, "logs"],
    queryFn: () => api.libraryBookLogs(bookId!, 50, 0),
    enabled: !!bookId && logsOpen,
  })

  const processingLogsQuery = useQuery({
    queryKey: ["library", "book", bookId, "processing-logs"],
    queryFn: () => api.libraryBookProcessingLogs(bookId!, 50, 0),
    enabled: !!bookId && isAdmin,
    refetchInterval: 5000,
  })

  const actionMutation = useMutation({
    mutationFn: async (action: "check-update" | "refresh-sources" | "repair" | "rebuild") => {
      if (!bookId) throw new Error("bookId is required")
      if (action === "check-update") return api.checkLibraryBookUpdate(bookId)
      if (action === "refresh-sources") return api.refreshLibraryBookSources(bookId, { force: true })
      if (action === "repair") return api.repairLibraryBook(bookId, { reason: "manual" })
      return api.rebuildLibraryBook(bookId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library", "book", bookId] })
      queryClient.invalidateQueries({ queryKey: ["library"] })
    },
  })

  const book: LibraryBookDetail | undefined = summaryQuery.data
  const chapters: LibraryChapterListItem[] = chaptersQuery.data?.items || chaptersQuery.data?.chapters || []
  const chapterTotal = Number(chaptersQuery.data?.total || chapters.length || 0)
  const chapterTotalPages = Math.max(1, Math.ceil(chapterTotal / pageSize))
  const processingLogs: ProcessingLogItem[] = processingLogsQuery.data?.items || []
  const processingStats = processingLogsQuery.data?.stats

  if (summaryQuery.isLoading) {
    return (
      <div className="flex min-h-[300px] items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!book || book.found === false) {
    return <div className="text-muted-foreground">书籍不存在或已删除。</div>
  }

  const progress = book.totalChapters > 0 ? (book.processedChapters / book.totalChapters) * 100 : 0
  const bookState = book.bookState || {}
  const sourceMapSummary = book.sourceMapSummary || []

  return (
    <div className="space-y-4">
      <Button variant="outline" size="sm" onClick={() => navigate("/console/library")}>
        <ChevronLeft className="mr-1 h-4 w-4" />
        返回书库
      </Button>

      <div className="flex gap-4">
        {book.coverUrl ? (
          <img
            src={book.coverUrl}
            alt={book.displayName}
            className="h-44 w-32 rounded bg-muted object-cover"
          />
        ) : (
          <div className="flex h-44 w-32 items-center justify-center rounded bg-muted">
            <BookOpen className="h-12 w-12 text-muted-foreground opacity-20" />
          </div>
        )}
        <div className="flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold">{book.displayName}</h1>
            {bookStatusBadge(book.bookStatus)}
            {statusBadge(book.status)}
            {visibilityBadge(book.searchVisibilityStatus || bookState.searchVisibilityStatus)}
          </div>
          <p className="text-sm text-muted-foreground">{book.displayAuthor || "未知作者"}</p>
          {book.intro && <p className="line-clamp-3 text-sm text-muted-foreground">{book.intro}</p>}
          <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
            {book.wordCount && (
              <span className="flex items-center gap-1">
                <FileText className="h-4 w-4" />
                {book.wordCount}
              </span>
            )}
            {book.addedByUsername && (
              <span className="flex items-center gap-1">
                <ArrowUpRight className="h-4 w-4" />
                {book.addedByUsername}
              </span>
            )}
            <span className="flex items-center gap-1">
              <Clock className="h-4 w-4" />
              {formatDate(book.lastCheckedAt)}
            </span>
          </div>
          <div className="max-w-xl space-y-1">
            <Progress value={progress} className="h-2" />
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <span>
                已处理 {book.processedChapters} / {book.totalChapters}
              </span>
              <span>可读 {book.visibleProcessedChapters}</span>
              <span>失败 {book.failedChapters || bookState.failedChapterCount || 0}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => setLogsOpen(true)}>
              <ScrollText className="h-4 w-4" />
              日志
            </Button>
            {isAdmin && (
              <>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => actionMutation.mutate("check-update")}
                  disabled={actionMutation.isPending}
                >
                  {actionMutation.isPending ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RefreshCw className="h-4 w-4" />
                  )}
                  检查更新
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => actionMutation.mutate("refresh-sources")}
                  disabled={actionMutation.isPending}
                >
                  <Sparkles className="h-4 w-4" />
                  刷新源映射
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => actionMutation.mutate("repair")}
                  disabled={actionMutation.isPending}
                >
                  <Wrench className="h-4 w-4" />
                  修复
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => actionMutation.mutate("rebuild")}
                  disabled={actionMutation.isPending}
                >
                  <RefreshCw className="h-4 w-4" />
                  重建
                </Button>
              </>
            )}
          </div>
        </div>
      </div>

      {book.lastError && (
        <Alert>
          <ShieldAlert className="h-4 w-4" />
          <AlertDescription>{book.lastError}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">元数据</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 text-sm md:grid-cols-2">
              <div>
                <div className="text-xs text-muted-foreground">主源</div>
                <div className="font-medium">{book.primarySourceName || book.primarySourceId || "-"}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">起始章节</div>
                <div className="font-medium">{book.startChapterIndex || 1}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">订阅快照章节</div>
                <div className="font-medium">{book.totalChaptersAtSubscribe || 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">策略版本</div>
                <div className="font-medium">{book.currentPolicyVersion || 1}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">最后章节</div>
                <div className="font-medium">{book.lastChapterTitle || "-"}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">下次检查</div>
                <div className="font-medium">{formatDate(book.nextCheckTime)}</div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">当前状态</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-3 text-sm md:grid-cols-2">
              <div>
                <div className="text-xs text-muted-foreground">任务状态</div>
                <div className="font-medium">{statusBadge(bookState.status || book.status)}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">发现状态</div>
                <div className="font-medium">
                  {visibilityBadge(bookState.searchVisibilityStatus || book.searchVisibilityStatus)}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">可读章节</div>
                <div className="font-medium">{bookState.readableChapterCount ?? book.visibleProcessedChapters}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">预览章节</div>
                <div className="font-medium">{bookState.previewChapterCount ?? 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">疑似章节</div>
                <div className="font-medium">{bookState.suspectChapterCount ?? 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">校对完成</div>
                <div className="font-medium">{bookState.proofreadCompleteCount ?? 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">最近更新检查</div>
                <div className="font-medium">{formatDate(bookState.lastUpdateCheckAt)}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">源映射刷新</div>
                <div className="font-medium">
                  {book.sourceMapRefresh?.completed ? "已完成" : "未完成"}
                  {book.sourceMapRefresh?.missingCriticalSource ? " / 缺关键源" : ""}
                </div>
                <div className="text-xs text-muted-foreground">
                  {formatDate(book.sourceMapRefresh?.lastVerifiedAt)}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">源映射摘要</CardTitle>
        </CardHeader>
        <CardContent>
          {sourceMapSummary.length === 0 ? (
            <div className="text-sm text-muted-foreground">暂无源映射摘要</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>来源</TableHead>
                  <TableHead>匹配分</TableHead>
                  <TableHead>章节数</TableHead>
                  <TableHead>最后章节</TableHead>
                  <TableHead>书籍状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sourceMapSummary.map((item) => (
                  <TableRow key={`${item.sourceId}-${item.bookId || item.sourceName}`}>
                    <TableCell>
                      <div className="font-medium">{item.sourceName || item.sourceId}</div>
                      <div className="text-xs text-muted-foreground">{item.sourceId}</div>
                    </TableCell>
                    <TableCell>{item.score}</TableCell>
                    <TableCell>{item.chapterCount}</TableCell>
                    <TableCell className="max-w-[280px] truncate">{item.lastChapter || "-"}</TableCell>
                    <TableCell>{item.bookStatus || "-"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Tabs defaultValue="chapters" className="w-full">
        <TabsList>
          <TabsTrigger value="chapters">章节</TabsTrigger>
          {isAdmin && <TabsTrigger value="processing">处理日志</TabsTrigger>}
        </TabsList>

        <TabsContent value="chapters" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="text-sm">章节列表</CardTitle>
                <div className="flex items-center gap-2">
                  <div className="relative">
                    <Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      value={chapterKeyword}
                      onChange={(event) => {
                        setChapterKeyword(event.target.value)
                        setChapterPage(1)
                      }}
                      placeholder="搜索章节..."
                      className="h-8 w-48 pl-8"
                    />
                  </div>
                  <Select
                    value={chapterStatusFilter}
                    onValueChange={(value) => {
                      setChapterStatusFilter(value)
                      setChapterPage(1)
                    }}
                  >
                    <SelectTrigger className="h-8 w-28">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全部</SelectItem>
                      <SelectItem value="processed">已处理</SelectItem>
                      <SelectItem value="fallback">回退</SelectItem>
                      <SelectItem value="error">失败</SelectItem>
                      <SelectItem value="pending">待处理</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {chaptersQuery.isLoading ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  加载中...
                </div>
              ) : chapters.length === 0 ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground">
                  暂无章节数据
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-20">序号</TableHead>
                      <TableHead>标题</TableHead>
                      <TableHead className="w-28">状态</TableHead>
                      <TableHead className="w-28">内容</TableHead>
                      <TableHead className="w-40">详情</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {chapters.map((chapter) => (
                      <TableRow
                        key={chapter.chapterId}
                        className="cursor-pointer"
                        onClick={() =>
                          navigate(`/console/library/${bookId}/chapters/${chapter.chapterId}`)
                        }
                      >
                        <TableCell>{chapter.chapterIndex}</TableCell>
                        <TableCell className="max-w-[420px] truncate">{chapter.title}</TableCell>
                        <TableCell>{statusBadge(chapter.status)}</TableCell>
                        <TableCell>{chapter.hasContent ? "已生成" : "占位"}</TableCell>
                        <TableCell>
                          <Button variant="ghost" size="sm">
                            查看进度
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>

          {chapterTotalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-muted-foreground">
              <span>共 {chapterTotal} 章</span>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={chapterPage <= 1}
                  onClick={() => setChapterPage((page) => page - 1)}
                >
                  <ChevronLeftIcon className="h-4 w-4" />
                </Button>
                <span>
                  {chapterPage} / {chapterTotalPages}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={chapterPage >= chapterTotalPages}
                  onClick={() => setChapterPage((page) => page + 1)}
                >
                  <ChevronRightIcon className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </TabsContent>

        {isAdmin && (
          <TabsContent value="processing">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <ScrollText className="h-4 w-4" />
                  章节处理日志
                  {processingLogsQuery.isFetching && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4">
                {processingStats && (
                  <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                    {[
                      ["总章节", processingStats.total],
                      ["已完成", processingStats.completed],
                      ["已处理", processingStats.processed],
                      ["待处理", processingStats.pending],
                      ["回退", processingStats.fallback],
                      ["失败", processingStats.failed],
                    ].map(([label, value]) => (
                      <div key={label} className="rounded-lg border p-3">
                        <div className="text-xs text-muted-foreground">{label}</div>
                        <div className="text-lg font-semibold">{value}</div>
                      </div>
                    ))}
                  </div>
                )}

                {processingLogsQuery.isLoading ? (
                  <div className="text-muted-foreground">加载中...</div>
                ) : processingLogs.length === 0 ? (
                  <div className="text-muted-foreground">暂无处理日志</div>
                ) : (
                  <ScrollArea className="h-[420px]">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="w-16">序号</TableHead>
                          <TableHead>标题</TableHead>
                          <TableHead className="w-24">状态</TableHead>
                          <TableHead className="w-24">来源</TableHead>
                          <TableHead className="w-28">AI 模型</TableHead>
                          <TableHead className="w-20 text-right">Token</TableHead>
                          <TableHead className="w-40">处理时间</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {processingLogs.map((log) => (
                          <TableRow key={log.chapterId}>
                            <TableCell>{log.chapterIndex}</TableCell>
                            <TableCell>
                              <div className="flex items-center gap-2">
                                <span className="truncate">{log.title}</span>
                                {log.previewOnly && (
                                  <Badge variant="outline" className="text-[10px]">
                                    预览
                                  </Badge>
                                )}
                              </div>
                              {log.error && (
                                <p className="mt-0.5 max-w-[300px] truncate text-xs text-destructive">
                                  {log.error}
                                </p>
                              )}
                            </TableCell>
                            <TableCell>{statusBadge(log.status)}</TableCell>
                            <TableCell className="text-xs">{log.source}</TableCell>
                            <TableCell className="text-xs">{log.aiModel || "-"}</TableCell>
                            <TableCell className="text-right text-xs">
                              {log.aiTokens ? log.aiTokens.toLocaleString() : "-"}
                            </TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {formatDate(log.processedAt)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </ScrollArea>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>

      <Dialog open={logsOpen} onOpenChange={setLogsOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>操作日志</DialogTitle>
          </DialogHeader>
          {operationLogsQuery.isLoading ? (
            <div className="flex items-center py-8 text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载中...
            </div>
          ) : (operationLogsQuery.data?.items || []).length === 0 ? (
            <div className="text-sm text-muted-foreground">暂无操作日志</div>
          ) : (
            <ScrollArea className="h-[420px] pr-4">
              <div className="space-y-3">
                {(operationLogsQuery.data?.items || []).map((item: any) => (
                  <div key={item.id} className="rounded-lg border p-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{operationLabel(item.operationType)}</Badge>
                        <span className="text-sm text-muted-foreground">{item.actorRole || "-"}</span>
                      </div>
                      <span className="text-xs text-muted-foreground">{formatDate(item.createdAt)}</span>
                    </div>
                  </div>
                ))}
              </div>
            </ScrollArea>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
