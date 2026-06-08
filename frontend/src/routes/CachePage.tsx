import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { HardDrive, Trash2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"

export function CachePage() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ["cache"],
    queryFn: api.cache,
  })

  const clearMutation = useMutation({
    mutationFn: api.clearCache,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["cache"] }),
  })

  const stats = data || {}

  const items = [
    { label: "搜索缓存", value: stats.searchCache || 0 },
    { label: "书籍缓存", value: stats.bookCache || 0 },
    { label: "目录缓存", value: stats.tocCache || 0 },
    { label: "章节缓存", value: stats.chapterCache || 0 },
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">缓存</h1>
        <Button
          variant="destructive"
          size="sm"
          onClick={() => clearMutation.mutate()}
        >
          <Trash2 className="w-4 h-4 mr-1" />
          清空缓存
        </Button>
      </div>

      {isLoading ? (
        <div className="text-muted-foreground">加载中...</div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {items.map((item) => (
            <Card key={item.label}>
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-muted-foreground">{item.label}</p>
                    <p className="text-2xl font-semibold mt-1">{item.value}</p>
                  </div>
                  <HardDrive className="w-5 h-5 text-muted-foreground" />
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
