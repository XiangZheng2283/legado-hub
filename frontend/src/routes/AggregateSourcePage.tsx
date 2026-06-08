import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { RefreshCw } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

export function AggregateSourcePage() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ["aggregate-source"],
    queryFn: api.aggregateSource,
  })

  const regenerateMutation = useMutation({
    mutationFn: api.regenerateAggregateSource,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["aggregate-source"] }),
  })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">聚合书源</h1>
        <Button
          size="sm"
          onClick={() => regenerateMutation.mutate()}
          disabled={regenerateMutation.isPending}
        >
          <RefreshCw className="w-4 h-4 mr-1" />
          重新生成
        </Button>
      </div>

      {isLoading ? (
        <div className="text-muted-foreground">加载中...</div>
      ) : (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">配置</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground space-y-1">
              <p>名称: {data?.name || "-"}</p>
              <p>版本: {data?.version || "-"}</p>
              <p>组: {data?.group || "-"}</p>
              <p>生成路径: {data?.generated_path || "-"}</p>
              <p>最后生成: {data?.last_generated_at || "-"}</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">进度</CardTitle>
            </CardHeader>
            <CardContent>
              <pre className="text-xs bg-muted p-2 rounded overflow-auto">
                {JSON.stringify(data?.parser_progress || {}, null, 2)}
              </pre>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
