import { useState } from "react"
import { useParams } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { BookOpen, ChevronLeft, Clock, FileText, Loader2, User } from "lucide-react"
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

function chapterStatusBadge(status: string) {
  if (status === "processed") return <Badge variant="success">已处理</Badge>
  if (status === "fallback") return <Badge variant="warning">回退</Badge>
  if (status === "pending") return <Badge variant="info">处理中</Badge>
  if (status === "error") return <Badge variant="destructive">失败</Badge>
  return <Badge variant="outline">占位</Badge>
}

export function LibraryBookDetailPage() {
  const { bookId } = useParams<{ bookId: string }>()
  const [selectedChapter, setSelectedChapter] = useState<Chapter | null>(null)

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

  const book: BookDetail | undefined = bookQuery.data
  const chapters: Chapter[] = chaptersQuery.data?.chapters || []

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
                {new Date(book.lastCheckedAt).toLocaleString()}
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
                      <TableRow
                        key={ch.chapterIndex}
                        className="cursor-pointer"
                        onClick={() => setSelectedChapter(ch)}
                      >
                        <TableCell>{ch.chapterIndex}</TableCell>
                        <TableCell>{ch.title}</TableCell>
                        <TableCell>{chapterStatusBadge(ch.status)}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {ch.processedAt ? new Date(ch.processedAt).toLocaleString() : "-"}
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
    </div>
  )
}
