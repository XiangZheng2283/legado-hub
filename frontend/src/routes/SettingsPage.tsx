import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Save } from "lucide-react"
import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

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
                value={sourcePool.max_concurrency || 6}
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
                value={sourcePool.source_timeout_seconds || 15}
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
                value={sourcePool.overall_search_timeout_seconds || 45}
                onChange={(e) =>
                  setEditedSettings({
                    ...localSettings,
                    sourcePool: { ...sourcePool, overall_search_timeout_seconds: Number(e.target.value) },
                  })
                }
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
