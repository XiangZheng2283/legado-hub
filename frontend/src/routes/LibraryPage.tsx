import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import {
  AlertCircle,
  Archive,
  BookOpen,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Settings,
  Trash2,
  User,
} from "lucide-react"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Alert, AlertDescription } from "@/components/ui/alert"

interface LibraryBook {
  aggregateBookId: string
  displayName: string
  displayAuthor: string
  coverUrl?: string
  wordCount?: string
  totalChapters: number
  processedChapters: number
  visibleProcessedChapters: number
  status: "active" | "paused" | "archived" | "error"
  bookStatus: "ongoing" | "completed"
  addedByUsername?: string
  lastChapterTitle?: string
  lastCheckedAt?: string
}

function statusBadge(status: string) {
  if (status === "active") return <Badge variant="success">处理中</Badge>
  if (status === "paused") return <Badge variant="warning">已暂停</Badge>
  if (status === "archived") return <Badge variant="secondary">已归档</Badge>
  if (status === "error") return <Badge variant="destructive">异常</Badge>
  return <Badge variant="outline">{status}</Badge>
}

function bookStatusBadge(status: string) {
  if (status === "completed") return <Badge variant="secondary">已完结</Badge>
  return <Badge variant="outline">连载中</Badge>
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
  const books: LibraryBook[] =
    (activeData as { items?: LibraryBook[] } | undefined)
      ?.items || []

  const filteredBooks = books.filter(
    (b) =>
      b.displayName.toLowerCase().includes(search.toLowerCase()) ||
      (b.displayAuthor || "").toLowerCase().includes(search.toLowerCase())
  )

  const renderBookRow = (book: LibraryBook) => (
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
              className="w-10 h-14 object-cover rounded bg-muted"
            />
          ) : (
            <div className="w-10 h-14 rounded bg-muted flex items-center justify-center">
              <BookOpen className="w-4 h-4 text-muted-foreground" />
            </div>
          )}
          <div>
            <p className="font-medium">{book.displayName}</p>
            <p className="text-xs text-muted-foreground">{book.displayAuthor || "未知作者"}</p>
          </div>
        </div>
      </TableCell>
      <TableCell>{statusBadge(book.status)}</TableCell>
      <TableCell>{bookStatusBadge(book.bookStatus)}</TableCell>
      <TableCell>
        <div className="w-32">
          <Progress
            value={book.totalChapters ? (book.processedChapters / book.totalChapters) * 100 : 0}
            className="h-2"
          />
          <p className="text-xs text-muted-foreground mt-1">
            {book.processedChapters}/{book.totalChapters}
          </p>
        </div>
      </TableCell>
      <TableCell className="text-xs text-muted-foreground max-w-[200px] truncate">
        {book.lastChapterTitle || "-"}
      </TableCell>
      <TableCell className="text-xs text-muted-foreground">
        {book.addedByUsername || "-"}
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
          {book.status === "active" ? (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => actionMutation.mutate({ bookId: book.aggregateBookId, action: "pause" })}
            >
              <Pause className="w-4 h-4" />
            </Button>
          ) : (
            <Button
              variant="ghost"
              size="icon"
              onClick={() => actionMutation.mutate({ bookId: book.aggregateBookId, action: "resume" })}
            >
              <Play className="w-4 h-4" />
            </Button>
          )}
          {isAdmin && (
            <>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => actionMutation.mutate({ bookId: book.aggregateBookId, action: "archive" })}
              >
                <Archive className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => actionMutation.mutate({ bookId: book.aggregateBookId, action: "rebuild" })}
              >
                <RefreshCw className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => {
                  setSettingsBook(book)
                  setSettingsPayload({})
                }}
              >
                <Settings className="w-4 h-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="text-destructive"
                onClick={() => setDeleteBook(book)}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </>
          )}
        </div>
      </TableCell>
    </TableRow>
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">共享书库</h1>
        <Badge variant="outline">全局共享</Badge>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <div className="flex items-center justify-between">
          <TabsList>
            {isAdmin && <TabsTrigger value="all">全部书库</TabsTrigger>}
            <TabsTrigger value="mine">我添加的</TabsTrigger>
          </TabsList>
          <Input
            placeholder="搜索书名/作者..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-64"
          />
        </div>
        <TabsContent value="all" className="mt-4">
          {allQuery.isLoading ? (
            <div className="text-muted-foreground">加载中...</div>
          ) : (
            <Card>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>书籍</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>连载</TableHead>
                    <TableHead>进度</TableHead>
                    <TableHead>最新章节</TableHead>
                    <TableHead>添加人</TableHead>
                    <TableHead className="w-[200px]">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredBooks.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-muted-foreground">
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
        <TabsContent value="mine" className="mt-4">
          {mineQuery.isLoading ? (
            <div className="text-muted-foreground">加载中...</div>
          ) : (
            <Card>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>书籍</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead>连载</TableHead>
                    <TableHead>进度</TableHead>
                    <TableHead>最新章节</TableHead>
                    <TableHead>添加人</TableHead>
                    <TableHead className="w-[200px]">操作</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filteredBooks.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-muted-foreground">
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
      </Tabs>

      <Dialog open={!!deleteBook} onOpenChange={(open) => !open && setDeleteBook(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确认删除</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            删除后无法恢复，将清理所有章节文件和处理任务。
          </p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteBook(null)}>
              取消
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteBook && deleteMutation.mutate(deleteBook.aggregateBookId)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
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
                onCheckedChange={(v) =>
                  setSettingsPayload((p) => ({ ...p, aiAggregateEnabled: v }))
                }
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="aiPurify">AI 净化</Label>
              <Switch
                id="aiPurify"
                checked={settingsPayload.aiPurifyEnabled ?? true}
                onCheckedChange={(v) =>
                  setSettingsPayload((p) => ({ ...p, aiPurifyEnabled: v }))
                }
              />
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="autoTrack">自动追更</Label>
              <Switch
                id="autoTrack"
                checked={settingsPayload.autoTrackUpdates ?? true}
                onCheckedChange={(v) =>
                  setSettingsPayload((p) => ({ ...p, autoTrackUpdates: v }))
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
              {settingsMutation.isPending && <Loader2 className="w-4 h-4 mr-2 animate-spin" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
