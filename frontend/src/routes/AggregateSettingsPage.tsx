import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Save, Zap, RefreshCw, X, Plus, Loader2, CheckCircle2, XCircle, GripVertical } from "lucide-react"
import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

// ── provider presets ────────────────────────────────────────────────────────

const PROVIDER_PRESETS = [
  { id: "deepseek", name: "DeepSeek", baseUrl: "https://api.deepseek.com/v1" },
  { id: "openai", name: "OpenAI", baseUrl: "https://api.openai.com/v1" },
  { id: "anthropic", name: "Anthropic (Claude)", baseUrl: "https://api.anthropic.com/v1" },
  { id: "moonshot", name: "Moonshot / Kimi", baseUrl: "https://api.moonshot.cn/v1" },
  { id: "siliconflow", name: "硅基流动 SiliconFlow", baseUrl: "https://api.siliconflow.cn/v1" },
  { id: "qwen", name: "通义千问 (DashScope)", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { id: "zhipu", name: "智谱 GLM", baseUrl: "https://open.bigmodel.cn/api/paas/v4" },
  { id: "minimax", name: "MiniMax", baseUrl: "https://api.minimax.chat/v1" },
  { id: "mistral", name: "Mistral AI", baseUrl: "https://api.mistral.ai/v1" },
  { id: "openrouter", name: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1" },
  { id: "baichuan", name: "百川大模型", baseUrl: "https://api.baichuan-ai.com/v1" },
  { id: "spark", name: "讯飞星火", baseUrl: "https://spark-api-open.xf-yun.com/v1" },
  { id: "doubao", name: "字节豆包", baseUrl: "https://ark.cn-beijing.volces.com/api/v3" },
  { id: "yi", name: "零一万物 Yi", baseUrl: "https://api.lingyiwanwu.com/v1" },
  { id: "stepfun", name: "阶跃星辰 Step", baseUrl: "https://api.stepfun.com/v1" },
  { id: "groq", name: "Groq", baseUrl: "https://api.groq.com/openai/v1" },
  { id: "together", name: "Together AI", baseUrl: "https://api.together.xyz/v1" },
  { id: "nvidia", name: "NVIDIA NIM", baseUrl: "https://integrate.api.nvidia.com/v1" },
  { id: "mimo", name: "小米 MiMo", baseUrl: "https://api.xiaomi.com/v1" },
  { id: "hunyuan", name: "腾讯混元", baseUrl: "https://api.hunyuan.cloud.tencent.com/v1" },
  { id: "tiangong", name: "昆仑万维 天工", baseUrl: "https://api.tiangong.cn/v1" },
  { id: "sensechat", name: "商汤日日新 SenseChat", baseUrl: "https://api.sensenova.cn/v1" },
  { id: "ollama", name: "Ollama (本地)", baseUrl: "http://localhost:11434/v1" },
  { id: "lmstudio", name: "LM Studio (本地)", baseUrl: "http://localhost:1234/v1" },
  { id: "custom", name: "自定义", baseUrl: "" },
] as const

// ── component ───────────────────────────────────────────────────────────────

export function AggregateSettingsPage() {
  const queryClient = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ["aggregateSettings"],
    queryFn: api.aggregateSettings,
  })
  // Fetch available plugins for source selector.
  const { data: pluginsData } = useQuery({
    queryKey: ["plugins"],
    queryFn: api.plugins,
  })

  const [form, setForm] = useState<Record<string, any> | null>(null)
  const [saved, setSaved] = useState(false)
  const [testResult, setTestResult] = useState<any>(null)
  const [testing, setTesting] = useState(false)
  const [fetchingModels, setFetchingModels] = useState(false)
  const [selectedPreset, setSelectedPreset] = useState("custom")
  const [sourceDropdownOpen, setSourceDropdownOpen] = useState(false)

  useEffect(() => {
    if (data && form === null) {
      setForm(data)
      // Detect which preset matches the current baseUrl.
      const url = data?.aiProviderConfig?.baseUrl || ""
      const match = PROVIDER_PRESETS.find((p) => p.baseUrl && url.startsWith(p.baseUrl))
      if (match) setSelectedPreset(match.id)
    }
  }, [data])

  useEffect(() => {
    if (!saved) return
    const timer = setTimeout(() => setSaved(false), 2000)
    return () => clearTimeout(timer)
  }, [saved])

  const saveMutation = useMutation({
    mutationFn: api.updateAggregateSettings,
    onSuccess: () => {
      setSaved(true)
      queryClient.invalidateQueries({ queryKey: ["aggregateSettings"] })
    },
  })

  const handleTestProvider = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const provider = local.aiProviderConfig || {}
      const result = await api.testAggregateProvider({
        baseUrl: provider.baseUrl,
        apiKey: provider.apiKey,
        model: provider.model,
      })
      setTestResult(result)
    } catch (err: any) {
      setTestResult({ ok: false, error: err.message })
    } finally {
      setTesting(false)
    }
  }

  const handleFetchModels = async () => {
    setFetchingModels(true)
    try {
      const provider = local.aiProviderConfig || {}
      const result = await api.fetchAggregateModels({
        baseUrl: provider.baseUrl,
        apiKey: provider.apiKey,
      })
      const models = result?.models || []
      updateProvider({ availableModels: models })
    } catch {
      // ignore
    } finally {
      setFetchingModels(false)
    }
  }

  if (isLoading || !form) return <div className="text-muted-foreground">加载中...</div>

  const local = form
  const set = (patch: Record<string, any>) => setForm({ ...local, ...patch })
  const provider = local.aiProviderConfig || {}
  const workflow = local.contentWorkflow || {}
  const priorityList: string[] = local.primarySourcePriority || ["qidian_com_web"]

  const updateProvider = (patch: Record<string, any>) =>
    set({ aiProviderConfig: { ...provider, ...patch } })
  const updateWorkflow = (patch: Record<string, any>) =>
    set({ contentWorkflow: { ...workflow, ...patch } })

  // ── provider preset handler ─────────────────────────────────────────
  const handlePresetChange = (presetId: string) => {
    setSelectedPreset(presetId)
    const preset = PROVIDER_PRESETS.find((p) => p.id === presetId)
    if (preset && preset.baseUrl) {
      updateProvider({ baseUrl: preset.baseUrl })
    }
  }

  // ── source list from plugins ────────────────────────────────────────
  const plugins: any[] = pluginsData?.items || []
  const availableSources = plugins
    .filter((p: any) => p.enabled)
    .map((p: any) => ({
      id: p.pluginId,
      name: p.name || p.pluginId,
      official: p.official,
    }))
    .sort((a: any, b: any) => {
      if (a.official !== b.official) return a.official ? -1 : 1
      return a.name.localeCompare(b.name)
    })

  const addSource = (sourceId: string) => {
    if (!sourceId || priorityList.includes(sourceId)) return
    set({ primarySourcePriority: [...priorityList, sourceId] })
    setSourceDropdownOpen(false)
  }
  const removeSource = (id: string) => {
    set({ primarySourcePriority: priorityList.filter((s) => s !== id) })
  }
  const moveSource = (idx: number, dir: -1 | 1) => {
    const newList = [...priorityList]
    const target = idx + dir
    if (target < 0 || target >= newList.length) return
    ;[newList[idx], newList[target]] = [newList[target], newList[idx]]
    set({ primarySourcePriority: newList })
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">聚合设置</h1>
        <Button
          size="sm"
          onClick={() => saveMutation.mutate(local)}
          disabled={saveMutation.isPending || saved}
        >
          <Save className="w-4 h-4 mr-1" />
          {saved ? "已保存" : saveMutation.isPending ? "保存中..." : "保存"}
        </Button>
      </div>

      {/* AI Provider */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">AI 服务商配置</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Provider Preset */}
          <div className="space-y-2">
            <Label>服务商</Label>
            <Select value={selectedPreset} onValueChange={handlePresetChange}>
              <SelectTrigger>
                <SelectValue placeholder="选择服务商" />
              </SelectTrigger>
              <SelectContent>
                {PROVIDER_PRESETS.map((p) => (
                  <SelectItem key={p.id} value={p.id}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {/* Base URL + API Key */}
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>Base URL</Label>
              <Input
                value={provider.baseUrl || ""}
                onChange={(e) => {
                  updateProvider({ baseUrl: e.target.value })
                  setSelectedPreset("custom")
                }}
                placeholder="https://api.example.com/v1"
              />
            </div>
            <div className="space-y-2">
              <Label>API Key</Label>
              <Input
                type="password"
                value={provider.apiKey || ""}
                onChange={(e) => updateProvider({ apiKey: e.target.value })}
                placeholder="sk-..."
              />
            </div>
          </div>
          {/* Model */}
          <div className="flex items-end gap-2">
            <div className="flex-1 space-y-2">
              <Label>模型</Label>
              {provider.availableModels?.length > 0 ? (
                <Select
                  value={provider.model || ""}
                  onValueChange={(v) => updateProvider({ model: v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    {provider.availableModels.map((m: string) => (
                      <SelectItem key={m} value={m}>
                        {m}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <Input
                  value={provider.model || ""}
                  onChange={(e) => updateProvider({ model: e.target.value })}
                  placeholder="gpt-4o"
                />
              )}
            </div>
            <Button variant="outline" size="sm" onClick={handleFetchModels} disabled={fetchingModels}>
              {fetchingModels ? (
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4 mr-1" />
              )}
              获取模型列表
            </Button>
          </div>
          {/* Test Connection */}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={handleTestProvider} disabled={testing}>
              {testing ? (
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              ) : (
                <Zap className="w-4 h-4 mr-1" />
              )}
              测试连接
            </Button>
            {testResult && (
              <div className="flex items-center gap-2 text-sm">
                {testResult.ok !== false ? (
                  <>
                    <CheckCircle2 className="w-4 h-4 text-green-600" />
                    <span className="text-green-700">连接成功</span>
                    {testResult.latencyMs != null && (
                      <Badge variant="outline">{testResult.latencyMs}ms</Badge>
                    )}
                    {testResult.modelCount != null && (
                      <Badge variant="outline">{testResult.modelCount} 个模型</Badge>
                    )}
                  </>
                ) : (
                  <>
                    <XCircle className="w-4 h-4 text-red-600" />
                    <span className="text-red-700">{testResult.error || testResult.message || "连接失败"}</span>
                  </>
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Content Workflow */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">内容工作流</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center gap-3">
            <Switch
              checked={workflow.aiEnabled ?? true}
              onCheckedChange={(v) => updateWorkflow({ aiEnabled: v })}
            />
            <Label>启用 AI 内容处理</Label>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>净化模式</Label>
              <Select
                value={workflow.purifyMode || "conservative"}
                onValueChange={(v) => updateWorkflow({ purifyMode: v })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="off">关闭</SelectItem>
                  <SelectItem value="conservative">保守</SelectItem>
                  <SelectItem value="aggressive">激进</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>检查间隔（分钟）</Label>
              <Input
                type="number"
                value={workflow.aggregateCheckIntervalMinutes ?? 30}
                onChange={(e) =>
                  updateWorkflow({ aggregateCheckIntervalMinutes: Number(e.target.value) })
                }
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label>偏差阈值</Label>
            <Select
              value={String(workflow.deviationThreshold ?? 0.9)}
              onValueChange={(v) => updateWorkflow({ deviationThreshold: Number(v) })}
            >
              <SelectTrigger className="w-48">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="0.95">0.95（严格）</SelectItem>
                <SelectItem value="0.9">0.90（标准）</SelectItem>
                <SelectItem value="0.8">0.80（宽松）</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="grid grid-cols-2 gap-4 pt-2 border-t">
            <div className="space-y-2">
              <Label>聚合模式</Label>
              <Select
                value={workflow.aggregationMode || "balanced"}
                onValueChange={(v) => updateWorkflow({ aggregationMode: v })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fast">快速</SelectItem>
                  <SelectItem value="balanced">均衡</SelectItem>
                  <SelectItem value="quality">质量优先</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>候选书源数</Label>
              <Input
                type="number"
                min={1}
                max={10}
                value={workflow.sourceCandidateLimit ?? 3}
                onChange={(e) => updateWorkflow({ sourceCandidateLimit: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label>最低源评分</Label>
              <Input
                type="number"
                min={0}
                max={1}
                step={0.05}
                value={workflow.minSourceScore ?? 0.6}
                onChange={(e) => updateWorkflow({ minSourceScore: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label>前文参考章节数</Label>
              <Input
                type="number"
                min={0}
                max={10}
                value={workflow.includePreviousChapters ?? 3}
                onChange={(e) => updateWorkflow({ includePreviousChapters: Number(e.target.value) })}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-2 pt-2 border-t">
            <div className="flex items-center gap-3">
              <Switch
                checked={workflow.autoAggregate ?? false}
                onCheckedChange={(v) => updateWorkflow({ autoAggregate: v })}
              />
              <Label>自动聚合同名书籍</Label>
            </div>
            <div className="flex items-center gap-3">
              <Switch
                checked={workflow.processAggregateOnRead ?? false}
                onCheckedChange={(v) => updateWorkflow({ processAggregateOnRead: v })}
              />
              <Label>阅读时自动处理</Label>
            </div>
            <div className="flex items-center gap-3">
              <Switch
                checked={workflow.returnOnlyAggregateSource ?? false}
                onCheckedChange={(v) => updateWorkflow({ returnOnlyAggregateSource: v })}
              />
              <Label>只返回聚合源</Label>
            </div>
            <div className="flex items-center gap-3">
              <Switch
                checked={workflow.blockedWordRepair ?? true}
                onCheckedChange={(v) => updateWorkflow({ blockedWordRepair: v })}
              />
              <Label>屏蔽词修复</Label>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Primary Source Priority */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">主源优先级</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            按优先级排列，排在前面的优先使用。拖拽箭头可调整顺序。
          </p>
          <div className="space-y-1">
            {priorityList.map((id, idx) => {
              const src = availableSources.find((s: any) => s.id === id)
              return (
                <div key={id} className="flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm">
                  <div className="flex items-center gap-0.5">
                    <button
                      className="p-0.5 hover:bg-muted rounded disabled:opacity-30"
                      disabled={idx === 0}
                      onClick={() => moveSource(idx, -1)}
                    >
                      <GripVertical className="w-3.5 h-3.5 rotate-180" />
                    </button>
                    <button
                      className="p-0.5 hover:bg-muted rounded disabled:opacity-30"
                      disabled={idx === priorityList.length - 1}
                      onClick={() => moveSource(idx, 1)}
                    >
                      <GripVertical className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <Badge variant={src?.official ? "default" : "secondary"} className="text-xs">
                    {idx + 1}
                  </Badge>
                  <span className="flex-1 truncate">
                    {src ? src.name : id}
                    {src?.official && <span className="ml-1 text-xs text-muted-foreground">(官方)</span>}
                  </span>
                  <button
                    className="rounded-sm hover:bg-muted p-0.5"
                    onClick={() => removeSource(id)}
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              )
            })}
          </div>
          {/* Source selector dropdown */}
          <div className="relative">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setSourceDropdownOpen(!sourceDropdownOpen)}
            >
              <Plus className="w-4 h-4 mr-1" />
              添加书源
            </Button>
            {sourceDropdownOpen && (
              <div className="absolute z-50 mt-1 w-80 max-h-64 overflow-y-auto rounded-md border bg-popover shadow-md">
                {availableSources.length === 0 ? (
                  <div className="px-3 py-2 text-sm text-muted-foreground">无可用书源</div>
                ) : (
                  availableSources
                    .filter((s: any) => !priorityList.includes(s.id))
                    .map((s: any) => (
                      <button
                        key={s.id}
                        className="flex w-full items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent text-left"
                        onClick={() => addSource(s.id)}
                      >
                        <Badge variant={s.official ? "default" : "secondary"} className="text-xs shrink-0">
                          {s.official ? "官方" : "三方"}
                        </Badge>
                        <span className="truncate">{s.name}</span>
                        <span className="ml-auto text-xs text-muted-foreground truncate">{s.id}</span>
                      </button>
                    ))
                )}
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
