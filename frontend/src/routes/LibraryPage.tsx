import { useMemo, useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Search, MoreVertical, Play, Pause, Archive, RefreshCw, Trash2, Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Badge } from "@/components/ui/badge"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface LibraryBook {
  aggregateBookId: string
  displayName: string
  displayAuthor: string
  coverUrl?: string
  totalChapters: number
  processedChapters: number
  visibleProcessedChapters: number
  failedChapters?: number
  status: string
  bookStatus: string
  lastChapterTitle?: string
  intro?: string
  wordCount?: string
  primarySourceName?: string
  subscription?: {
    status: "active" | "paused" | "archived"
    startChapterIndex: number
    autoArchiveOnComplete: boolean
  }
  personalProgress?: {
    fullCount: number
    previewCount: number
    failedCount: number
    pendingCount: number
    coverageRatio: number
  }
}

function processStatusLabel(status: string) {
  switch (status) {
    case "completed":
      return <Badge className="rounded-full border border-emerald-200 bg-emerald-50 text-emerald-600 hover:bg-emerald-50">已完成</Badge>
    case "active":
      return <Badge className="rounded-full border border-slate-200 bg-slate-100 text-slate-700 hover:bg-slate-100">处理中</Badge>
    case "error":
      return <Badge className="rounded-full border border-rose-200 bg-rose-50 text-rose-600 hover:bg-rose-50">异常</Badge>
    case "archived":
      return <Badge className="rounded-full border border-slate-200 bg-slate-100 text-slate-500 hover:bg-slate-100">已归档</Badge>
    case "paused":
      return <Badge className="rounded-full border border-slate-200 bg-slate-100 text-slate-500 hover:bg-slate-100">已暂停</Badge>
    default:
      return <Badge className="rounded-full border border-slate-200 bg-slate-100 text-slate-500 hover:bg-slate-100">未知</Badge>
  }
}

