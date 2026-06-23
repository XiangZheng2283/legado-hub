import { useEffect, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useNavigate } from "react-router-dom"
import {
  BookOpen,
  Check,
  Loader2,
  Plus,
  Search,
  User,
  Library,
  AlertCircle,
} from "lucide-react"
import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Alert, AlertDescription } from "@/components/ui/alert"

interface SearchCard {
  candidateId: string
  name: string
  author?: string
  coverUrl?: string
  intro?: string
  wordCount?: string
  chapterCount?: number
  completed?: boolean
  status?: string
  sourceSummary?: string
  alreadyIngested?: boolean
  aggregateBookId?: string
  addedBy?: string
}

function statusBadge(status?: string, alreadyIngested?: boolean) {
  if (alreadyIngested) return <Badge variant="secondary">已入库</Badge>
  if (status === "completed") return <Badge variant="success">可订阅</Badge>
  if (status === "running") return <Badge variant="info">搜索中</Badge>
  if (status === "failed") return <Badge variant="destructive">失败</Badge>
  return <Badge variant="outline">待处理</Badge>
}

export function SubscriptionDiscoveryPage() {
  const navigate = useNavigate()
  const [keyword, setKeyword] = useState("")
  const [jobId, setJobId] = useState<string | null>(null)
  const [selectedCard, setSelectedCard] = useState<SearchCard | null>(null)
  const [startChapterIndex, setStartChapterIndex] = useState(1)
  const [autoArchive, setAutoArchive] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const searchMutation = useMutation({
    mutationFn: api.subscribe.search,
    onSuccess: (data) => {
      setJobId(data.jobId)
      setError(null)
    },
    onError: (err: any) => setError(err?.message || "搜索失败"),
  })

  const { data: jobData, isLoading: polling } = useQuery({
    queryKey: ["subscribe", "search", jobId],
    queryFn: () => (jobId ? api.subscribe.searchJob(jobId) : Promise.resolve(null)),
    enabled: !!jobId,
    refetchInterval: (query) => {
      const data = query.state.data as { status?: string } | null
      if (!data || ["completed", "failed", "cancelled"].includes(data.status || "")) return false
      return 1500
    },
  })

  const subscribeMutation = useMutation({
    mutationFn: (card: SearchCard) =>
      api.subscribe.subscribeCard(jobId!, card.candidateId, {
        startChapterIndex,
        autoArchiveOnComplete: autoArchive,
      }),
    onSuccess: (data) => {
      setSelectedCard(null)
      if (data.aggregateBookId) {
        navigate(`/console/library/${data.aggregateBookId}`)
      }
    },
    onError: (err: any) => setError(err?.message || "入库失败"),
  })

  useEffect(() => {
    if (jobData?.status === "failed" && jobData?.error) {
      setError(jobData.error)
    }
  }, [jobData])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (!keyword.trim()) return
    setJobId(null)
    setError(null)
    searchMutation.mutate({ keyword: keyword.trim(), page: 1 })
  }

  const cards: SearchCard[] = jobData?.cards || []
  const isRunning = polling && jobData && !["completed", "failed", "cancelled"].includes((jobData as { status?: string }).status || "")

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">共享订阅</h1>
        <Badge variant="outline">一书一卡片</Badge>
      </div>

      <form onSubmit={handleSearch} className="flex gap-2">
        <Input
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          placeholder="搜索书名或作者..."
          className="max-w-md"
        />
        <Button type="submit" disabled={searchMutation.isPending || isRunning}>
          {(searchMutation.isPending || isRunning) && (
            <Loader2 className="w-4 h-4 mr-2 animate-spin" />
          )}
          <Search className="w-4 h-4 mr-2" />
          搜索
        </Button>
      </form>

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="w-4 h-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {jobData && !isRunning && cards.length === 0 && !error && (
        <div className="text-sm text-muted-foreground">未找到匹配书籍。</div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {cards.map((card) => (
          <Card key={card.candidateId} className="overflow-hidden flex flex-col">
            <div className="aspect-[3/4] bg-muted relative">
              {card.coverUrl ? (
                <img
                  src={card.coverUrl}
                  alt={card.name}
                  className="w-full h-full object-cover"
                  onError={(e) => {
                    (e.target as HTMLImageElement).style.display = "none"
                  }}
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                  <BookOpen className="w-12 h-12 opacity-20" />
                </div>
              )}
              <div className="absolute top-2 right-2">
                {statusBadge(card.status, card.alreadyIngested)}
              </div>
            </div>
            <CardContent className="p-4 flex-1 flex flex-col gap-2">
              <div>
                <h3 className="font-semibold line-clamp-1" title={card.name}>
                  {card.name}
                </h3>
                <p className="text-xs text-muted-foreground line-clamp-1">
                  {card.author || "未知作者"}
                </p>
              </div>
              <p className="text-xs text-muted-foreground line-clamp-2 flex-1">
                {card.intro || "暂无简介"}
              </p>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                {card.wordCount && <span>{card.wordCount}</span>}
                {card.chapterCount !== undefined && <span>{card.chapterCount} 章</span>}
                {card.completed ? <span>已完结</span> : <span>连载中</span>}
              </div>
              {card.sourceSummary && (
                <p className="text-xs text-muted-foreground line-clamp-1">
                  {card.sourceSummary}
                </p>
              )}
              {card.alreadyIngested && card.addedBy && (
                <div className="flex items-center gap-1 text-xs text-muted-foreground">
                  <User className="w-3 h-3" />
                  <span>{card.addedBy}</span>
                </div>
              )}
              <div className="flex gap-2 pt-2">
                {card.alreadyIngested && card.aggregateBookId ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="flex-1"
                    onClick={() => navigate(`/console/library/${card.aggregateBookId}`)}
                  >
                    <Library className="w-3 h-3 mr-1" />
                    查看书库
                  </Button>
                ) : (
                  <Button
                    size="sm"
                    className="flex-1"
                    onClick={() => {
                      setSelectedCard(card)
                      setStartChapterIndex(1)
                      setAutoArchive(true)
                    }}
                  >
                    <Plus className="w-3 h-3 mr-1" />
                    订阅入库
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={!!selectedCard} onOpenChange={(open) => !open && setSelectedCard(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>订阅入库</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <p className="font-medium">{selectedCard?.name}</p>
              <p className="text-sm text-muted-foreground">{selectedCard?.author}</p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="startIndex">开始处理章节序号</Label>
              <Input
                id="startIndex"
                type="number"
                min={1}
                value={startChapterIndex}
                onChange={(e) => setStartChapterIndex(parseInt(e.target.value || "1", 10))}
              />
              <p className="text-xs text-muted-foreground">
                从该章节开始向后处理，之前的章节标记为占位。
              </p>
            </div>
            <div className="flex items-center justify-between">
              <Label htmlFor="autoArchive">完本自动归档</Label>
              <Switch id="autoArchive" checked={autoArchive} onCheckedChange={setAutoArchive} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSelectedCard(null)}>
              取消
            </Button>
            <Button
              onClick={() => selectedCard && subscribeMutation.mutate(selectedCard)}
              disabled={subscribeMutation.isPending}
            >
              {subscribeMutation.isPending && (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              )}
              <Check className="w-4 h-4 mr-2" />
              确认订阅
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
