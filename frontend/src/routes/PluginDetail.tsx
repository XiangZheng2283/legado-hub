import { useState } from "react"
import { useParams } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { ArrowLeft, Play, Power, Shield, Cookie, ExternalLink, Activity } from "lucide-react"
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

function parseCookieDraft(value: string, challenge: any) {
  let trimmed = value.trim()
  if (!trimmed) return null
  try {
    return JSON.parse(trimmed)
  } catch {
    const cookieLines = trimmed
      .replace(/\r\n/g, "\n")
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .flatMap((line) => {
        const lower = line.toLowerCase()
        if (lower.startsWith("cookie:")) return [line.slice(line.indexOf(":") + 1).trim()]
        if (lower.startsWith("set-cookie:")) return [line.slice(line.indexOf(":") + 1).split(";", 1)[0].trim()]
        return []
      })
    if (cookieLines.length) trimmed = cookieLines.join("; ")
    const domain = challenge.cookieDomains?.[0] || challenge.sourceId || ""
    const jar: Record<string, string> = {}
    trimmed.split(";").forEach((part) => {
      const index = part.indexOf("=")
      if (index <= 0) return
      const name = part.slice(0, index).trim()
      const cookieValue = part.slice(index + 1).trim()
      if (name) jar[name] = cookieValue
    })
    return Object.keys(jar).length ? { [domain]: jar } : null
  }
}

