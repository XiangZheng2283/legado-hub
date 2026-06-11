import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Bot, Save, ShieldCheck, Wand2 } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

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
  const { data, isLoading } = useQuery({
    queryKey: ["settings"],
    queryFn: api.settings,
  })

  const [editedSettings, setEditedSettings] = useState<Record<string, any> | null>(null)

  const saveMutation = useMutation({
    mutationFn: api.updateSettings,
    onSuccess: () => {
      setEditedSettings(null)
      queryClient.invalidateQueries({ queryKey: ["settings"] })
    },
  })

  const handleSave = () => {
    saveMutation.mutate(localSettings)
  }

  if (isLoading) return <div className="text-muted-foreground">加载中...</div>

  const localSettings = editedSettings || data || {}
  const sourcePool = localSettings.sourcePool || {}
  const contentWorkflow = parseSettingObject(localSettings.contentWorkflow)

  const updateContentWorkflow = (patch: Record<string, any>) =>
    setEditedSettings({
      ...localSettings,
      contentWorkflow: { ...contentWorkflow, ...patch },
    })

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">设置</h1>
        <Button size="sm" onClick={handleSave}>
          <Save className="w-4 h-4 mr-1" />
          保存
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">书源池</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>最大并发</Label>
              <Input
                type="number"
                value={sourcePool.max_concurrency || 3}
                onChange={(e) =>
                  setEditedSettings({
                    ...localSettings,
                    sourcePool: { ...sourcePool, max_concurrency: Number(e.target.value) },
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>批次大小</Label>
              <Input
                type="number"
                value={sourcePool.source_batch_size || 20}
                onChange={(e) =>
                  setEditedSettings({
                    ...localSettings,
                    sourcePool: { ...sourcePool, source_batch_size: Number(e.target.value) },
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>源超时(秒)</Label>
              <Input
                type="number"
                value={sourcePool.source_timeout_seconds || 20}
                onChange={(e) =>
                  setEditedSettings({
                    ...localSettings,
                    sourcePool: { ...sourcePool, source_timeout_seconds: Number(e.target.value) },
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>整体超时(秒)</Label>
              <Input
                type="number"
                value={sourcePool.overall_search_timeout_seconds || 60}
                onChange={(e) =>
                  setEditedSettings({
                    ...localSettings,
                    sourcePool: { ...sourcePool, overall_search_timeout_seconds: Number(e.target.value) },
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>浏览器搜索超时(秒)</Label>
              <Input
                type="number"
                value={sourcePool.browser_search_timeout_seconds || 60}
                onChange={(e) =>
                  setEditedSettings({
                    ...localSettings,
                    sourcePool: { ...sourcePool, browser_search_timeout_seconds: Number(e.target.value) },
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>浏览器读取超时(秒)</Label>
              <Input
                type="number"
                value={sourcePool.browser_source_timeout_seconds || 120}
                onChange={(e) =>
                  setEditedSettings({
                    ...localSettings,
                    sourcePool: { ...sourcePool, browser_source_timeout_seconds: Number(e.target.value) },
                  })
                }
              />
            </div>
            <div className="space-y-2">
              <Label>搜索评分过滤阈值</Label>
              <Input
                type="number"
                min={0}
                max={500}
                value={localSettings.searchScoreFilter ?? 100}
                onChange={(e) =>
                  setEditedSettings({
                    ...localSettings,
                    searchScoreFilter: Number(e.target.value),
                  })
                }
              />
              <p className="text-xs text-muted-foreground">评分低于此值的结果将被过滤（0 表示不过滤）</p>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">聚合与内容处理</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 lg:grid-cols-3">
            <div className="space-y-2">
              <Label>聚合模式</Label>
              <Select
                value={contentWorkflow.aggregationMode || "balanced"}
                onValueChange={(value) => updateContentWorkflow({ aggregationMode: value })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="fast">速度优先</SelectItem>
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
                max={30}
                value={contentWorkflow.sourceCandidateLimit || 6}
                onChange={(e) => updateContentWorkflow({ sourceCandidateLimit: Number(e.target.value) })}
              />
            </div>
            <div className="space-y-2">
              <Label>净化强度</Label>
              <Select
                value={contentWorkflow.purifyMode || "conservative"}
                onValueChange={(value) => updateContentWorkflow({ purifyMode: value })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="off">关闭</SelectItem>
                  <SelectItem value="conservative">保守</SelectItem>
                  <SelectItem value="aggressive">强净化</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>聚合检查间隔</Label>
              <Select
                value={String(contentWorkflow.aggregateCheckIntervalMinutes || 30)}
                onValueChange={(value) => updateContentWorkflow({ aggregateCheckIntervalMinutes: Number(value) })}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="10">每 10 分钟</SelectItem>
                  <SelectItem value="30">每 30 分钟</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="grid gap-3 lg:grid-cols-5">
            <div className="flex items-center gap-3 rounded-md border p-3">
              <ShieldCheck className="h-4 w-4 text-[#d4812a]" />
              <div className="flex-1">
                <Label>自动聚合同名书</Label>
                <p className="text-xs text-muted-foreground">统一比对详情、目录和章节可读性</p>
              </div>
              <Switch
                checked={contentWorkflow.autoAggregate ?? true}
                onCheckedChange={(checked) => updateContentWorkflow({ autoAggregate: checked })}
              />
            </div>
            <div className="flex items-center gap-3 rounded-md border p-3">
              <Wand2 className="h-4 w-4 text-[#d4812a]" />
              <div className="flex-1">
                <Label>屏蔽词修复</Label>
                <p className="text-xs text-muted-foreground">先标记缺口，后续进入 AI 修复队列</p>
              </div>
              <Switch
                checked={contentWorkflow.blockedWordRepair || false}
                onCheckedChange={(checked) => updateContentWorkflow({ blockedWordRepair: checked })}
              />
            </div>
            <div className="flex items-center gap-3 rounded-md border p-3">
              <Bot className="h-4 w-4 text-[#d4812a]" />
              <div className="flex-1">
                <Label>AI 处理</Label>
                <p className="text-xs text-muted-foreground">Provider 和 Model 在下方统一配置</p>
              </div>
              <Switch
                checked={contentWorkflow.aiEnabled || false}
                onCheckedChange={(checked) => updateContentWorkflow({ aiEnabled: checked })}
              />
            </div>
            <div className="flex items-center gap-3 rounded-md border p-3">
              <Bot className="h-4 w-4 text-[#d4812a]" />
              <div className="flex-1">
                <Label>点开聚合源后处理</Label>
                <p className="text-xs text-muted-foreground">自动加入全章节处理和复查队列</p>
              </div>
              <Switch
                checked={contentWorkflow.processAggregateOnRead ?? true}
                onCheckedChange={(checked) => updateContentWorkflow({ processAggregateOnRead: checked })}
              />
            </div>
            <div className="flex items-center gap-3 rounded-md border p-3">
              <ShieldCheck className="h-4 w-4 text-[#d4812a]" />
              <div className="flex-1">
                <Label>只返回聚合源</Label>
                <p className="text-xs text-muted-foreground">阅读搜索隐藏原始站点结果</p>
              </div>
              <Switch
                checked={contentWorkflow.returnOnlyAggregateSource || false}
                onCheckedChange={(checked) => updateContentWorkflow({ returnOnlyAggregateSource: checked })}
              />
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div className="space-y-2">
              <Label>AI Provider</Label>
              <Input
                value={contentWorkflow.aiProvider || ""}
                placeholder="openai / compatible endpoint"
                onChange={(e) => updateContentWorkflow({ aiProvider: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Model</Label>
              <Input
                value={contentWorkflow.model || ""}
                placeholder="例如 gpt-4.1-mini"
                onChange={(e) => updateContentWorkflow({ model: e.target.value })}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">代理</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>代理URL</Label>
            <Input
              type="text"
              value={sourcePool.proxy?.url || ""}
              onChange={(e) =>
                setEditedSettings({
                  ...localSettings,
                  sourcePool: {
                    ...sourcePool,
                    proxy: { ...(sourcePool.proxy || {}), url: e.target.value },
                  },
                })
              }
            />
          </div>
          <div className="flex items-center gap-2">
            <Switch
              checked={sourcePool.proxy?.enabled || false}
              onCheckedChange={(checked) =>
                setEditedSettings({
                  ...localSettings,
                  sourcePool: {
                    ...sourcePool,
                    proxy: { ...(sourcePool.proxy || {}), enabled: checked },
                  },
                })
              }
            />
            <Label>启用代理</Label>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
