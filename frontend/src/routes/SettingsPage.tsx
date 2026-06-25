import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import {
  Bot, Save, ShieldCheck, Wand2, Zap, RefreshCw, X, Plus,
  Loader2, CheckCircle2, XCircle, ChevronUp, ChevronDown,
} from "lucide-react"
import { useState, useEffect, type FormEvent } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription } from "@/components/ui/alert"
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select"

// ── provider presets with plans ─────────────────────────────────────────────

const PROVIDER_PRESETS = [
  // DeepSeek
  { id: "deepseek", name: "DeepSeek", baseUrl: "https://api.deepseek.com/v1", plan: "" },
  { id: "deepseek-coder", name: "DeepSeek Coder", baseUrl: "https://api.deepseek.com/v1", plan: "coder" },
  // OpenAI
  { id: "openai", name: "OpenAI", baseUrl: "https://api.openai.com/v1", plan: "" },
  { id: "openai-azure", name: "OpenAI Azure", baseUrl: "https://YOUR_RESOURCE.openai.azure.com/openai", plan: "azure" },
  // Anthropic
  { id: "anthropic", name: "Anthropic (Claude)", baseUrl: "https://api.anthropic.com/v1", plan: "" },
  // Moonshot / Kimi
  { id: "moonshot", name: "Moonshot / Kimi", baseUrl: "https://api.moonshot.cn/v1", plan: "" },
  { id: "moonshot-explorer", name: "Moonshot 探索版", baseUrl: "https://api.moonshot.cn/v1", plan: "explorer" },
  { id: "moonshot-pro", name: "Moonshot 旗舰版", baseUrl: "https://api.moonshot.cn/v1", plan: "pro" },
  // 硅基流动
  { id: "siliconflow", name: "硅基流动 SiliconFlow", baseUrl: "https://api.siliconflow.cn/v1", plan: "" },
  { id: "siliconflow-pro", name: "硅基流动 Pro", baseUrl: "https://api.siliconflow.cn/v1", plan: "pro" },
  // 通义千问
  { id: "qwen", name: "通义千问 (DashScope)", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", plan: "" },
  { id: "qwen-turbo", name: "千问 Turbo 套餐", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", plan: "turbo" },
  { id: "qwen-plus", name: "千问 Plus 套餐", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", plan: "plus" },
  { id: "qwen-max", name: "千问 Max 套餐", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1", plan: "max" },
  // 智谱 GLM
  { id: "zhipu", name: "智谱 GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4", plan: "" },
  { id: "zhipu-flash", name: "智谱 Flash 免费", baseUrl: "https://open.bigmodel.cn/api/paas/v4", plan: "flash" },
  { id: "zhipu-air", name: "智谱 Air", baseUrl: "https://open.bigmodel.cn/api/paas/v4", plan: "air" },
  { id: "zhipu-pro", name: "智谱 Pro", baseUrl: "https://open.bigmodel.cn/api/paas/v4", plan: "pro" },
  // MiniMax
  { id: "minimax", name: "MiniMax", baseUrl: "https://api.minimax.chat/v1", plan: "" },
  { id: "minimax-abab7", name: "MiniMax abab7", baseUrl: "https://api.minimax.chat/v1", plan: "abab7" },
  // Mistral
  { id: "mistral", name: "Mistral AI", baseUrl: "https://api.mistral.ai/v1", plan: "" },
  { id: "mistral-free", name: "Mistral 免费 (Le Chat)", baseUrl: "https://api.mistral.ai/v1", plan: "free" },
  { id: "mistral-pro", name: "Mistral Pro", baseUrl: "https://api.mistral.ai/v1", plan: "pro" },
  // OpenRouter
  { id: "openrouter", name: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1", plan: "" },
  { id: "openrouter-free", name: "OpenRouter 免费模型", baseUrl: "https://openrouter.ai/api/v1", plan: "free" },
  // 百川
  { id: "baichuan", name: "百川大模型", baseUrl: "https://api.baichuan-ai.com/v1", plan: "" },
  { id: "baichuan-turbo", name: "百川 Turbo", baseUrl: "https://api.baichuan-ai.com/v1", plan: "turbo" },
  // 讯飞星火
  { id: "spark", name: "讯飞星火", baseUrl: "https://spark-api-open.xf-yun.com/v1", plan: "" },
  { id: "spark-pro", name: "星火 Pro", baseUrl: "https://spark-api-open.xf-yun.com/v1", plan: "pro" },
  { id: "spark-max", name: "星火 Max", baseUrl: "https://spark-api-open.xf-yun.com/v1", plan: "max" },
  { id: "spark-ultra", name: "星火 Ultra 4.0", baseUrl: "https://spark-api-open.xf-yun.com/v1", plan: "ultra" },
  // 豆包
  { id: "doubao", name: "字节豆包", baseUrl: "https://ark.cn-beijing.volces.com/api/v3", plan: "" },
  { id: "doubao-lite", name: "豆包 Lite", baseUrl: "https://ark.cn-beijing.volces.com/api/v3", plan: "lite" },
  { id: "doubao-pro", name: "豆包 Pro", baseUrl: "https://ark.cn-beijing.volces.com/api/v3", plan: "pro" },
  // 零一万物
  { id: "yi", name: "零一万物 Yi", baseUrl: "https://api.lingyiwanwu.com/v1", plan: "" },
  { id: "yi-spark", name: "Yi Spark", baseUrl: "https://api.lingyiwanwu.com/v1", plan: "spark" },
  { id: "yi-large", name: "Yi Large", baseUrl: "https://api.lingyiwanwu.com/v1", plan: "large" },
  // 阶跃星辰
  { id: "stepfun", name: "阶跃星辰 Step", baseUrl: "https://api.stepfun.com/v1", plan: "" },
  { id: "stepfun-pro", name: "Step Pro", baseUrl: "https://api.stepfun.com/v1", plan: "pro" },
  // 腾讯混元
  { id: "hunyuan", name: "腾讯混元", baseUrl: "https://api.hunyuan.cloud.tencent.com/v1", plan: "" },
  { id: "hunyuan-pro", name: "混元 Pro", baseUrl: "https://api.hunyuan.cloud.tencent.com/v1", plan: "pro" },
  { id: "hunyuan-standard", name: "混元 Standard", baseUrl: "https://api.hunyuan.cloud.tencent.com/v1", plan: "standard" },
  // 天工
  { id: "tiangong", name: "昆仑万维 天工", baseUrl: "https://api.tiangong.cn/v1", plan: "" },
  // 商汤
  { id: "sensechat", name: "商汤日日新", baseUrl: "https://api.sensenova.cn/v1", plan: "" },
  // 小米
  { id: "mimo", name: "小米 MiMo", baseUrl: "https://api.xiaomimimo.com/v1", plan: "" },
  { id: "mimo-token-plan", name: "MiMo Token Plan 套餐", baseUrl: "https://token-plan-cn.xiaomimimo.com/v1", plan: "token-plan" },
  // Groq
  { id: "groq", name: "Groq", baseUrl: "https://api.groq.com/openai/v1", plan: "" },
  // Together
  { id: "together", name: "Together AI", baseUrl: "https://api.together.xyz/v1", plan: "" },
  // NVIDIA
  { id: "nvidia", name: "NVIDIA NIM", baseUrl: "https://integrate.api.nvidia.com/v1", plan: "" },
  // 本地
  { id: "ollama", name: "Ollama (本地)", baseUrl: "http://localhost:11434/v1", plan: "" },
  { id: "lmstudio", name: "LM Studio (本地)", baseUrl: "http://localhost:1234/v1", plan: "" },
  // 自定义
  { id: "custom", name: "自定义", baseUrl: "", plan: "" },
] as const

function parseSettingObject(value: any) {
  if (!value) return {}
  if (typeof value !== "string") return value
  try {
    const parsed = JSON.parse(value)
    return parsed && typeof parsed === "object" ? parsed : {}
  } catch {
    return {}
  }
}

export function SettingsPage() {
  const queryClient = useQueryClient()

  // Generic settings
  const { data: settingsData, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
  })
  // Aggregate settings (separate API)
  const { data: aggData } = useQuery({
    queryKey: ["aggregateSettings"],
    queryFn: api.aggregateSettings,
  })
  // Plugins list for source selector
  const { data: pluginsData } = useQuery({
    queryKey: ["plugins"],
    queryFn: api.plugins,
  })

  const [editedSettings, setEditedSettings] = useState<Record<string, any> | null>(null)
  const [aggForm, setAggForm] = useState<Record<string, any> | null>(null)
  const [saved, setSaved] = useState(false)
  const [testResult, setTestResult] = useState<any>(null)
  const [testing, setTesting] = useState(false)
  const [fetchingModels, setFetchingModels] = useState(false)
  const [selectedPreset, setSelectedPreset] = useState("custom")
  const [sourceDropdownOpen, setSourceDropdownOpen] = useState(false)
  const [currentPassword, setCurrentPassword] = useState("")
  const [newPassword, setNewPassword] = useState("")
  const [confirmPassword, setConfirmPassword] = useState("")
  const [passwordError, setPasswordError] = useState<string | null>(null)
  const [passwordOk, setPasswordOk] = useState(false)

  useEffect(() => {
    if (aggData && aggForm === null) {
      setAggForm(aggData)
      const url = aggData?.aiProviderConfig?.baseUrl || ""
      const match = PROVIDER_PRESETS.find((p) => p.baseUrl && url.startsWith(p.baseUrl))
      if (match) setSelectedPreset(match.id)
    }
  }, [aggData])

  useEffect(() => {
    if (!saved) return
    const t = setTimeout(() => setSaved(false), 2000)
    return () => clearTimeout(t)
  }, [saved])

  const saveSettings = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      setSaved(true)
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })
  const saveAgg = useMutation({
    mutationFn: api.updateAggregateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aggregateSettings"] })
    },
  })
  const changePassword = useMutation({
    mutationFn: api.auth.changePassword,
    onSuccess: () => {
      setCurrentPassword("")
      setNewPassword("")
      setConfirmPassword("")
      setPasswordError(null)
      setPasswordOk(true)
    },
    onError: (err: any) => {
      setPasswordOk(false)
      setPasswordError(err?.message || "修改密码失败")
    },
  })

  const handleSaveAll = async () => {
    await Promise.all([
      saveSettings.mutateAsync(local),
      saveAgg.mutateAsync(agg),
    ])
    setSaved(true)
  }

  const handleTestProvider = async () => {
    setTesting(true); setTestResult(null)
    try {
      const p = agg?.aiProviderConfig || {}
      setTestResult(await api.testAggregateProvider({ baseUrl: p.baseUrl, apiKey: p.apiKey, model: p.model }))
    } catch (e: any) {
      setTestResult({ ok: false, error: e.message })
    } finally { setTesting(false) }
  }
  const handleFetchModels = async () => {
    setFetchingModels(true)
    try {
      const p = agg?.aiProviderConfig || {}
      const r = await api.fetchAggregateModels({ baseUrl: p.baseUrl, apiKey: p.apiKey })
      updateAggProvider({ availableModels: r?.models || [] })
    } catch { /* */ }
    finally { setFetchingModels(false) }
  }
  const handlePresetChange = (id: string) => {
    setSelectedPreset(id)
    const pre = PROVIDER_PRESETS.find((p) => p.id === id)
    if (pre?.baseUrl) updateAggProvider({ baseUrl: pre.baseUrl })
  }
  const handlePasswordSubmit = (event: FormEvent) => {
    event.preventDefault()
    setPasswordError(null)
    setPasswordOk(false)
    if (!currentPassword || !newPassword) {
      setPasswordError("请输入当前密码和新密码")
      return
    }
    if (newPassword !== confirmPassword) {
      setPasswordError("两次输入的新密码不一致")
      return
    }
    changePassword.mutate({ currentPassword, newPassword })
  }

  if (isLoading || !settingsData) return <div className="text-muted-foreground">加载中...</div>

  const local = editedSettings || settingsData || {}
  const sp = local.sourcePool || {}
  const cw = parseSettingObject(local.contentWorkflow)
  const agg = aggForm || {}
  const prov = agg.aiProviderConfig || {}
  const wf = agg.contentWorkflow || {}
  const priority: string[] = agg.primarySourcePriority || ["qidian_com_web"]

  const setLocal = (patch: any) => setEditedSettings({ ...local, ...patch })
  const updateCw = (patch: any) => setLocal({ contentWorkflow: { ...cw, ...patch } })
  const setAgg = (patch: any) => setAggForm({ ...agg, ...patch })
  const updateAggProvider = (patch: any) => setAgg({ aiProviderConfig: { ...prov, ...patch } })
  const updateAggWorkflow = (patch: any) => setAgg({ contentWorkflow: { ...wf, ...patch } })

  const plugins: any[] = pluginsData?.items || []
  const sources = plugins
    .filter((p: any) => p.enabled)
    .map((p: any) => ({ id: p.pluginId, name: p.name || p.pluginId, official: p.official }))
    .sort((a: any, b: any) => (a.official !== b.official ? (a.official ? -1 : 1) : a.name.localeCompare(b.name)))
  const addSource = (id: string) => {
    if (!id || priority.includes(id)) return
    setAgg({ primarySourcePriority: [...priority, id] })
    setSourceDropdownOpen(false)
  }
  const removeSource = (id: string) => setAgg({ primarySourcePriority: priority.filter((s) => s !== id) })
  const moveSource = (i: number, d: -1 | 1) => {
    const t = i + d; if (t < 0 || t >= priority.length) return
    const arr = [...priority]; [arr[i], arr[t]] = [arr[t], arr[i]]
    setAgg({ primarySourcePriority: arr })
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div className="lg:col-span-2 flex items-center justify-between">
        <h1 className="text-xl font-semibold">设置</h1>
        <Button size="sm" onClick={handleSaveAll} disabled={saveSettings.isPending || saveAgg.isPending || saved}>
          <Save className="w-4 h-4 mr-1" />
          {saved ? "已保存" : "保存"}
        </Button>
      </div>

      <Card className="lg:col-span-2">
        <CardHeader className="pb-2"><CardTitle className="text-sm">账户安全</CardTitle></CardHeader>
        <CardContent>
          <form onSubmit={handlePasswordSubmit} className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
            <div className="space-y-1">
              <Label htmlFor="current-password">当前密码</Label>
              <Input id="current-password" type="password" value={currentPassword} onChange={(e) => setCurrentPassword(e.target.value)} autoComplete="current-password" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="new-password">新密码</Label>
              <Input id="new-password" type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} autoComplete="new-password" />
            </div>
            <div className="space-y-1">
              <Label htmlFor="confirm-password">确认新密码</Label>
              <Input id="confirm-password" type="password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} autoComplete="new-password" />
            </div>
            <Button type="submit" disabled={changePassword.isPending}>
              {changePassword.isPending && <Loader2 className="w-4 h-4 mr-1 animate-spin" />}
              修改密码
            </Button>
          </form>
          {passwordError && (
            <Alert variant="destructive" className="mt-4">
              <AlertDescription>{passwordError}</AlertDescription>
            </Alert>
          )}
          {passwordOk && (
            <Alert className="mt-4">
              <AlertDescription>密码已修改。</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {/* ── 书源池 ────────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">书源池</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1"><Label>最大并发</Label><Input type="number" value={sp.max_concurrency || 3} onChange={(e) => setLocal({ sourcePool: { ...sp, max_concurrency: +e.target.value } })} /></div>
            <div className="space-y-1"><Label>批次大小</Label><Input type="number" value={sp.source_batch_size || 20} onChange={(e) => setLocal({ sourcePool: { ...sp, source_batch_size: +e.target.value } })} /></div>
            <div className="space-y-1"><Label>源超时(秒)</Label><Input type="number" value={sp.source_timeout_seconds || 20} onChange={(e) => setLocal({ sourcePool: { ...sp, source_timeout_seconds: +e.target.value } })} /></div>
            <div className="space-y-1"><Label>整体超时(秒)</Label><Input type="number" value={sp.overall_search_timeout_seconds || 60} onChange={(e) => setLocal({ sourcePool: { ...sp, overall_search_timeout_seconds: +e.target.value } })} /></div>
            <div className="space-y-1"><Label>浏览器搜索超时</Label><Input type="number" value={sp.browser_search_timeout_seconds || 60} onChange={(e) => setLocal({ sourcePool: { ...sp, browser_search_timeout_seconds: +e.target.value } })} /></div>
            <div className="space-y-1"><Label>浏览器读取超时</Label><Input type="number" value={sp.browser_source_timeout_seconds || 120} onChange={(e) => setLocal({ sourcePool: { ...sp, browser_source_timeout_seconds: +e.target.value } })} /></div>
          </div>
          <div className="grid grid-cols-2 gap-4 mt-4">
            <div className="space-y-1"><Label>搜索评分过滤</Label><Input type="number" min={0} max={500} value={local.searchScoreFilter ?? 100} onChange={(e) => setLocal({ searchScoreFilter: +e.target.value })} /><p className="text-xs text-muted-foreground">低于此值的结果被过滤</p></div>
            <div className="space-y-1"><Label>默认 User-Agent</Label><Input value={sp.default_user_agent || ""} placeholder="留空使用系统默认" onChange={(e) => setLocal({ sourcePool: { ...sp, default_user_agent: e.target.value } })} /></div>
          </div>
          <div className="grid grid-cols-2 gap-4 mt-4">
            <div className="space-y-1"><Label>代理 URL</Label><Input value={sp.proxy?.url || ""} onChange={(e) => setLocal({ sourcePool: { ...sp, proxy: { ...(sp.proxy || {}), url: e.target.value } } })} /></div>
            <div className="flex items-end gap-2 pb-1"><Switch checked={sp.proxy?.enabled || false} onCheckedChange={(c) => setLocal({ sourcePool: { ...sp, proxy: { ...(sp.proxy || {}), enabled: c } } })} /><Label>启用代理</Label></div>
          </div>
          <div className="mt-4">
            <div className="flex items-center gap-2">
              <Switch
                checked={sp.officialSourceInNormalSearch || false}
                onCheckedChange={(c) => setLocal({ sourcePool: { ...sp, officialSourceInNormalSearch: c } })}
              />
              <Label>启用官方源参与普通搜索</Label>
            </div>
            <p className="text-xs text-muted-foreground mt-1">开启后普通搜索同时搜第三方源和官方源，官方源命中额外 +50 分</p>
          </div>
        </CardContent>
      </Card>

      {/* ── 聚合开关 ──────────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-2"><CardTitle className="text-sm">聚合与内容处理</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4 mb-4">
            <div className="space-y-1"><Label>聚合模式</Label>
              <Select value={cw.aggregationMode || "balanced"} onValueChange={(v) => updateCw({ aggregationMode: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="fast">速度优先</SelectItem><SelectItem value="balanced">均衡</SelectItem><SelectItem value="quality">质量优先</SelectItem></SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>候选书源数</Label><Input type="number" min={1} max={30} value={cw.sourceCandidateLimit || 6} onChange={(e) => updateCw({ sourceCandidateLimit: +e.target.value })} /></div>
            <div className="space-y-1"><Label>净化强度</Label>
              <Select value={cw.purifyMode || "conservative"} onValueChange={(v) => updateCw({ purifyMode: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="off">关闭</SelectItem><SelectItem value="conservative">保守</SelectItem><SelectItem value="aggressive">强净化</SelectItem></SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            {[
              { icon: ShieldCheck, label: "自动聚合同名", desc: "统一比对详情", key: "autoAggregate", val: cw.autoAggregate ?? true },
              { icon: Wand2, label: "屏蔽词修复", desc: "标记缺口进 AI 队列", key: "blockedWordRepair", val: cw.blockedWordRepair || false },
              { icon: Bot, label: "AI 处理", desc: "下方配置 Provider", key: "aiEnabled", val: cw.aiEnabled || false },
              { icon: Bot, label: "阅读时处理", desc: "自动加入处理队列", key: "processAggregateOnRead", val: cw.processAggregateOnRead ?? true },
              { icon: ShieldCheck, label: "只返回聚合源", desc: "隐藏原始站点", key: "returnOnlyAggregateSource", val: cw.returnOnlyAggregateSource || false },
            ].map(({ icon: Icon, label, desc, key, val }) => (
              <div key={key} className="flex items-center gap-2 rounded-md border p-2.5">
                <Icon className="h-4 w-4 text-[#d4812a] shrink-0" />
                <div className="flex-1 min-w-0"><Label className="text-xs">{label}</Label><p className="text-[10px] text-muted-foreground truncate">{desc}</p></div>
                <Switch checked={val} onCheckedChange={(c) => updateCw({ [key]: c })} />
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* ── AI 服务商 ──────────────────────────────────────────────── */}
      <Card className="lg:col-span-2">
        <CardHeader className="pb-2"><CardTitle className="text-sm">AI 服务商配置</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4">
            <div className="space-y-1"><Label>服务商</Label>
              <Select value={selectedPreset} onValueChange={handlePresetChange}>
                <SelectTrigger><SelectValue placeholder="选择服务商" /></SelectTrigger>
                <SelectContent className="max-h-72">
                  {PROVIDER_PRESETS.map((p) => (
                    <SelectItem key={p.id} value={p.id}>
                      {p.name}{p.plan ? ` · ${p.plan}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>Base URL</Label>
              <Input value={prov.baseUrl || ""} onChange={(e) => { updateAggProvider({ baseUrl: e.target.value }); setSelectedPreset("custom") }} placeholder="https://api.example.com/v1" />
            </div>
            <div className="space-y-1"><Label>API Key</Label>
              <Input type="password" value={prov.apiKey || ""} onChange={(e) => updateAggProvider({ apiKey: e.target.value })} placeholder="sk-..." />
            </div>
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
            <div className="space-y-1"><Label>模型</Label>
              {prov.availableModels?.length > 0 ? (
                <Select value={prov.model || ""} onValueChange={(v) => updateAggProvider({ model: v })}>
                  <SelectTrigger><SelectValue placeholder="选择模型" /></SelectTrigger>
                  <SelectContent className="max-h-72">{prov.availableModels.map((m: string) => <SelectItem key={m} value={m}>{m}</SelectItem>)}</SelectContent>
                </Select>
              ) : (
                <Input value={prov.model || ""} onChange={(e) => updateAggProvider({ model: e.target.value })} placeholder="gpt-4o" />
              )}
            </div>
            <div className="space-y-1"><Label>偏差阈值</Label>
              <Select value={String(wf.deviationThreshold ?? 0.9)} onValueChange={(v) => updateAggWorkflow({ deviationThreshold: +v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="0.95">0.95 严格</SelectItem>
                  <SelectItem value="0.9">0.90 标准</SelectItem>
                  <SelectItem value="0.8">0.80 宽松</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1"><Label>检查间隔（分钟）</Label>
              <Input type="number" value={wf.aggregateCheckIntervalMinutes ?? 30} onChange={(e) => updateAggWorkflow({ aggregateCheckIntervalMinutes: +e.target.value })} />
            </div>
          </div>
          <div className="flex items-center gap-2 mt-3 flex-wrap">
            <Button variant="outline" size="sm" onClick={handleFetchModels} disabled={fetchingModels}>
              {fetchingModels ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-1" />}获取模型
            </Button>
            <Button variant="outline" size="sm" onClick={handleTestProvider} disabled={testing}>
              {testing ? <Loader2 className="w-4 h-4 mr-1 animate-spin" /> : <Zap className="w-4 h-4 mr-1" />}测试连接
            </Button>
            {testResult && (
              <span className="flex items-center gap-1.5 text-sm">
                {testResult.ok !== false ? (
                  <><CheckCircle2 className="w-4 h-4 text-green-600" /><span className="text-green-700">成功</span>
                    {testResult.latencyMs != null && <Badge variant="outline">{testResult.latencyMs}ms</Badge>}
                    {testResult.modelCount != null && <Badge variant="outline">{testResult.modelCount} 模型</Badge>}
                  </>
                ) : (
                  <><XCircle className="w-4 h-4 text-red-600" /><span className="text-red-700">{testResult.error || testResult.message || "失败"}</span></>
                )}
              </span>
            )}
          </div>
        </CardContent>
      </Card>

      {/* ── 主源优先级 ────────────────────────────────────────────── */}
      <Card className="lg:col-span-2">
        <CardHeader className="pb-2"><CardTitle className="text-sm">主源优先级</CardTitle></CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">排在前面的优先使用，不匹配时自动降级。</p>
          <div className="space-y-1">
            {priority.map((id, i) => {
              const src = sources.find((s: any) => s.id === id)
              return (
                <div key={id} className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm">
                  <div className="flex flex-col gap-0.5">
                    <button className="p-0 hover:bg-muted rounded disabled:opacity-30" disabled={i === 0} onClick={() => moveSource(i, -1)}>
                      <ChevronUp className="w-4 h-4" />
                    </button>
                    <button className="p-0 hover:bg-muted rounded disabled:opacity-30" disabled={i === priority.length - 1} onClick={() => moveSource(i, 1)}>
                      <ChevronDown className="w-4 h-4" />
                    </button>
                  </div>
                  <Badge variant={src?.official ? "default" : "secondary"} className="text-xs shrink-0">{i + 1}</Badge>
                  <span className="flex-1 truncate">{src ? src.name : id}{src?.official && <span className="ml-1 text-xs text-muted-foreground">(官方)</span>}</span>
                  <button className="rounded-sm hover:bg-muted p-0.5" onClick={() => removeSource(id)}><X className="w-3.5 h-3.5" /></button>
                </div>
              )
            })}
          </div>
          <div className="relative">
            <Button variant="outline" size="sm" onClick={() => setSourceDropdownOpen(!sourceDropdownOpen)}>
              <Plus className="w-4 h-4 mr-1" />添加书源
            </Button>
            {sourceDropdownOpen && (
              <div className="absolute z-50 mt-1 w-80 max-h-64 overflow-y-auto rounded-md border bg-popover shadow-md">
                {sources.filter((s: any) => !priority.includes(s.id)).length === 0
                  ? <div className="px-3 py-2 text-sm text-muted-foreground">无更多可用书源</div>
                  : sources.filter((s: any) => !priority.includes(s.id)).map((s: any) => (
                    <button key={s.id} className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent text-left" onClick={() => addSource(s.id)}>
                      <Badge variant={s.official ? "default" : "secondary"} className="text-xs shrink-0">{s.official ? "官方" : "三方"}</Badge>
                      <span className="truncate">{s.name}</span>
                      <span className="ml-auto text-xs text-muted-foreground truncate">{s.id}</span>
                    </button>
                  ))}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

    </div>
  )
}
