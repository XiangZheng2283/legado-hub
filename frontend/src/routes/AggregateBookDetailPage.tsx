import { useState } from "react"
import { useParams, useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
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
import { ArrowLeft, RotateCcw, Search, Loader2, ChevronLeft, ChevronRight } from "lucide-react"

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

function bookStatusBadge(status?: string) {
  const map: Record<string, { label: string; variant: "success" | "warning" | "info" | "destructive" | "outline" }> = {
    active: { label: "进行中", variant: "success" },
    running: { label: "运行中", variant: "success" },
    paused: { label: "已暂停", variant: "warning" },
    completed: { label: "已完成", variant: "info" },
    error: { label: "错误", variant: "destructive" },
    pending: { label: "等待中", variant: "outline" },
  }
  const entry = map[status || ""] || { label: status || "未知", variant: "outline" as const }
  return <Badge variant={entry.variant}>{entry.label}</Badge>
}

export function AggregateBookDetailPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [statusFilter, setStatusFilter] = useState("all")
  const [keyword, setKeyword] = useState("")
  const [page, setPage] = useState(1)
  const pageSize = 30

  const { data: book, isLoading: bookLoading } = useQuery({
    queryKey: ["aggregateBook", bookId],
    queryFn: () => api.aggregateBook(bookId!),
    enabled: !!bookId,
    refetchInterval: 5000,
  })

  const { data: health } = useQuery({
    queryKey: ["consoleStatus"],
    queryFn: api.status,
    refetchInterval: 5000,
  })

  const chapterParams: Record<string, string> = { page: String(page), limit: String(pageSize) }
  if (statusFilter !== "all") chapterParams.status = statusFilter
  if (keyword.trim()) chapterParams.keyword = keyword.trim()

  const { data: chapterData, isLoading: chaptersLoading } = useQuery({
    queryKey: ["aggregateBookChapters", bookId, statusFilter, keyword, page],
    queryFn: () => api.aggregateBookChapters(bookId!, chapterParams),
    enabled: !!bookId,
    refetchInterval: 5000,
  })

  const retryMut = useMutation({
    mutationFn: (chapterId: string) => api.retryAggregateChapter(bookId!, chapterId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["aggregateBookChapters", bookId] }),
  })

  if (bookLoading) {
    return (
      <div className="flex items-center justify-center py-12 text-muted-foreground">
        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
        加载中...
      </div>
    )
  }

  if (!book) {
    return <div className="text-muted-foreground">书籍未找到</div>
  }

  const chapters = chapterData?.items || chapterData?.chapters || []
  const total = chapterData?.total || 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const progress = book.totalChapters
    ? Math.round(((book.processedChapters || 0) / book.totalChapters) * 100)
    : 0

  return (
    <div className="space-y-4">
      {/* Back + Header */}
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => navigate("/console/aggregate-books")}>
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <h1 className="text-xl font-semibold">{book.name}</h1>
        {bookStatusBadge(book.status)}
        {health ? (
          <Badge variant="outline" className="text-xs gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
            后端在线
          </Badge>
        ) : (
          <Badge variant="destructive" className="text-xs gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-current" />
            后端离线
          </Badge>
        )}
      </div>

      {/* Book Info */}
      <Card>
        <CardContent className="py-4">
          <div className="grid grid-cols-4 gap-4 text-sm">
            <div>
              <span className="text-muted-foreground">作者：</span>
              <span className="font-medium">{book.author}</span>
            </div>
            <div>
              <span className="text-muted-foreground">主源：</span>
              <span className="font-medium">{book.primarySourceId || "-"}</span>
            </div>
            <div>
              <span className="text-muted-foreground">进度：</span>
              <span className="font-medium">
                {book.processedChapters ?? 0}/{book.totalChapters ?? 0}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Tokens：</span>
              <span className="font-medium">{book.totalTokens?.toLocaleString() ?? "-"}</span>
            </div>
          </div>
          <div className="mt-3">
            <div className="h-2 bg-muted rounded-full overflow-hidden">
              <div
                className="h-full bg-primary rounded-full transition-all"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground mt-1">{progress}% 完成</p>
          </div>
        </CardContent>
      </Card>

      {/* Chapter Table */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm">章节列表</CardTitle>
            <div className="flex items-center gap-2">
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  value={keyword}
                  onChange={(e) => { setKeyword(e.target.value); setPage(1) }}
                  placeholder="搜索章节..."
                  className="pl-8 w-48 h-8"
                />
              </div>
              <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1) }}>
                <SelectTrigger className="w-28 h-8">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">全部</SelectItem>
                  <SelectItem value="processed">已完成</SelectItem>
                  <SelectItem value="fallback">回退</SelectItem>
                  <SelectItem value="error">错误</SelectItem>
                  <SelectItem value="pending">等待中</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {chaptersLoading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
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
                  <TableHead className="w-16">序号</TableHead>
                  <TableHead>标题</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>内容长度</TableHead>
                  <TableHead>AI 模型</TableHead>
                  <TableHead>Tokens</TableHead>
                  <TableHead>偏差分数</TableHead>
                  <TableHead>AI 自评分</TableHead>
                  <TableHead>回退源</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {chapters.map((ch: any) => (
                  <TableRow
                    key={ch.id}
                    className="cursor-pointer"
                    onClick={() =>
                      navigate(`/console/aggregate-books/${bookId}/chapters/${ch.id}`)
                    }
                  >
                    <TableCell className="text-muted-foreground">{ch.index ?? ch.chapterIndex ?? "-"}</TableCell>
                    <TableCell className="font-medium max-w-[200px] truncate">
                      {ch.title}
                    </TableCell>
                    <TableCell>{statusBadge(ch.status)}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {ch.contentLength?.toLocaleString() ?? "-"}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {ch.aiModel || "-"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {ch.aiTotalTokens?.toLocaleString() ?? ch.tokens?.toLocaleString() ?? "-"}
                    </TableCell>
                    <TableCell>
                      {ch.deviationScore != null ? (
                        <span
                          className={
                            ch.deviationScore < 0.8
                              ? "text-destructive font-medium"
                              : ch.deviationScore < 0.9
                                ? "text-yellow-600"
                                : "text-muted-foreground"
                          }
                        >
                          {ch.deviationScore.toFixed(2)}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">-</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {ch.aiSelfScore != null ? ch.aiSelfScore.toFixed(2) : "-"}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {ch.fallbackSourceId || "-"}
                    </TableCell>
                    <TableCell className="text-right">
                      {(ch.status === "error" || ch.status === "fallback") && (
                        <Button
                          variant="ghost"
                          size="sm"
                          title="重试"
                          onClick={(e) => {
                            e.stopPropagation()
                            retryMut.mutate(ch.id)
                          }}
                        >
                          <RotateCcw className="w-4 h-4" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>共 {total} 章</span>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage((p) => p - 1)}
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <span>
              {page} / {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => p + 1)}
            >
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
