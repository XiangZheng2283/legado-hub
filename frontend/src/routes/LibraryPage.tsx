import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Archive,
  BookOpen,
  Eye,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Settings,
  Trash2,
} from "lucide-react"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Progress } from "@/components/ui/progress"
import { Switch } from "@/components/ui/switch"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"

interface LibraryBook {
  aggregateBookId: string
  displayName: string
  displayAuthor: string
  coverUrl?: string
  wordCount?: string
  totalChapters: number
  processedChapters: number
  visibleProcessedChapters: number
  failedChapters?: number
  status: "active" | "paused" | "archived" | "error"
  bookStatus: "ongoing" | "completed"
  searchVisibilityStatus?: "visible" | "hidden" | string
  addedByUsername?: string
  lastChapterTitle?: string
  lastCheckedAt?: string
  autoArchiveOnComplete?: boolean
  startChapterIndex?: number
  settingsJson?: string
}

function processingStatusBadge(status: string) {
  if (status === "active") return <Badge variant="info">处理中</Badge>
  if (status === "paused") return <Badge variant="warning">已暂停</Badge>
  if (status === "archived") return <Badge variant="secondary">已归档</Badge>
  if (status === "error") return <Badge variant="destructive">异常</Badge>
  return <Badge variant="outline">{status}</Badge>
}

function visibilityBadge(status?: string) {
  if (status === "visible") return <Badge variant="success">可发现</Badge>
  if (status === "hidden") return <Badge variant="outline">隐藏</Badge>
  return <Badge variant="outline">{status || "未知"}</Badge>
}

function bookStatusBadge(status: string) {
  if (status === "completed") return <Badge variant="secondary">已完结</Badge>
  return <Badge variant="outline">连载中</Badge>
}

function formatDate(value?: string) {
  if (!value) return "-"
  try {
    return new Date(value).toLocaleString("zh-CN")
  } catch {
    return value
  }
}

function parseBookSettings(book: LibraryBook | null) {
  if (!book?.settingsJson) {
    return {
      aiAggregateEnabled: true,
      aiPurifyEnabled: true,
      autoTrackUpdates: true,
    }
  }
  try {
    const parsed = JSON.parse(book.settingsJson)
    return {
      aiAggregateEnabled: parsed.aiAggregateEnabled ?? true,
      aiPurifyEnabled: parsed.aiPurifyEnabled ?? true,
      autoTrackUpdates: parsed.autoTrackUpdates ?? true,
    }
  } catch {
    return {
      aiAggregateEnabled: true,
      aiPurifyEnabled: true,
      autoTrackUpdates: true,
    }
  }
}

