import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Play } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

export function VerificationPage() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ["verification"],
    queryFn: api.verification,
  })

  const runMutation = useMutation({
    mutationFn: api.runVerification,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["verification"] }),
  })

  const archived = data?.archived

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">验证中心</h1>
        <Button
          size="sm"
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending}
        >
          <Play className="w-4 h-4 mr-1" />
          运行验证
        </Button>
      </div>

      {archived && (
        <Card className="border-yellow-200 bg-yellow-50">
          <CardContent className="p-4 text-sm text-yellow-800">
            旧验证框架已归档。当前使用插件运行时自检。
          </CardContent>
        </Card>
      )}

      {isLoading ? (
        <div className="text-muted-foreground">加载中...</div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground">插件总数</div>
                <div className="text-2xl font-semibold">{data?.summary?.total ?? 0}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground">Smoke 通过</div>
                <div className="text-2xl font-semibold">{data?.summary?.passed ?? 0}</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <div className="text-xs text-muted-foreground">Smoke 失败</div>
                <div className="text-2xl font-semibold">{data?.summary?.failed ?? 0}</div>
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Reading API Loop</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-2 text-xs md:grid-cols-2">
              {Object.entries(data?.readingLoop || {}).map(([key, value]) => (
                <div key={key} className="rounded border p-2">
                  <div className="font-medium">{key}</div>
                  <div className="text-muted-foreground break-all">{String(value)}</div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">插件检查</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>插件</TableHead>
                    <TableHead>Fixture</TableHead>
                    <TableHead>Smoke</TableHead>
                    <TableHead>认证</TableHead>
                    <TableHead>错误</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data?.items || []).map((item: any) => (
                    <TableRow key={item.pluginId}>
                      <TableCell>{item.name}<div className="text-xs text-muted-foreground">{item.pluginId}</div></TableCell>
                      <TableCell>{item.hasFixtureSmoke ? "存在" : "缺失"}</TableCell>
                      <TableCell>
                        <Badge variant={item.lastSmokePass === true ? "success" : item.lastSmokePass === false ? "destructive" : "outline"}>
                          {item.lastSmokePass === true ? "通过" : item.lastSmokePass === false ? "失败" : "未运行"}
                        </Badge>
                      </TableCell>
                      <TableCell>{item.authMode || "none"}</TableCell>
                      <TableCell className="max-w-64 truncate text-muted-foreground">{item.lastError || "-"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  )
}