export function LibraryPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()
  const isAdmin = user?.role === "admin"

  const [searchQuery, setSearchQuery] = useState("")
  const [deleteBookId, setDeleteBookId] = useState<string | null>(null)

  const { data, isLoading, error: libraryError } = useQuery({
    queryKey: ["library", isAdmin ? "admin" : "mine"],
    queryFn: () => isAdmin ? api.libraryBooks() : api.subscribe.myLibrary(),
  })

  const actionMutation = useMutation({
    mutationFn: async ({ bookId, action }: { bookId: string; action: string }) => {
      if (!isAdmin) {
        const status = action === "resume" ? "active" : action === "pause" ? "paused" : "archived"
        return api.subscribe.updateSubscription(bookId, { status })
      }
      if (action === "pause") return api.pauseLibraryBook(bookId)
      if (action === "resume") return api.resumeLibraryBook(bookId)
      if (action === "archive") return api.archiveLibraryBook(bookId)
      return api.rebuildLibraryBook(bookId)
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["library"] }) },
  })

  const deleteMutation = useMutation({
    mutationFn: (bookId: string) => api.deleteLibraryBook(bookId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library"] })
      setDeleteBookId(null)
    },
  })

  const books: LibraryBook[] = useMemo(() => {
    const items = (data as { items?: LibraryBook[] } | undefined)?.items || []
    if (!searchQuery) return items
    return items.filter(
      (b) =>
        b.displayName.toLowerCase().includes(searchQuery.toLowerCase()) ||
        (b.displayAuthor || "").toLowerCase().includes(searchQuery.toLowerCase())
    )
  }, [data, searchQuery])

  const bookToDelete = books.find((b) => b.aggregateBookId === deleteBookId)
  const mutationError = actionMutation.error || deleteMutation.error
  const libraryBusy = actionMutation.isPending || deleteMutation.isPending

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-slate-900">{isAdmin ? "全局书库" : "我的书库"}</h1>
          <p className="mt-1 text-sm text-slate-500">{isAdmin ? `共 ${books.length} 本书籍` : "个人订阅、章节覆盖与处理状态"}</p>
        </div>
      </div>

      <div className="flex flex-col sm:flex-row gap-4 items-center">
        <div className="w-full relative group shadow-sm hover:shadow transition-shadow duration-300 rounded-full bg-white border border-slate-200 focus-within:border-blue-400 focus-within:ring-2 focus-within:ring-blue-400/10 flex-1">
          <div className="flex items-center w-full px-1 py-1">
            <div className="pl-4 pr-2 text-slate-400 group-focus-within:text-blue-500 transition-colors">
              <Search className="h-4 w-4" />
            </div>
            <input
              type="text"
              name="library-search"
              autoComplete="off"
              placeholder="在书库中搜索…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="flex-1 bg-transparent border-0 py-2 md:py-2.5 text-sm focus:outline-none focus:ring-0 text-slate-800 placeholder:text-slate-400"
            />
          </div>
        </div>
      </div>

      {(libraryError || mutationError) && (
        <Alert variant="destructive">
          <AlertDescription>
            {(mutationError as Error)?.message || (libraryError as Error)?.message || "书库操作失败，请稍后重试。"}
          </AlertDescription>
        </Alert>
      )}

      {isLoading ? (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
        </div>
      ) : books.length > 0 ? (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {books.map((book) => {
            const personal = book.personalProgress
            const displayStatus = isAdmin ? book.status : book.subscription?.status || "unknown"
            const progress = isAdmin
              ? (book.totalChapters > 0 ? Math.round((book.processedChapters / book.totalChapters) * 100) : 0)
              : Math.round(Math.max(0, Math.min(1, personal?.coverageRatio ?? 0)) * 100)
            const failedCount = isAdmin ? book.failedChapters : personal?.failedCount
            const hasError = typeof failedCount === "number" && failedCount > 0
            return (
              <Card key={book.aggregateBookId} className="overflow-hidden flex flex-col hover:shadow-lg transition-shadow duration-200 relative group">
                <Link
                  className="absolute inset-0 z-10 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-400 focus-visible:ring-offset-2"
                  aria-label={`打开《${book.displayName}》详情`}
                  to={`/console/library/${book.aggregateBookId}`}
                />
                <div className="flex p-5 gap-4">
                  <div className="relative w-20 h-28 bg-slate-200 rounded-md overflow-hidden flex-shrink-0 shadow-sm">
                    {book.coverUrl ? (
                      <img src={book.coverUrl} alt={book.displayName} width={80} height={112} loading="lazy" className="w-full h-full object-cover" />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center text-slate-400">
                        <Search className="h-6 w-6" />
                      </div>
                    )}
                    {isAdmin && book.primarySourceName && (
                      <div className="absolute bottom-0 left-0 right-0 bg-black/60 backdrop-blur-sm py-1 px-1.5">
                        <p className="text-[9px] text-white/90 text-center truncate">{book.primarySourceName}</p>
                      </div>
                    )}
                  </div>

                  <div className="flex flex-col flex-1 min-w-0">
                    <div className="flex justify-between items-start">
                      <h3 className="font-semibold text-slate-900 truncate text-base">{book.displayName}</h3>

                      <div className="relative z-20">
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 -mr-2 -mt-1"
                              aria-label={`打开《${book.displayName}》操作菜单`}
                            >
                              <MoreVertical className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-36">
                            {isAdmin && (
                              <DropdownMenuItem disabled={libraryBusy} onSelect={() => actionMutation.mutate({ bookId: book.aggregateBookId, action: "rebuild" })}>
                                <RefreshCw className="h-3 w-3 mr-2" /> 重新处理
                              </DropdownMenuItem>
                            )}
                            {displayStatus === "paused" || displayStatus === "archived" ? (
                              <DropdownMenuItem disabled={libraryBusy} onSelect={() => actionMutation.mutate({ bookId: book.aggregateBookId, action: "resume" })}>
                                <Play className="h-3 w-3 mr-2" /> 继续
                              </DropdownMenuItem>
                            ) : (
                              <DropdownMenuItem disabled={libraryBusy} onSelect={() => actionMutation.mutate({ bookId: book.aggregateBookId, action: "pause" })}>
                                <Pause className="h-3 w-3 mr-2" /> 暂停
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuItem disabled={libraryBusy} onSelect={() => actionMutation.mutate({ bookId: book.aggregateBookId, action: "archive" })}>
                              <Archive className="h-3 w-3 mr-2" /> 归档
                            </DropdownMenuItem>
                            {isAdmin && (
                              <>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem disabled={libraryBusy} className="text-rose-600 focus:text-rose-600" onSelect={() => setDeleteBookId(book.aggregateBookId)}>
                                  <Trash2 className="h-3 w-3 mr-2" /> 删除
                                </DropdownMenuItem>
                              </>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </div>

                    <p className="text-sm text-slate-500 truncate mt-0.5">{book.displayAuthor || "未知作者"}</p>

                    <div className="mt-2.5 text-xs text-slate-500 flex flex-wrap items-center gap-x-1.5 gap-y-1">
                      <span className={book.bookStatus === "ongoing" ? "text-emerald-600" : "text-slate-600"}>
                        {book.bookStatus === "completed" ? "已完结" : "连载中"}
                      </span>
                      {book.wordCount && (
                        <>
                          <span className="text-slate-300">•</span>
                          <span>{book.wordCount}</span>
                        </>
                      )}
                    </div>

                    <div className="mt-auto pt-2 text-xs text-slate-400">
                      {book.lastChapterTitle ? `最新至 ${book.lastChapterTitle}` : ""}
                    </div>
                  </div>
                </div>

                {book.intro && (
                  <div className="px-5 py-4 bg-slate-50/50 border-t border-slate-100 flex-1 flex flex-col">
                    <p className="text-xs text-slate-600 line-clamp-3 leading-relaxed flex-1">{book.intro}</p>
                  </div>
                )}

                <div className="p-4 border-t border-slate-100 mt-auto bg-white flex flex-col justify-end">
                  <div className="flex justify-between items-center mb-2 text-xs text-slate-500">
                    <div className="flex items-center gap-2">
                      {processStatusLabel(displayStatus)}
                    </div>
                    <span>{progress}%</span>
                  </div>
                  <Progress
                    value={progress}
                    className="h-1.5"
                    indicatorClassName={
                      displayStatus === "error" ? "bg-rose-500" :
                      displayStatus === "completed" ? "bg-emerald-500" :
                      displayStatus === "archived" ? "bg-slate-400" :
                      "bg-slate-500"
                    }
                  />
                  <div className="mt-2.5 text-xs text-slate-500 flex items-center gap-2">
                    <span>{isAdmin ? `可阅读 ${book.visibleProcessedChapters}` : `全文 ${personal?.fullCount ?? 0} · 预览 ${personal?.previewCount ?? 0}`}</span>
                    <span className="text-slate-300">·</span>
                    <span className={hasError ? "text-rose-500" : ""}>
                      {typeof failedCount === "number" ? `失败 ${failedCount}` : "失败数未知"}
                    </span>
                    {!isAdmin && <><span className="text-slate-300">·</span><span>待处理 {personal?.pendingCount ?? 0}</span></>}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 bg-slate-50 rounded-full flex items-center justify-center mb-4 text-slate-400">
            <Search className="h-8 w-8" />
          </div>
          {searchQuery ? (
            <p className="text-slate-500">当前范围没有匹配书籍</p>
          ) : (
            <>
              <p className="text-slate-500 mb-4">{isAdmin ? "暂无书籍" : "你还没有订阅的书籍"}</p>
              <Button onClick={() => navigate("/console/subscription")}>去发现新书</Button>
            </>
          )}
        </div>
      )}

      <Dialog open={!!deleteBookId} onOpenChange={(open) => { if (!open) setDeleteBookId(null) }}>
        <DialogContent onClick={(e) => e.stopPropagation()}>
          <DialogHeader>
            <DialogTitle>删除书籍</DialogTitle>
            <DialogDescription>
              确定要将《{bookToDelete?.displayName}》从书库中删除吗？此操作不可逆，将删除所有相关章节数据。
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteBookId(null)}>取消</Button>
            <Button variant="destructive" onClick={() => bookToDelete && deleteMutation.mutate(bookToDelete.aggregateBookId)} disabled={libraryBusy}>
              {deleteMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              确认删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
