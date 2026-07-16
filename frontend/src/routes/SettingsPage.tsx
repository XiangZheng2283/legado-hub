import { useState, useEffect, useRef } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Save, RefreshCw, CheckCircle2, Loader2 } from "lucide-react"
import { api } from "@/lib/api"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Alert, AlertDescription } from "@/components/ui/alert"

const settingsCardClass = "border-slate-200 bg-white shadow-sm"
const settingsInputClass = "h-10 border-slate-200 bg-white shadow-none"
const settingsTabTriggerClass = "data-[state=active]:bg-white data-[state=active]:text-slate-950 data-[state=active]:shadow"

function secondsToMilliseconds(value: unknown, fallbackSeconds: number) {
  const seconds = Number(value ?? fallbackSeconds)
  return Number.isFinite(seconds) ? Math.round(seconds * 1000) : fallbackSeconds * 1000
}

function millisecondsToSeconds(value: string) {
  const milliseconds = Number(value)
  return Number.isFinite(milliseconds) ? milliseconds / 1000 : 0
}

function parseRecord(value: unknown): Record<string, any> {
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value)
      return parsed && typeof parsed === "object" ? parsed : {}
    } catch {
      return {}
    }
  }
  return value && typeof value === "object" ? value as Record<string, any> : {}
}

function SettingRow({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center justify-between py-4 border-b border-slate-100 last:border-0 gap-4">
      <div className="flex-1 pr-4">
        <h4 className="text-sm font-medium text-slate-900">{title}</h4>
        <p className="text-sm text-slate-500 mt-1">{description}</p>
      </div>
      <div className="sm:w-64 flex-shrink-0">{children}</div>
    </div>
  )
}

