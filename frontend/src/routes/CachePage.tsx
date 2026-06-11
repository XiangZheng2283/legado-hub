import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { BookOpen, FileText, HardDrive, ListTree, Search, Trash2 } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

function shortId(value = "") {
  if (!value) return "-"
  return value.length > 34 ? `${value.slice(0, 18)}...${value.slice(-10)}` : value
}

function timeText(value = "") {
  return value ? value.replace("T", " ").replace("+00:00", "") : "-"
}

export function CachePage() {
  const queryClient = useQueryClient()
  const statsQuery = useQuery({
    queryKey: ["cache"],
    queryFn: api.cache,
  })
  const itemsQuery = useQuery({
    queryKey: ["cacheItems"],
    queryFn: api.cacheItems,
  })

  const clearMutation = useMutation({
    mutationFn: api.clearCache,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cache"] })
      queryClient.invalidateQueries({ queryKey: ["cacheItems"] })
    },
  })

  const clearChapterMutation = useMutation({
    mutationFn: () => api.clearCacheByType("chapter"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["cache"] })
      queryClient.invalidateQueries({ queryKey: ["cacheItems"] })
    },
  })

  const stats = statsQuery.data || {}
  const cacheItems = itemsQuery.data || {}
  const summaryItems = [
    { label: "搜索", value: stats.searchCache || 0, icon: Search },
    { label: "书籍", value: stats.bookCache || 0, icon: BookOpen },
    { label: "目录", value: stats.tocCache || 0, icon: ListTree },
    { label: "章节", value: stats.chapterCache || 0, icon: FileText },
  ]

  return (
    <div className="flex h-[calc(100vh-3rem)] min-h-0 flex-col gap-4 overflow-hidden">
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">缓存列表</h1>
          <p className="text-sm text-muted-foreground">
            查看当前搜索、书籍详情、目录和章节缓存；这里不做单书处理配置，只呈现运行态数据。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => clearChapterMutation.mutate()}
            disabled={clearMutation.isPending || clearChapterMutation.isPending}
          >
            <FileText className="mr-1 h-4 w-4" />
            只清章节缓存
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => clearMutation.mutate()}
            disabled={clearMutation.isPending || clearChapterMutation.isPending}
          >
            <Trash2 className="mr-1 h-4 w-4" />
            清空全部缓存
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {summaryItems.map((item) => (
          <Card key={item.label} className="rounded-lg shadow-sm">
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">{item.label}</p>
                  <p className="mt-1 text-2xl font-semibold">{item.value}</p>
                </div>
                <item.icon className="h-5 w-5 text-[#d4812a]" />
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card className="min-h-0 flex-1 overflow-hidden rounded-lg shadow-sm">
        <CardContent className="flex h-full min-h-0 flex-col p-0">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div>
              <div className="text-sm font-semibold">缓存明细</div>
              <div className="text-xs text-muted-foreground">最近 100 条，按写入时间倒序</div>
            </div>
            <Badge variant="outline" className="gap-1">
              <HardDrive className="h-3.5 w-3.5" />
              SQLite
            </Badge>
          </div>

          {statsQuery.isLoading || itemsQuery.isLoading ? (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              加载缓存中...
            </div>
          ) : (
            <Tabs defaultValue="books" className="flex min-h-0 flex-1 flex-col">
              <div className="border-b px-4 py-2">
                <TabsList>
                  <TabsTrigger value="books">书籍</TabsTrigger>
                  <TabsTrigger value="tocs">目录</TabsTrigger>
                  <TabsTrigger value="chapters">章节</TabsTrigger>
                  <TabsTrigger value="searches">搜索</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent value="books" className="min-h-0 flex-1 overflow-auto p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>书名</TableHead>
                      <TableHead>作者</TableHead>
                      <TableHead>来源</TableHead>
                      <TableHead>最新章节</TableHead>
                      <TableHead>缓存时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(cacheItems.books || []).map((item: any) => (
                      <TableRow key={item.bookId}>
                        <TableCell className="font-medium">{item.name || shortId(item.bookId)}</TableCell>
                        <TableCell>{item.author || "-"}</TableCell>
                        <TableCell><Badge variant="outline">{item.sourceId || "-"}</Badge></TableCell>
                        <TableCell className="max-w-xs truncate">{item.lastChapter || "-"}</TableCell>
                        <TableCell className="text-muted-foreground">{timeText(item.createdAt)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TabsContent>

              <TabsContent value="tocs" className="min-h-0 flex-1 overflow-auto p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Book ID</TableHead>
                      <TableHead>章节数</TableHead>
                      <TableHead>首章</TableHead>
                      <TableHead>末章</TableHead>
                      <TableHead>缓存时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(cacheItems.tocs || []).map((item: any) => (
                      <TableRow key={item.bookId}>
                        <TableCell className="font-mono text-xs">{shortId(item.bookId)}</TableCell>
                        <TableCell>{item.chapterCount}</TableCell>
                        <TableCell className="max-w-xs truncate">{item.firstTitle || "-"}</TableCell>
                        <TableCell className="max-w-xs truncate">{item.lastTitle || "-"}</TableCell>
                        <TableCell className="text-muted-foreground">{timeText(item.createdAt)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TabsContent>

              <TabsContent value="chapters" className="min-h-0 flex-1 overflow-auto p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>章节</TableHead>
                      <TableHead>来源</TableHead>
                      <TableHead>正文长度</TableHead>
                      <TableHead>Chapter ID</TableHead>
                      <TableHead>缓存时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(cacheItems.chapters || []).map((item: any) => (
                      <TableRow key={item.chapterId}>
                        <TableCell className="font-medium">{item.title || "-"}</TableCell>
                        <TableCell><Badge variant="outline">{item.sourceId || "-"}</Badge></TableCell>
                        <TableCell>{item.contentLength}</TableCell>
                        <TableCell className="font-mono text-xs">{shortId(item.chapterId)}</TableCell>
                        <TableCell className="text-muted-foreground">{timeText(item.createdAt)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TabsContent>

              <TabsContent value="searches" className="min-h-0 flex-1 overflow-auto p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>关键词</TableHead>
                      <TableHead>页码</TableHead>
                      <TableHead>结果数</TableHead>
                      <TableHead>缓存时间</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {(cacheItems.searches || []).map((item: any) => (
                      <TableRow key={`${item.keyword}:${item.page}`}>
                        <TableCell className="font-medium">{item.keyword || "-"}</TableCell>
                        <TableCell>{item.page}</TableCell>
                        <TableCell>{item.itemCount}</TableCell>
                        <TableCell className="text-muted-foreground">{timeText(item.createdAt)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TabsContent>
            </Tabs>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
