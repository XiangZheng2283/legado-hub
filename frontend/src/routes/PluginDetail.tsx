import { useNavigate, useParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api, apiErrorMessage } from "@/lib/api"
import {
  Activity,
  ArrowLeft,
  Power,
  Puzzle,
  Shield,
} from "lucide-react"
import { Link } from "react-router-dom"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Alert, AlertDescription } from "@/components/ui/alert"

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

function MetaItem({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-medium">{value}</div>
    </div>
  )
}

export function PluginDetail() {
  const { pluginId } = useParams<{ pluginId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data, isLoading, error: pluginError, refetch: refetchPlugin } = useQuery({
    queryKey: ["plugin", pluginId],
    queryFn: () => api.plugin(pluginId!),
    enabled: !!pluginId,
  })

  const { data: attemptsData, error: attemptsError, refetch: refetchAttempts } = useQuery({
    queryKey: ["plugin-attempts", pluginId],
    queryFn: () => api.pluginAttempts(pluginId!),
    enabled: !!pluginId,
  })

  const enableMutation = useMutation({
    mutationFn: (enabled: boolean) => api.enablePlugin(pluginId!, enabled),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugin", pluginId] }),
  })

  const pingMutation = useMutation({
    mutationFn: () => api.pingPlugin(pluginId!),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["plugin", pluginId] }),
        queryClient.invalidateQueries({ queryKey: ["plugin-attempts", pluginId] }),
      ])
    },
  })

  if (isLoading) {
    return (
      <div className="flex min-h-[300px] items-center justify-center text-muted-foreground">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    )
  }

  if (pluginError) {
    return (
      <Alert variant="destructive">
        <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
          <span>书源加载失败：{apiErrorMessage(pluginError, "请稍后重试。")}</span>
          <Button type="button" size="sm" variant="outline" onClick={() => { void refetchPlugin() }}>重试</Button>
        </AlertDescription>
      </Alert>
    )
  }
  if (!data || data.error) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border py-16 text-center">
        <p className="text-base font-semibold">书源不存在或已删除</p>
        <Button variant="outline" size="sm" className="mt-4" asChild>
          <Link to="/console/plugins">
            <ArrowLeft className="mr-1.5 h-4 w-4" />
            返回书源列表
          </Link>
        </Button>
      </div>
    )
  }

  const p = data
  const hasAuth = p.auth?.mode && p.auth.mode !== "none"
  const attempts = attemptsData?.attempts || []

  return (
    <div className="space-y-5">
      {(enableMutation.error || pingMutation.error || attemptsError) && (
        <Alert variant="destructive">
          <AlertDescription className="flex flex-wrap items-center justify-between gap-3">
            <span>{apiErrorMessage(enableMutation.error || pingMutation.error || attemptsError, "书源操作失败，请稍后重试。")}</span>
            {attemptsError && (
              <Button type="button" size="sm" variant="outline" onClick={() => { void refetchAttempts() }}>
                重试记录
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <button
            type="button"
            onClick={() => navigate("/console/plugins")}
            className="inline-flex items-center gap-1.5 rounded-xl bg-card/80 px-3 py-1.5 text-sm text-muted-foreground shadow-sm backdrop-blur hover:text-foreground hover:bg-card transition-colors"
          >
            <ArrowLeft className="h-4 w-4" />
            返回书源列表
          </button>
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
              <Puzzle className="h-5 w-5 text-primary" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-foreground">{p.name}</h1>
                <Badge variant={p.enabled ? "success" : "outline"}>
                  {p.enabled ? "启用" : "禁用"}
                </Badge>
              </div>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {p.capabilities?.map((c: string) => (
                  <Badge key={c} variant="secondary" className="text-xs">
                    {formatCapability(c)}
                  </Badge>
                ))}
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant={p.enabled ? "outline" : "default"}
            onClick={() => enableMutation.mutate(!p.enabled)}
            disabled={enableMutation.isPending}
          >
            <Power className="w-4 h-4 mr-1.5" />
            {p.enabled ? "禁用" : "启用"}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => pingMutation.mutate()}
            disabled={pingMutation.isPending}
          >
            {pingMutation.isPending ? (
              <div className="mr-1.5 h-4 w-4 animate-spin rounded-full border-2 border-primary border-t-transparent" />
            ) : (
              <Activity className="w-4 h-4 mr-1.5" />
            )}
            Ping 检测
          </Button>
          {hasAuth && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigate("/console/official-sources")}
            >
              <Shield className="w-4 h-4 mr-1.5" />
              官方源管理
            </Button>
          )}
        </div>
      </div>

      <Tabs defaultValue="metadata">
        <TabsList>
          <TabsTrigger value="metadata">元数据</TabsTrigger>
          <TabsTrigger value="auth">认证</TabsTrigger>
          <TabsTrigger value="logs">日志</TabsTrigger>
        </TabsList>

        <TabsContent value="metadata" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">基础信息</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 text-sm md:grid-cols-2">
                <MetaItem label="ID" value={p.pluginId} />
                <MetaItem label="版本" value={p.version || "-"} />
                <MetaItem label="作者" value={p.author || "-"} />
                <MetaItem label="修改时间" value={p.lastModified || "-"} />
                <MetaItem label="书源类型" value={p.accessType || p.sourceType || "HTTP"} />
                <MetaItem label="域名" value={p.domains?.join(", ") || "-"} />
                <MetaItem label="基础 URL" value={p.baseUrls?.join(", ") || "-"} />
                <MetaItem label="代理" value={p.proxyRequired ? `需要 (${p.proxyMode || "auto"})` : "不需要"} />
                <MetaItem label="浏览器模式" value={p.browser?.mode || "none"} />
                <MetaItem label="标签" value={p.tags?.join(", ") || "-"} />
                <MetaItem label="认证模式" value={p.auth?.mode || "none"} />
                <MetaItem label="内容访问" value={p.content?.access || "unknown"} />
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">运行时状态</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 text-sm md:grid-cols-2">
                <MetaItem
                  label="最近 Ping"
                  value={
                    p.health?.pingStatus === "reachable" ? (
                      <span className="text-primary">可达 {p.health.pingLatencyMs}ms</span>
                    ) : p.health?.pingStatus === "unreachable" ? (
                      <span className="text-destructive">不可达</span>
                    ) : (
                      "-"
                    )
                  }
                />
                <MetaItem
                  label="最近错误"
                  value={
                    p.health?.lastError ? (
                      <span className="text-destructive">{p.health.lastError}</span>
                    ) : (
                      "-"
                    )
                  }
                />
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="auth">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">认证配置</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid gap-3 text-sm md:grid-cols-2">
                <MetaItem label="模式" value={p.auth?.mode || "none"} />
                <MetaItem label="登录 URL" value={p.auth?.loginUrl || "-"} />
                <MetaItem label="Cookie 域" value={p.auth?.cookieDomains?.join(", ") || "-"} />
                <MetaItem label="验证 URL" value={p.auth?.verificationUrl || "-"} />
              </div>
            </CardContent>
          </Card>
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
                        <span className="text-xs text-muted-foreground whitespace-nowrap">
                          {a.timestamp ? new Date(a.timestamp).toLocaleString() : "-"}
                        </span>
                        <Badge variant="secondary" className="text-xs">{a.type}</Badge>
                        {a.type === "ping" && (
                          <Badge variant={a.status === "reachable" ? "success" : "destructive"} className="text-xs">
                            {a.status}
                          </Badge>
                        )}
                        {typeof a.latencyMs === "number" && a.latencyMs > 0 && (
                          <span className="text-xs text-muted-foreground">{a.latencyMs}ms</span>
                        )}
                        {a.proxyUsed && <Badge variant="outline" className="text-xs">代理</Badge>}
                        {a.error && <span className="text-xs text-destructive">{a.error}</span>}
                      </div>
                      {a.url && <div className="text-xs text-muted-foreground mb-1">{a.url}</div>}
                      {a.message && <div className="text-xs text-muted-foreground mb-1">{a.message}</div>}
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