export function SettingsPage() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState("pool")
  const [isSaving, setIsSaving] = useState(false)
  const [isSaved, setIsSaved] = useState(false)
  const [hasChanges, setHasChanges] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordOk, setPasswordOk] = useState(false)

  const { data: settingsData, error: settingsError } = useQuery({ queryKey: ["settings"], queryFn: api.settings })
  const { data: aggData, error: aggError } = useQuery({ queryKey: ["aggregateSettings"], queryFn: api.aggregateSettings })
  const { data: lexiconData, error: lexiconError, refetch: refetchLexicon } = useQuery({ queryKey: ["lexiconStatus"], queryFn: api.lexiconStatus })

  const [editedSettings, setEditedSettings] = useState<Record<string, any> | null>(null)
  const [aggForm, setAggForm] = useState<Record<string, any> | null>(null)

  useEffect(() => {
    if (isSaved) {
      savedTimer.current = setTimeout(() => setIsSaved(false), 2000)
      return () => { if (savedTimer.current) clearTimeout(savedTimer.current) }
    }
  }, [isSaved])

  const local = editedSettings || settingsData || {}
  const sp = local.sourcePool || {}
  const agg = aggForm ?? aggData ?? {}
  const wf = parseRecord(agg.contentWorkflow)

  const setLocal = (patch: any) => {
    setHasChanges(true)
    setEditedSettings((previous) => ({ ...(previous ?? settingsData ?? {}), ...patch }))
  }
  const setAgg = (patch: any) => {
    setHasChanges(true)
    setAggForm((previous) => ({ ...(previous ?? aggData ?? {}), ...patch }))
  }

  const saveSettings = useMutation({
    mutationFn: api.updateSettings,
  })
  const saveAgg = useMutation({ mutationFn: api.updateAggregateSettings })

  const changePassword = useMutation({
    mutationFn: api.auth.changePassword,
    onSuccess: () => { setCurrentPassword(""); setNewPassword(""); setConfirmPassword(""); setPasswordError(null); setPasswordOk(true) },
    onError: (err: any) => { setPasswordError(err?.message || "修改失败") },
  })

  const updateLexicon = useMutation({ mutationFn: api.updateLexicon, onSuccess: () => refetchLexicon() })

  const handleSave = async () => {
    if (!hasChanges || isSaving) return
    setIsSaving(true)
    setSaveError(null)
    setIsSaved(false)
    try {
      // Both endpoints persist app_config.json. Keep the writes ordered and
      // exclude the workflow from the general payload so an older snapshot
      // cannot overwrite the aggregate settings.
      const invalidations: Promise<unknown>[] = []
      if (editedSettings) {
        const localPayload = { ...local }
        delete localPayload.contentWorkflow
        await saveSettings.mutateAsync(localPayload)
        invalidations.push(queryClient.invalidateQueries({ queryKey: ["settings"] }))
      }
      if (aggForm) {
        await saveAgg.mutateAsync(agg)
        invalidations.push(queryClient.invalidateQueries({ queryKey: ["aggregateSettings"] }))
      }
      await Promise.all(invalidations)
      setEditedSettings(null)
      setAggForm(null)
      setIsSaved(true)
      setHasChanges(false)
    } catch (error: any) {
      setSaveError(error?.message || "保存配置失败，请稍后重试。")
    } finally {
      setIsSaving(false)
    }
  }

  const handlePasswordSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    setPasswordError(null); setPasswordOk(false)
    if (!currentPassword || !newPassword) { setPasswordError("请输入当前密码和新密码"); return }
    if (newPassword !== confirmPassword) { setPasswordError("两次输入的新密码不一致"); return }
    changePassword.mutate({ currentPassword, newPassword })
  }

  return (
    <div className="space-y-6 max-w-4xl pb-24">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">系统设置</h1>
        <p className="mt-1 text-sm text-slate-500">配置 LegadoHub 的核心运行参数。</p>
      </div>

      {(settingsError || aggError || saveError) && (
        <Alert variant="destructive">
          <AlertDescription>
            {saveError || (settingsError as Error)?.message || (aggError as Error)?.message || "设置加载失败，请刷新后重试。"}
          </AlertDescription>
        </Alert>
      )}

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="mb-4 flex-wrap h-auto gap-2 p-2 w-full justify-start overflow-x-auto bg-slate-100 text-slate-500">
          <TabsTrigger className={settingsTabTriggerClass} value="security">账户安全</TabsTrigger>
          <TabsTrigger className={settingsTabTriggerClass} value="pool">书源池</TabsTrigger>
          <TabsTrigger className={settingsTabTriggerClass} value="agg">聚合策略</TabsTrigger>
          <TabsTrigger className={settingsTabTriggerClass} value="priority">优先级</TabsTrigger>
          <TabsTrigger className={settingsTabTriggerClass} value="dict">词库</TabsTrigger>
        </TabsList>

        <TabsContent value="security">
          <Card>
            <CardHeader><CardTitle>修改密码</CardTitle><CardDescription>定期修改密码有助于保护您的账户安全。</CardDescription></CardHeader>
            <CardContent>
              <form onSubmit={handlePasswordSubmit} className="space-y-4">
                <div className="space-y-2 max-w-md">
                  <Label htmlFor="current-password">当前密码</Label>
                  <Input id="current-password" autoComplete="current-password" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} />
                </div>
                <div className="space-y-2 max-w-md">
                  <Label htmlFor="new-password">新密码</Label>
                  <Input id="new-password" autoComplete="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} />
                </div>
                <div className="space-y-2 max-w-md">
                  <Label htmlFor="confirm-password">确认新密码</Label>
                  <Input id="confirm-password" autoComplete="new-password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} />
                </div>
                {passwordError && <Alert variant="destructive"><AlertDescription>{passwordError}</AlertDescription></Alert>}
                {passwordOk && <Alert><AlertDescription>密码已修改。</AlertDescription></Alert>}
                <div className="pt-2">
                  <Button type="submit" variant="secondary" disabled={changePassword.isPending}>
                    {changePassword.isPending ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : null}
                    更新密码
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="pool">
          <Card className={settingsCardClass}>
            <CardHeader><CardTitle>并发与超时</CardTitle><CardDescription>控制搜索和解析时的并发数量与超时熔断时间。</CardDescription></CardHeader>
            <CardContent>
              <SettingRow title="最大并发搜索数" description="同时向多少个书源发起搜索请求。过高可能导致内存溢出。"><Input className={settingsInputClass} type="number" value={sp.max_concurrency || 3} onChange={(e) => setLocal({ sourcePool: { ...sp, max_concurrency: +e.target.value } })} /></SettingRow>
              <SettingRow title="单源超时 (ms)" description="等待一个普通源响应的最长时间。"><Input className={settingsInputClass} type="number" value={secondsToMilliseconds(sp.source_timeout_seconds, 20)} onChange={(e) => setLocal({ sourcePool: { ...sp, source_timeout_seconds: millisecondsToSeconds(e.target.value) } })} /></SettingRow>
              <SettingRow title="浏览器模式搜索超时 (ms)" description="等待 Headless 浏览器搜索结果。"><Input className={settingsInputClass} type="number" value={secondsToMilliseconds(sp.browser_search_timeout_seconds, 60)} onChange={(e) => setLocal({ sourcePool: { ...sp, browser_search_timeout_seconds: millisecondsToSeconds(e.target.value) } })} /></SettingRow>
              <SettingRow title="搜索评分过滤" description="低于此分数的搜索结果会被直接丢弃。"><Input className={settingsInputClass} type="number" value={local.searchScoreFilter ?? 40} onChange={(e) => setLocal({ searchScoreFilter: +e.target.value })} /></SettingRow>
            </CardContent>
          </Card>
          <Card className={`mt-6 ${settingsCardClass}`}>
            <CardHeader><CardTitle>网络代理与标识</CardTitle></CardHeader>
            <CardContent>
              <SettingRow title="默认 User-Agent" description="向第三方书源发起 HTTP 请求时使用的标识。"><Input className={settingsInputClass} value={sp.default_user_agent || ""} onChange={(e) => setLocal({ sourcePool: { ...sp, default_user_agent: e.target.value } })} /></SettingRow>
              <SettingRow title="代理 URL (Proxy)" description="配置 HTTP/SOCKS 代理用于访问受限书源。"><Input className={settingsInputClass} value={sp.proxy?.url || ""} onChange={(e) => setLocal({ sourcePool: { ...sp, proxy: { ...(sp.proxy || {}), url: e.target.value } } })} /></SettingRow>
              <SettingRow title="官方源参与普通搜索" description="是否在常规聚合搜索中包含官方书源。">
                <div className="flex items-center gap-2">
                  <Switch checked={sp.officialSourceInNormalSearch || false} onCheckedChange={(c) => setLocal({ sourcePool: { ...sp, officialSourceInNormalSearch: c } })} />
                  <span className="text-sm text-slate-600">启用</span>
                </div>
              </SettingRow>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="agg">
          <Card>
            <CardHeader><CardTitle>聚合策略</CardTitle><CardDescription>配置候选源数量、检查间隔和源优先级。</CardDescription></CardHeader>
            <CardContent>
              <SettingRow title="候选书源数量" description="为每本书保留最多几个高质量备选源用于容灾。"><Input type="number" value={wf.sourceCandidateLimit || 6} onChange={(e) => setAgg({ contentWorkflow: { ...wf, sourceCandidateLimit: +e.target.value } })} /></SettingRow>
              <SettingRow title="自动更新间隔(分钟)" description="后台自动检查书籍更新的频率。"><Input type="number" value={wf.aggregateCheckIntervalMinutes ?? 30} onChange={(e) => setAgg({ contentWorkflow: { ...wf, aggregateCheckIntervalMinutes: +e.target.value } })} /></SettingRow>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="priority">
          <div className="grid md:grid-cols-2 gap-6">
            <Card>
              <CardHeader className="pb-3 border-b border-slate-100">
                <CardTitle className="text-base">官方主源优先级</CardTitle>
                <CardDescription>用于目录对齐和元数据抓取，每行一个源 ID。</CardDescription>
              </CardHeader>
              <CardContent className="p-4">
                <textarea
                  aria-label="官方主源优先级"
                  className="min-h-32 w-full rounded-md border border-slate-200 bg-white p-3 text-sm font-mono"
                  value={Array.isArray(wf.primarySourcePriority) ? wf.primarySourcePriority.join("\n") : ""}
                  onChange={(e) => setAgg({ contentWorkflow: { ...wf, primarySourcePriority: e.target.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean) } })}
                />
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3 border-b border-slate-100">
                <CardTitle className="text-base">补全源优先级</CardTitle>
                <CardDescription>VIP或错误章节的替补内容来源，每行一个源 ID。</CardDescription>
              </CardHeader>
              <CardContent className="p-4">
                <textarea
                  aria-label="补全源优先级"
                  className="min-h-32 w-full rounded-md border border-slate-200 bg-white p-3 text-sm font-mono"
                  value={Array.isArray(wf.candidateSourcePriority) ? wf.candidateSourcePriority.join("\n") : ""}
                  onChange={(e) => setAgg({ contentWorkflow: { ...wf, candidateSourcePriority: e.target.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean) } })}
                />
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="dict">
          <Card>
            <CardHeader><CardTitle>净化词库管理</CardTitle><CardDescription>用于修复乱码、屏蔽词和谐以及统一内容格式。</CardDescription></CardHeader>
            <CardContent>
                <div className="bg-slate-50 p-4 rounded-lg mt-2 border border-slate-100">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
                  <div>
                    <h4 className="text-sm font-bold text-slate-800">当前词库状态</h4>
                    {lexiconData?.commitSha && <p className="text-xs text-slate-500 mt-1 font-mono">Commit: {lexiconData.commitSha.slice(0, 7)}</p>}
                  </div>
                  <Button variant="outline" size="sm" className="bg-white" onClick={() => updateLexicon.mutate()} disabled={updateLexicon.isPending}>
                    {updateLexicon.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
                    <RefreshCw className="h-4 w-4 mr-2" /> 强制同步
                  </Button>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 py-4 border-t border-slate-200">
                  <div><div className="text-xs text-slate-400">版本</div><div className="text-sm font-medium text-slate-800 mt-0.5">{lexiconData?.commitSha ? lexiconData.commitSha.slice(0, 7) : "未安装"}</div></div>
                  <div><div className="text-xs text-slate-400">规则文件数</div><div className="text-sm font-medium text-slate-800 mt-0.5">{lexiconData?.fileCount ?? "-"}</div></div>
                  <div><div className="text-xs text-slate-400">词条总数</div><div className="text-sm font-medium text-slate-800 mt-0.5">{lexiconData?.wordCount ?? "-"}</div></div>
                  <div><div className="text-xs text-slate-400">最后更新</div><div className="text-sm font-medium text-slate-800 mt-0.5">{lexiconData?.updatedAt ? new Date(lexiconData.updatedAt).toLocaleString() : "-"}</div></div>
                </div>
                {lexiconError && <p className="mt-3 text-sm text-rose-600">词库状态加载失败：{(lexiconError as Error).message}</p>}
                {updateLexicon.error && <p className="mt-3 text-sm text-rose-600">词库同步失败：{(updateLexicon.error as Error).message}</p>}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <div className="fixed bottom-0 left-0 right-0 md:left-64 p-4 bg-white/80 backdrop-blur-md border-t border-slate-200 flex justify-end z-20">
        <div className="max-w-4xl w-full mx-auto flex justify-end gap-3 items-center px-4 md:px-0">
          {isSaved && <span className="text-sm text-emerald-600 flex items-center"><CheckCircle2 className="h-4 w-4 mr-1.5" /> 已保存</span>}
          <Button onClick={handleSave} disabled={!hasChanges || isSaving} className={`min-w-[120px] ${hasChanges ? "bg-blue-600 shadow-md hover:bg-blue-700" : "bg-slate-800"}`}>
            {isSaving ? <><Loader2 className="h-4 w-4 mr-2 animate-spin" /> 保存中</> : <><Save className="h-4 w-4 mr-2" /> 保存配置</>}
          </Button>
        </div>
      </div>
    </div>
  )
}