export function PluginDetail() {
  const { pluginId } = useParams<{ pluginId: string }>()
  const queryClient = useQueryClient()
  const [challengeActionResults, setChallengeActionResults] = useState<Record<string, string>>({})
  const [challengeRetryResults, setChallengeRetryResults] = useState<Record<string, any>>({})
  const [cookieDrafts, setCookieDrafts] = useState<Record<string, string>>({})

  const { data, isLoading } = useQuery({
    queryKey: ["plugin", pluginId],
    queryFn: () => api.plugin(pluginId!),
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

  const authMutation = useMutation({
    mutationFn: () => api.pluginAuth(pluginId!),
  })

  const loginMutation = useMutation({
    mutationFn: () => api.pluginLogin(pluginId!),
  })

  const clearCookiesMutation = useMutation({
    mutationFn: () => api.pluginCookiesClear(pluginId!),
  })

  const liveCheckMutation = useMutation({
    mutationFn: () => api.liveCheckPlugin(pluginId!, "剑宗外门"),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugin", pluginId] }),
  })

  const openBrowserMutation = useMutation({
    mutationFn: (challenge: any) => api.openBrowserChallengeBrowser(challenge.sessionId),
    onSuccess: (data, challenge) => {
      setChallengeActionResults((state) => ({
        ...state,
        [challenge.sessionId]: data.started ? data.message || "浏览器助手已启动" : data.error || "启动失败",
      }))
    },
  })

  const importCookiesMutation = useMutation({
    mutationFn: (challenge: any) => api.importBrowserChallengeCookies(challenge.sessionId),
    onSuccess: (data, challenge) => {
      const clearance = data.clearanceDomains?.length
        ? `cf_clearance: ${data.clearanceDomains.join(", ")}`
        : "未检测到 cf_clearance"
      setChallengeActionResults((state) => ({
        ...state,
        [challenge.sessionId]: data.saved ? `已导入浏览器 Cookie，可以重试验收。${clearance}` : data.error || "导入失败",
      }))
      queryClient.invalidateQueries({ queryKey: ["plugin", pluginId] })
    },
  })

  const saveCookiesMutation = useMutation({
    mutationFn: ({ challenge, value }: { challenge: any; value: string }) => {
      const parsed = parseCookieDraft(value, challenge)
      if (!parsed) throw new Error("未识别到有效 Cookie")
      return api.submitBrowserChallengeCookies(challenge.sessionId, parsed)
    },
    onSuccess: (data, variables) => {
      const clearance = data.clearanceDomains?.length
        ? `cf_clearance: ${data.clearanceDomains.join(", ")}`
        : "未检测到 cf_clearance"
      setChallengeActionResults((state) => ({
        ...state,
        [variables.challenge.sessionId]: data.saved ? `Cookie 已保存，可以重试验收。${clearance}` : data.error || "保存失败",
      }))
      queryClient.invalidateQueries({ queryKey: ["plugin", pluginId] })
    },
    onError: (error: any, variables) => {
      setChallengeActionResults((state) => ({
        ...state,
        [variables.challenge.sessionId]: error?.message || "保存失败",
      }))
    },
  })

  const retryChallengeMutation = useMutation({
    mutationFn: (challenge: any) => api.retryBrowserChallengeLiveCheck(challenge.sessionId, "剑宗外门"),
    onSuccess: (data, challenge) => {
      const result = data.retryResult || data
      setChallengeRetryResults((state) => ({ ...state, [challenge.sessionId]: result }))
      queryClient.invalidateQueries({ queryKey: ["plugin", pluginId] })
    },
  })

  if (isLoading) return <div className="text-muted-foreground">加载中...</div>
  if (!data || data.error) return <div className="text-destructive">插件不存在</div>

  const p = data
  const smokeResult = smokeMutation.data || p.health?.lastTestResult
  const authResult = authMutation.data
  const authChallenges = authResult?.browserChallenges || []
  const renderChallengePanel = (challenges: any[]) => (
    <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
      {challenges.map((challenge: any, index: number) => (
        <div key={challenge.sessionId || `${challenge.openUrl}-${index}`} className="space-y-2 rounded border border-amber-200 bg-background p-2">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div className="min-w-0">
              <div className="font-medium">{challenge.sourceName || challenge.reason || challenge.sourceId || "浏览器验证"}</div>
              <div className="truncate text-xs text-muted-foreground">{challenge.openUrl}</div>
              {challenge.sessionId && <div className="text-xs text-muted-foreground">会话 {challenge.sessionId}</div>}
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => window.open(challenge.openUrl, "_blank", "noopener,noreferrer")}
              >
                <ExternalLink className="h-4 w-4" />
                打开验证页
              </Button>
              {challenge.sessionId && (
                <>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={openBrowserMutation.isPending}
                    onClick={() => openBrowserMutation.mutate(challenge)}
                  >
                    启动浏览器助手
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={importCookiesMutation.isPending}
                    onClick={() => importCookiesMutation.mutate(challenge)}
                  >
                    导入 Cookie
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    disabled={saveCookiesMutation.isPending}
                    onClick={() =>
                      saveCookiesMutation.mutate({
                        challenge,
                        value: cookieDrafts[challenge.sessionId] || "",
                      })
                    }
                  >
                    保存 Cookie
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    disabled={retryChallengeMutation.isPending}
                    onClick={() => retryChallengeMutation.mutate(challenge)}
                  >
                    重试验收
                  </Button>
                </>
              )}
            </div>
          </div>
          {challenge.sessionId && (
            <textarea
              value={cookieDrafts[challenge.sessionId] || ""}
              onChange={(event) =>
                setCookieDrafts((state) => ({
                  ...state,
                  [challenge.sessionId]: event.target.value,
                }))
              }
              placeholder="粘贴 cookies JSON，或 cf_clearance=...; key=value"
              className="min-h-16 w-full rounded-md border bg-background px-3 py-2 text-xs outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring"
            />
          )}
          {challengeActionResults[challenge.sessionId] && (
            <div className="text-xs text-muted-foreground">{challengeActionResults[challenge.sessionId]}</div>
          )}
          {challengeRetryResults[challenge.sessionId] && (
            <div className="rounded border bg-muted/40 p-2 text-xs">
              <div className="font-medium">验收状态: {challengeRetryResults[challenge.sessionId].status || "unknown"}</div>
              <div className="text-muted-foreground">
                排行榜正文 {challengeRetryResults[challenge.sessionId].explore?.contentLength || 0} 字；
                搜索结果 {challengeRetryResults[challenge.sessionId].search?.count || 0}；
                目录 {challengeRetryResults[challenge.sessionId].toc?.count || 0} 章；
                正文 {challengeRetryResults[challenge.sessionId].chapter?.contentLength || 0} 字
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  )

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
        <Button
          variant="outline"
          size="sm"
          onClick={() => authMutation.mutate()}
        >
          <Shield className="w-4 h-4 mr-1" />
          认证状态
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => loginMutation.mutate()}
        >
          登录
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => clearCookiesMutation.mutate()}
        >
          <Cookie className="w-4 h-4 mr-1" />
          清除 Cookie
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={() => liveCheckMutation.mutate()}
          disabled={liveCheckMutation.isPending}
        >
          <Activity className="w-4 h-4 mr-1" />
          实时验收
        </Button>
      </div>

      <Tabs defaultValue="metadata">
        <TabsList>
          <TabsTrigger value="metadata">元数据</TabsTrigger>
          <TabsTrigger value="capabilities">能力</TabsTrigger>
          <TabsTrigger value="auth">认证</TabsTrigger>
          <TabsTrigger value="results">测试结果</TabsTrigger>
        </TabsList>

        <TabsContent value="metadata">
          <Card>
            <CardContent className="p-4 space-y-2 text-sm">
              <p><span className="text-muted-foreground">ID:</span> {p.pluginId}</p>
              <p><span className="text-muted-foreground">版本:</span> {p.version}</p>
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

        <TabsContent value="capabilities">
          <Card>
            <CardContent className="p-4">
              <div className="flex flex-wrap gap-2">
                {p.capabilities?.map((c: string) => (
                  <Badge key={c} variant="secondary">{c}</Badge>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="auth">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">认证状态</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <div className="grid gap-2 md:grid-cols-2">
                <p><span className="text-muted-foreground">模式:</span> {authResult?.mode || p.auth?.mode || "none"}</p>
                <p><span className="text-muted-foreground">已登录:</span> {authResult?.authenticated ? "是" : "否"}</p>
                <p><span className="text-muted-foreground">账号:</span> {authResult?.accountName || "-"}</p>
                <p><span className="text-muted-foreground">Cookie:</span> {authResult?.hasCookies ? "已保存" : "无"}</p>
                <p><span className="text-muted-foreground">验证:</span> {authResult?.verificationStatus || "-"}</p>
              </div>
              {authResult?.message && (
                <div className="rounded-md border bg-muted/40 p-2 text-xs text-muted-foreground">
                  {authResult.message}
                </div>
              )}
              {authResult?.requiredActions?.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {authResult.requiredActions.map((action: string) => (
                    <Badge key={action} variant="secondary">{action}</Badge>
                  ))}
                </div>
              )}
              {authChallenges.length > 0 && renderChallengePanel(authChallenges)}
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
          {liveCheckMutation.data && (
            <Card className="mt-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  实时验收结果
                  <Badge className="ml-2" variant={liveCheckMutation.data.passed ? "success" : "destructive"}>
                    {liveCheckMutation.data.status || (liveCheckMutation.data.passed ? "passed" : "failed")}
                  </Badge>
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="grid gap-2 md:grid-cols-2">
                  <p><span className="text-muted-foreground">排行榜书:</span> {liveCheckMutation.data.explore?.selected?.name || "-"}</p>
                  <p><span className="text-muted-foreground">搜索结果:</span> {liveCheckMutation.data.search?.count ?? 0}</p>
                  <p><span className="text-muted-foreground">目录:</span> {liveCheckMutation.data.toc?.count ?? 0} 章</p>
                  <p><span className="text-muted-foreground">正文:</span> {liveCheckMutation.data.chapter?.contentLength ?? 0} 字</p>
                </div>
                {(liveCheckMutation.data.browserChallenges || []).length > 0 &&
                  renderChallengePanel(liveCheckMutation.data.browserChallenges || [])}
                {(liveCheckMutation.data.diagnostics || []).length > 0 && (
                  <div className="space-y-2">
                    {(liveCheckMutation.data.diagnostics || []).slice(0, 3).map((item: any, index: number) => (
                      <div key={`${item.stage}-${index}`} className="rounded border border-destructive/30 p-2 text-xs">
                        <div className="font-medium">{item.stage || "runtime"} / {item.code || "error"}</div>
                        <div className="text-muted-foreground">{item.message}</div>
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}
          {loginMutation.data && (
            <Card className="mt-2">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">登录准备</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="text-xs bg-muted p-2 rounded overflow-auto">
                  {JSON.stringify(loginMutation.data, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}
          {clearCookiesMutation.data && (
            <Card className="mt-2">
              <CardContent className="p-4">
                <p className="text-sm">Cookie 已清除</p>
              </CardContent>
            </Card>
          )}
          {!smokeResult && !liveCheckMutation.data && !loginMutation.data && !clearCookiesMutation.data && (
            <Card>
              <CardContent className="p-8 text-center text-muted-foreground text-sm">
                点击上方按钮运行测试
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}
