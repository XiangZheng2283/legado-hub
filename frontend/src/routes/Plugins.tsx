import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Link } from "react-router-dom"
import { RefreshCw, Play, Power } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Card, CardContent } from "@/components/ui/card"

export function Plugins() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ["plugins"],
    queryFn: api.plugins,
  })

  const reloadMutation = useMutation({
    mutationFn: api.reloadPlugins,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugins"] }),
  })

  const enableMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) =>
      api.enablePlugin(id, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugins"] }),
  })

  const smokeMutation = useMutation({
    mutationFn: (id: string) => api.smokePlugin(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugins"] }),
  })

  const plugins = data?.items || []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">插件</h1>
        <Button
          size="sm"
          onClick={() => reloadMutation.mutate()}
          disabled={reloadMutation.isPending}
        >
          <RefreshCw className="w-4 h-4 mr-1" />
          重新加载
        </Button>
      </div>

      {isLoading ? (
        <div className="text-muted-foreground">加载中...</div>
      ) : plugins.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            暂无插件
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>名称</TableHead>
                  <TableHead>ID</TableHead>
                  <TableHead>能力</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>认证</TableHead>
                  <TableHead>Smoke</TableHead>
                  <TableHead>最近错误</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {plugins.map((p: any) => (
                  <TableRow key={p.pluginId}>
                    <TableCell>
                      <Link
                        to={`/console/plugins/${p.pluginId}`}
                        className="font-medium hover:text-primary"
                      >
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{p.pluginId}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {p.capabilities.map((c: string) => (
                          <Badge key={c} variant="secondary" className="text-xs">
                            {c}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.accessType === "Browser" ? "default" : "outline"} className="text-xs">
                        {p.accessType || p.sourceType || "HTTP"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {p.auth?.mode || "none"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={
                          p.health?.lastTestResult?.pass === true
                            ? "success"
                            : p.health?.lastTestResult?.pass === false
                              ? "destructive"
                              : "outline"
                        }
                      >
                        {p.health?.lastTestResult?.pass === true
                          ? "通过"
                          : p.health?.lastTestResult?.pass === false
                            ? "失败"
                            : "未运行"}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-48 truncate text-muted-foreground">
                      {p.health?.lastError || "-"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.enabled ? "success" : "outline"}>
                        {p.enabled ? "启用" : "禁用"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() =>
                            enableMutation.mutate({ id: p.pluginId, enabled: !p.enabled })
                          }
                        >
                          <Power className="w-3 h-3 mr-1" />
                          {p.enabled ? "禁用" : "启用"}
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={() => smokeMutation.mutate(p.pluginId)}
                        >
                          <Play className="w-3 h-3 mr-1" />
                          测试
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}

      {smokeMutation.data && (
        <Card>
          <CardContent className="p-4">
            <h3 className="text-sm font-semibold mb-2">
              冒烟测试结果: {smokeMutation.data.pluginId}
            </h3>
            <pre className="text-xs bg-muted p-2 rounded overflow-auto">
              {JSON.stringify(smokeMutation.data, null, 2)}
            </pre>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