export function LibraryPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const [activeTab, setActiveTab] = useState("all")
  const [search, setSearch] = useState("")
  const [settingsBook, setSettingsBook] = useState<LibraryBook | null>(null)
  const [deleteBook, setDeleteBook] = useState<LibraryBook | null>(null)
  const [settingsPayload, setSettingsPayload] = useState<Record<string, any>>({})

  const isAdmin = user?.role === "admin"

  const allQuery = useQuery({
    queryKey: ["library", "all"],
    queryFn: () => api.libraryBooks(),
    enabled: isAdmin,
  })

  const mineQuery = useQuery({
    queryKey: ["library", "mine"],
    queryFn: api.subscribe.myLibrary,
  })

  const actionMutation = useMutation({
    mutationFn: async ({
      bookId,
      action,
    }: {
      bookId: string
      action: "pause" | "resume" | "archive" | "rebuild"
    }) => {
      if (action === "pause") return api.pauseLibraryBook(bookId)
      if (action === "resume") return api.resumeLibraryBook(bookId)
      if (action === "archive") return api.archiveLibraryBook(bookId)
      return api.rebuildLibraryBook(bookId)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library"] })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (bookId: string) => api.deleteLibraryBook(bookId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library"] })
      setDeleteBook(null)
    },
  })

  const settingsMutation = useMutation({
    mutationFn: ({ bookId, payload }: { bookId: string; payload: Record<string, any> }) =>
      api.updateLibraryBookSettings(bookId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library"] })
      setSettingsBook(null)
    },
  })

  const activeData = activeTab === "all" && isAdmin ? allQuery.data : mineQuery.data
  const books: LibraryBook[] = (activeData as { items?: LibraryBook[] } | undefined)?.items || []

  const filteredBooks = useMemo(
    () =>
      books.filter(
        (book) =>
          book.displayName.toLowerCase().includes(search.toLowerCase()) ||
          (book.displayAuthor || "").toLowerCase().includes(search.toLowerCase())
      ),
    [books, search]
  )

  const renderBookRow = (book: LibraryBook) => {
    const progress =
      book.totalChapters > 0 ? (book.processedChapters / book.totalChapters) * 100 : 0
    return (
      <TableRow
        key={book.aggregateBookId}
        className="cursor-pointer"
        onClick={() => navigate(`/console/library/${book.aggregateBookId}`)}
      >
        <TableCell>
          <div className="flex items-center gap-3">
            {book.coverUrl ? (
              <img
                src={book.coverUrl}
                alt={book.displayName}
                className="h-14 w-10 rounded bg-muted object-cover"
              />
            ) : (
              <div className="flex h-14 w-10 items-center justify-center rounded bg-muted">
                <BookOpen className="h-4 w-4 text-muted-foreground" />
              </div>
            )}
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <p className="truncate font-medium">{book.displayName}</p>
                {bookStatusBadge(book.bookStatus)}
              </div>
              <p className="truncate text-xs text-muted-foreground">
                {book.displayAuthor || "未知作者"}
              </p>
            </div>
          </div>
        </TableCell>
        <TableCell>{processingStatusBadge(book.status)}</TableCell>
        <TableCell>
          <div className="w-40 space-y-1">
            <Progress value={progress} className="h-2" />
            <div className="flex items-center justify-between text-xs text-muted-foreground">
              <span>
                {book.processedChapters}/{book.totalChapters}
              </span>
              <span>{Math.round(progress)}%</span>
            </div>
          </div>
        </TableCell>
        <TableCell>
          <div className="text-sm font-medium">{book.visibleProcessedChapters}</div>
          <div className="text-xs text-muted-foreground">可读章节</div>
        </TableCell>
        <TableCell>{visibilityBadge(book.searchVisibilityStatus)}</TableCell>
        <TableCell className="max-w-[220px]">
          <div className="truncate text-sm">{book.lastChapterTitle || "-"}</div>
          <div className="text-xs text-muted-foreground">{formatDate(book.lastCheckedAt)}</div>
        </TableCell>
        <TableCell>
          <div className="text-sm">{book.addedByUsername || "-"}</div>
          <div className="text-xs text-muted-foreground">
            失败 {book.failedChapters || 0} 章
          </div>
        </TableCell>
        <TableCell>
          <div className="flex items-center gap-1" onClick={(event) => event.stopPropagation()}>
            {book.status === "active" ? (
              <Button
                variant="ghost"
                size="icon"
                onClick={() =>
                  actionMutation.mutate({ bookId: book.aggregateBookId, action: "pause" })
                }
              >
                <Pause className="h-4 w-4" />
              </Button>
            ) : (
              <Button
                variant="ghost"
                size="icon"
                onClick={() =>
                  actionMutation.mutate({ bookId: book.aggregateBookId, action: "resume" })
                }
              >
                <Play className="h-4 w-4" />
              </Button>
            )}
            {isAdmin && (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() =>
                    actionMutation.mutate({ bookId: book.aggregateBookId, action: "archive" })
                  }
                >
                  <Archive className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() =>
                    actionMutation.mutate({ bookId: book.aggregateBookId, action: "rebuild" })
                  }
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => {
                    setSettingsBook(book)
                    setSettingsPayload(parseBookSettings(book))
                  }}
                >
                  <Settings className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="text-destructive"
                  onClick={() => setDeleteBook(book)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>
        </TableCell>
      </TableRow>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">共享书库</h1>
          <p className="text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <Eye className="h-3.5 w-3.5" />
              {filteredBooks.length}
            </span>
          </p>
        </div>
        <Badge variant="outline">全局共享</Badge>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <div className="flex items-center justify-between gap-3">
          <TabsList>
            {isAdmin && <TabsTrigger value="all">全部书库</TabsTrigger>}
            <TabsTrigger value="mine">我添加的</TabsTrigger>
          </TabsList>
          <Input
            placeholder="搜索书名/作者..."
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            className="w-64"
          />
        </div>

        {(["all", "mine"] as const).map((tab) => (
          <TabsContent key={tab} value={tab} className="mt-4">
            {(tab === "all" ? allQuery.isLoading : mineQuery.isLoading) ? (
              <div className="text-muted-foreground">加载中...</div>
            ) : (
              <Card>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>书籍</TableHead>
                      <TableHead>处理状态</TableHead>
                      <TableHead>进度</TableHead>
                      <TableHead>可读章节</TableHead>
                      <TableHead>搜索可见</TableHead>
                      <TableHead>最新章节</TableHead>
                      <TableHead>添加人</TableHead>
                      <TableHead className="w-[180px]">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredBooks.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={8} className="text-center text-muted-foreground">
                          暂无数据
                        </TableCell>
                      </TableRow>
                    ) : (
                      filteredBooks.map(renderBookRow)
                    )}
                  </TableBody>
                </Table>
              </Card>
            )}
          </TabsContent>
        ))}
      </Tabs>

      <Dialog open={!!deleteBook} onOpenChange={(open) => !open && setDeleteBook(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
          </DialogHeader>
          <Alert>
            <AlertDescription>删除后会清理章节文件与处理任务，且无法恢复。</AlertDescription>
          </Alert>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteBook(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteBook && deleteMutation.mutate(deleteBook.aggregateBookId)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!settingsBook} onOpenChange={(open) => !open && setSettingsBook(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>书库设置</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="flex items-center justify-between">
              <Label htmlFor="aiAggregate">AI 聚合</Label>
              <Switch
                id="aiAggregate"
                checked={settingsPayload.aiAggregateEnabled ?? true}
                onCheckedChange={(checked) =>
                  setSettingsPayload((prev) => ({ ...prev, aiAggregateEnabled: checked }))
                }
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="aiPurify">AI 净化</Label>
              <Switch
                id="aiPurify"
                checked={settingsPayload.aiPurifyEnabled ?? true}
                onCheckedChange={(checked) =>
                  setSettingsPayload((prev) => ({ ...prev, aiPurifyEnabled: checked }))
                }
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="autoTrack">自动追更</Label>
              <Switch
                id="autoTrack"
                checked={settingsPayload.autoTrackUpdates ?? true}
                onCheckedChange={(checked) =>
                  setSettingsPayload((prev) => ({ ...prev, autoTrackUpdates: checked }))
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSettingsBook(null)}>
              取消
            </Button>
            <Button
              onClick={() =>
                settingsBook &&
                settingsMutation.mutate({
                  bookId: settingsBook.aggregateBookId,
                  payload: settingsPayload,
                })
              }
              disabled={settingsMutation.isPending}
            >
              {settingsMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
