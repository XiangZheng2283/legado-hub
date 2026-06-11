import { useParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { ArrowLeft, Play, Power, Shield } from "lucide-react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"

const CAPABILITY_MAP: Record<string, string> = {
  search: "搜索",
  detail: "详情",
  toc: "目录",
  chapter: "正文",
  explore: "发现",
  auth: "认证",
}

function formatCapability(c: string): string {
  return CAPABILITY_MAP[c] || c
}

export function PluginDetail() {
  const { pluginId } = useParams<{ pluginId: string }>()
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ["plugin", pluginId],
    queryFn: () => api.plugin(pluginId!),
    enabled: !!pluginId,
  })

  const { data: attemptsData } = useQuery({
    queryKey: ["plugin-attempts", pluginId],
    queryFn: () => api.pluginAttempts(pluginId!),
    enabled: !!pluginId,
  })

  const enableMutation = useMutation({
    mutationFn: (enabled: boolean) => api.enablePlugin(pluginId!, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugin", pluginId] }),
  })

  const smokeMutation = useMutation({
    mutationFn: () => api.smokePlugin(pluginId!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugin", pluginId] }),
  })

  const loginMutation = useMutation({
    mutationFn: () => api.pluginLogin(pluginId!),
  })

  if (isLoading) return <div className="text-muted-foreground">加载中...</div>
  if (!data || data.error) return <div className="text-destructive">书源不存在</div>

  const p = data
  const smokeResult = smokeMutation.data || p.health?.lastTestResult
  const hasAuth = p.auth?.mode && p.auth.mode !== "none"
  const attempts = attemptsData?.attempts || []

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Link to="/console/plugins" className="text-muted-foreground hover:text-foreground">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <h1 className="text-xl font-semibold">{p.name}</h1>
        <Badge variant={p.enabled ? "success" : "outline"}>
          {p.enabled ? "启用" : "禁用"}
        </Badge>
      </div>

      <div className="flex flex-wrap gap-2">
        {p.capabilities?.map((c: string) => (
          <Badge key={c} variant="secondary" className="text-xs">
            {formatCapability(c)}
          </Badge>
        ))}
      </div>

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={() => enableMutation.mutate(!p.enabled)}
        >
          <Power className="w-4 h-4 mr-1" />
          {p.enabled ? "禁用" : "启用"}
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => smokeMutation.mutate()}
        >
          <Play className="w-4 h-4 mr-1" />
          冒烟测试
        </Button>
        {hasAuth && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => loginMutation.mutate()}
          >
            <Shield className="w-4 h-4 mr-1" />
            登录
          </Button>
        )}
      </div>

      <Tabs defaultValue="metadata">
        <TabsList>
          <TabsTrigger value="metadata">元数据</TabsTrigger>
          <TabsTrigger value="auth">认证</TabsTrigger>
          <TabsTrigger value="results">测试结果</TabsTrigger>
          <TabsTrigger value="logs">日志</TabsTrigger>
        </TabsList>

        <TabsContent value="metadata">
          <Card>
            <CardContent className="p-4 space-y-2 text-sm">
              <p><span className="text-muted-foreground">ID:</span> {p.pluginId}</p>
              <p><span className="text-muted-foreground">版本:</span> {p.version}</p>
              <p><span className="text-muted-foreground">修改时间:</span> {p.lastModified || "-"}</p>
              <p><span className="text-muted-foreground">域名:</span> {p.domains?.join(", ") || "-"}</p>
              <p><span className="text-muted-foreground">基础URL:</span> {p.baseUrls?.join(", ") || "-"}</p>
              <p><span className="text-muted-foreground">书源类型:</span> {p.accessType || p.sourceType || "HTTP"}</p>
              <p><span className="text-muted-foreground">代理:</span> {p.proxyRequired ? `需要 (${p.proxyMode || "auto"})` : "不需要"}</p>
              <p><span className="text-muted-foreground">浏览器:</span> {p.browser?.mode || "none"}</p>
              <p><span className="text-muted-foreground">标签:</span> {p.tags?.join(", ") || "-"}</p>
              <p><span className="text-muted-foreground">认证模式:</span> {p.auth?.mode || "none"}</p>
              <p><span className="text-muted-foreground">内容访问:</span> {p.content?.access || "unknown"}</p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="auth">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">认证配置</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="grid gap-2 md:grid-cols-2">
                <p><span className="text-muted-foreground">模式:</span> {p.auth?.mode || "none"}</p>
                <p><span className="text-muted-foreground">登录URL:</span> {p.auth?.loginUrl || "-"}</p>
                <p><span className="text-muted-foreground">Cookie域:</span> {p.auth?.cookieDomains?.join(", ") || "-"}</p>
                <p><span className="text-muted-foreground">验证URL:</span> {p.auth?.verificationUrl || "-"}</p>
              </div>
              {loginMutation.data && (
                <div className="mt-2 rounded-md border bg-muted/40 p-2">
                  <pre className="text-xs bg-muted p-2 rounded overflow-auto">
                    {JSON.stringify(loginMutation.data, null, 2)}
                  </pre>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="results">
          {smokeResult && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  冒烟测试结果
                  <Badge className="ml-2" variant={smokeResult.pass ? "success" : "destructive"}>
                    {smokeResult.pass ? "通过" : "失败"}
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>阶段</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>数量</TableHead>
                      <TableHead>耗时</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {Object.entries(smokeResult.stages || {}).map(([stage, value]: [string, any]) => (
                      <TableRow key={stage}>
                        <TableCell>{stage}</TableCell>
                        <TableCell>{value.status}</TableCell>
                        <TableCell>{value.count ?? value.contentLength ?? "-"}</TableCell>
                        <TableCell>{value.elapsedMs ?? 0}ms</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                {smokeResult.errors?.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {smokeResult.errors.map((error: any, index: number) => (
                      <div key={`${error.stage}-${index}`} className="rounded border border-destructive/30 p-2 text-xs">
                        <div className="font-medium">{error.code} / {error.stage}</div>
                        <div className="text-muted-foreground">{error.message}</div>
                        <div className="text-muted-foreground">{error.hint}</div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
          {!smokeResult && (
            <Card>
              <CardContent className="p-8 text-center text-muted-foreground text-sm">
                点击上方按钮运行测试
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="logs">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">活动日志</CardTitle>
            </CardHeader>
            <CardContent>
              {attempts.length === 0 ? (
                <p className="text-sm text-muted-foreground">暂无活动记录</p>
              ) : (
                <div className="space-y-3">
                  {attempts.map((a: any, i: number) => (
                    <div key={i} className="rounded border p-3 text-sm">
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <span className="text-xs text-muted-foreground whitespace-nowrap">{a.createdAt || "-"}</span>
                        <Badge variant="secondary" className="text-xs">{a.stage}</Badge>
                        {a.proxyUsed ? (
                          <Badge variant="outline" className="text-xs">代理</Badge>
                        ) : (
                          <Badge variant="secondary" className="text-xs">直连</Badge>
                        )}
                        <span className="text-xs text-muted-foreground">{a.directStatus}</span>
                        <span className="text-xs text-muted-foreground">{a.latencyMs}ms</span>
                        {a.error && <span className="text-xs text-destructive">{a.error}</span>}
                      </div>
                      {a.result ? (
                        <pre className="text-xs bg-muted p-2 rounded overflow-auto max-h-[200px]">
                          {(() => {
                            try {
                              const parsed = JSON.parse(a.result)
                              return JSON.stringify(parsed, null, 2)
                            } catch {
                              return a.result
                            }
                          })()}
                        </pre>
                      ) : (
                        <p className="text-xs text-muted-foreground">无返回内容</p>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
