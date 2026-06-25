import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  BookOpen,
  ChevronLeft,
  Clock,
  FileText,
  Loader2,
  ScrollText,
  User,
} from "lucide-react"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface Chapter {
  chapterIndex: number
  title: string
  status: "placeholder" | "pending" | "processed" | "fallback" | "error"
  processedAt?: string
}

interface BookDetail {
  aggregateBookId: string
  displayName: string
  displayAuthor: string
  coverUrl?: string
  intro?: string
  wordCount?: string
  totalChapters: number
  processedChapters: number
  visibleProcessedChapters: number
  status: string
  bookStatus: string
  primarySourceId?: string
  addedByUsername?: string
  lastChapterTitle?: string
  lastCheckedAt?: string
  autoArchiveOnComplete?: boolean
  startChapterIndex?: number
}

interface ProcessingStats {
  total: number
  processed: number
  completed: number
  pending: number
  fallback: number
  failed: number
}

interface ProcessingLogItem {
  chapterId: string
  chapterIndex: number
  title: string
  status: "placeholder" | "pending" | "processed" | "fallback" | "error"
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

function chapterStatusBadge(status: string) {
  if (status === "processed") return <Badge variant="success">已处理</Badge>
  if (status === "fallback") return <Badge variant="warning">回退</Badge>
  if (status === "pending") return <Badge variant="info">处理中</Badge>
  if (status === "error") return <Badge variant="destructive">失败</Badge>
  return <Badge variant="outline">占位</Badge>
}

function formatDate(value: string | null | undefined) {
  if (!value) return "-"
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

export function LibraryBookDetailPage() {
  const { bookId } = useParams<{ bookId: string }>()

  const bookQuery = useQuery({
    queryKey: ["library", "book", bookId],
    queryFn: () => api.libraryBook(bookId!),
    enabled: !!bookId,
  })

  const chaptersQuery = useQuery({
    queryKey: ["library", "book", bookId, "chapters"],
    queryFn: () => api.libraryBookChapters(bookId!),
    enabled: !!bookId,
  })

  const logsQuery = useQuery({
    queryKey: ["library", "book", bookId, "processing-logs"],
    queryFn: () => api.libraryBookProcessingLogs(bookId!),
    enabled: !!bookId,
    refetchInterval: 5000,
  })

  const book: BookDetail | undefined = bookQuery.data
  const chapters: Chapter[] = chaptersQuery.data?.chapters || []
  const stats: ProcessingStats | undefined = logsQuery.data?.stats
  const logs: ProcessingLogItem[] = logsQuery.data?.items || []

  if (bookQuery.isLoading) {
    return (
      <div className="min-h-[300px] flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    )
  }

  if (!book) {
    return <div className="text-muted-foreground">书籍不存在或已删除。</div>
  }

  return (
    <div className="space-y-4">
      <Button variant="outline" size="sm" onClick={() => window.history.back()}>
        <ChevronLeft className="w-4 h-4 mr-1" />
        返回书库
      </Button>

      <div className="flex gap-4">
        {book.coverUrl ? (
          <img
            src={book.coverUrl}
            alt={book.displayName}
            className="w-32 h-44 object-cover rounded bg-muted"
          />
        ) : (
          <div className="w-32 h-44 rounded bg-muted flex items-center justify-center">
            <BookOpen className="w-12 h-12 text-muted-foreground opacity-20" />
          </div>
        )}
        <div className="flex-1 space-y-2">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold">{book.displayName}</h1>
            {book.bookStatus === "completed" ? (
              <Badge variant="secondary">已完结</Badge>
            ) : (
              <Badge variant="outline">连载中</Badge>
            )}
            {book.status === "archived" && <Badge variant="secondary">已归档</Badge>}
          </div>
          <p className="text-sm text-muted-foreground">{book.displayAuthor || "未知作者"}</p>
          {book.intro && <p className="text-sm text-muted-foreground line-clamp-3">{book.intro}</p>}
          <div className="flex flex-wrap gap-4 text-sm text-muted-foreground">
            {book.wordCount && (
              <span className="flex items-center gap-1">
                <FileText className="w-4 h-4" />
                {book.wordCount}
              </span>
            )}
            {book.addedByUsername && (
              <span className="flex items-center gap-1">
                <User className="w-4 h-4" />
                {book.addedByUsername}
              </span>
            )}
            {book.lastCheckedAt && (
              <span className="flex items-center gap-1">
                <Clock className="w-4 h-4" />
                {formatDate(book.lastCheckedAt)}
              </span>
            )}
          </div>
          <div className="w-full max-w-md">
            <Progress
              value={book.totalChapters ? (book.processedChapters / book.totalChapters) * 100 : 0}
              className="h-2"
            />
            <p className="text-xs text-muted-foreground mt-1">
              已处理 {book.processedChapters} / {book.totalChapters} 章
              （搜索可见 {book.visibleProcessedChapters} 章）
            </p>
          </div>
        </div>
      </div>

      <Tabs defaultValue="chapters" className="w-full">
        <TabsList>
          <TabsTrigger value="chapters">目录</TabsTrigger>
          <TabsTrigger value="logs" className="flex items-center gap-1">
            <ScrollText className="w-3.5 h-3.5" />
            处理日志
          </TabsTrigger>
        </TabsList>

        <TabsContent value="chapters">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">目录</CardTitle>
            </CardHeader>
            <CardContent>
              {chaptersQuery.isLoading ? (
                <div className="text-muted-foreground">加载中...</div>
              ) : (
                <ScrollArea className="h-[500px]">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="w-20">序号</TableHead>
                        <TableHead>标题</TableHead>
                        <TableHead className="w-28">状态</TableHead>
                        <TableHead className="w-40">处理时间</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {chapters.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={4} className="text-center text-muted-foreground">
                            暂无章节数据
                          </TableCell>
                        </TableRow>
                      ) : (
                        chapters.map((ch) => (
                          <TableRow key={ch.chapterIndex}>
                            <TableCell>{ch.chapterIndex}</TableCell>
                            <TableCell>{ch.title}</TableCell>
                            <TableCell>{chapterStatusBadge(ch.status)}</TableCell>
                            <TableCell className="text-xs text-muted-foreground">
                              {formatDate(ch.processedAt)}
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </ScrollArea>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="logs">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <ScrollText className="w-4 h-4" />
                处理日志
                {logsQuery.isFetching && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {stats && (
                <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
                  <div className="rounded-lg border p-3">
                    <div className="text-xs text-muted-foreground">总章节</div>
                    <div className="text-lg font-semibold">{stats.total}</div>
                  </div>
                  <div className="rounded-lg border p-3">
                    <div className="text-xs text-muted-foreground">已完成</div>
                    <div className="text-lg font-semibold">{stats.completed}</div>
                  </div>
                  <div className="rounded-lg border p-3">
                    <div className="text-xs text-muted-foreground">已处理</div>
                    <div className="text-lg font-semibold">{stats.processed}</div>
                  </div>
                  <div className="rounded-lg border p-3">
                    <div className="text-xs text-muted-foreground">待处理</div>
                    <div className="text-lg font-semibold">{stats.pending}</div>
                  </div>
                  <div className="rounded-lg border p-3">
                    <div className="text-xs text-muted-foreground">回退</div>
                    <div className="text-lg font-semibold">{stats.fallback}</div>
                  </div>
                  <div className="rounded-lg border p-3">
                    <div className="text-xs text-muted-foreground">失败</div>
                    <div className="text-lg font-semibold">{stats.failed}</div>
                  </div>
                </div>
              )}

              {logsQuery.isLoading ? (
                <div className="text-muted-foreground">加载中...</div>
              ) : logs.length === 0 ? (
                <div className="text-muted-foreground">暂无处理日志</div>
              ) : (
                <ScrollArea className="h-[500px]">
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
                      {logs.map((log) => (
                        <TableRow key={log.chapterId}>
                          <TableCell>{log.chapterIndex}</TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              {log.title}
                              {log.previewOnly && (
                                <Badge variant="outline" className="text-[10px]">
                                  预览
                                </Badge>
                              )}
                            </div>
                            {log.error && (
                              <p className="text-xs text-destructive mt-0.5 truncate max-w-[300px]">
                                {log.error}
                              </p>
                            )}
                          </TableCell>
                          <TableCell>{chapterStatusBadge(log.status)}</TableCell>
                          <TableCell className="text-xs">{log.source}</TableCell>
                          <TableCell className="text-xs">{log.aiModel || "-"}</TableCell>
                          <TableCell className="text-xs text-right">
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
      </Tabs>
    </div>
  )
}
