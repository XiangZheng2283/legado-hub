import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import {
  Play,
  Pause,
  RotateCcw,
  Trash2,
  ChevronLeft,
  ChevronRight,
  Loader2,
} from "lucide-react"

function statusBadge(status?: string) {
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

export function AggregateBookshelfPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState("all")
  const [page, setPage] = useState(1)
  const pageSize = 20

  const params: Record<string, string> = { page: String(page), limit: String(pageSize) }
  if (statusFilter !== "all") params.status = statusFilter

  const { data, isLoading } = useQuery({
    queryKey: ["aggregateBooks", statusFilter, page],
    queryFn: () => api.aggregateBooks(params),
  })

  const runMut = useMutation({
    mutationFn: (id: string) => api.runAggregateBook(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["aggregateBooks"] }),
  })
  const pauseMut = useMutation({
    mutationFn: (id: string) => api.pauseAggregateBook(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["aggregateBooks"] }),
  })
  const resumeMut = useMutation({
    mutationFn: (id: string) => api.resumeAggregateBook(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["aggregateBooks"] }),
  })
  const deleteMut = useMutation({
    mutationFn: (id: string) => api.deleteAggregateBook(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["aggregateBooks"] }),
  })

  const books = data?.items || data?.books || []
  const total = data?.total || 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">聚合书架</h1>
        <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1) }}>
          <SelectTrigger className="w-32">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">全部</SelectItem>
            <SelectItem value="active">进行中</SelectItem>
            <SelectItem value="paused">已暂停</SelectItem>
            <SelectItem value="completed">已完成</SelectItem>
            <SelectItem value="error">错误</SelectItem>
          </SelectContent>
        </Select>
      </div>

      <Card>
        <CardContent className="p-0">
          {isLoading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              加载中...
            </div>
          ) : books.length === 0 ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              暂无聚合书籍
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>书名</TableHead>
                  <TableHead>作者</TableHead>
                  <TableHead>主源</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>进度</TableHead>
                  <TableHead>失败</TableHead>
                  <TableHead>Tokens</TableHead>
                  <TableHead>最后处理</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {books.map((book: any) => (
                  <TableRow
                    key={book.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/console/aggregate-books/${book.id}`)}
                  >
                    <TableCell className="font-medium">
                      <TooltipProvider>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className={book.lastError ? "text-destructive" : ""}>{book.name}</span>
                          </TooltipTrigger>
                          {book.lastError && (
                            <TooltipContent side="top" className="max-w-xs">
                              <p>{book.lastError}</p>
                            </TooltipContent>
                          )}
                        </Tooltip>
                      </TooltipProvider>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{book.author}</TableCell>
                    <TableCell className="text-muted-foreground text-sm">{book.primarySourceId || "-"}</TableCell>
                    <TableCell>{statusBadge(book.status)}</TableCell>
                    <TableCell>
                      {book.processedChapters ?? 0}/{book.totalChapters ?? 0}
                    </TableCell>
                    <TableCell>
                      {book.failedChapters > 0 ? (
                        <Badge variant="destructive">{book.failedChapters}</Badge>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {book.totalTokens?.toLocaleString() ?? "-"}
                    </TableCell>
                    <TableCell className="text-muted-foreground text-sm">
                      {book.lastProcessedAt
                        ? new Date(book.lastProcessedAt).toLocaleString("zh-CN")
                        : "-"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {(book.status === "paused" || book.status === "error" || book.status === "pending") && (
                          <Button
                            variant="ghost"
                            size="sm"
                            title="运行"
                            onClick={(e) => {
                              e.stopPropagation()
                              runMut.mutate(book.id)
                            }}
                          >
                            <Play className="w-4 h-4" />
                          </Button>
                        )}
                        {(book.status === "active" || book.status === "running") && (
                          <Button
                            variant="ghost"
                            size="sm"
                            title="暂停"
                            onClick={(e) => {
                              e.stopPropagation()
                              pauseMut.mutate(book.id)
                            }}
                          >
                            <Pause className="w-4 h-4" />
                          </Button>
                        )}
                        {book.status === "paused" && (
                          <Button
                            variant="ghost"
                            size="sm"
                            title="恢复"
                            onClick={(e) => {
                              e.stopPropagation()
                              resumeMut.mutate(book.id)
                            }}
                          >
                            <RotateCcw className="w-4 h-4" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          title="删除"
                          onClick={(e) => {
                            e.stopPropagation()
                            if (confirm(`确认删除《${book.name}》？`)) {
                              deleteMut.mutate(book.id)
                            }
                          }}
                        >
                          <Trash2 className="w-4 h-4 text-destructive" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {totalPages > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>共 {total} 本</span>
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
