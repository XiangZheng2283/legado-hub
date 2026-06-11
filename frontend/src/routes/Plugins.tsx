import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { Link } from "react-router-dom"
import { RefreshCw, Trash2, Power, PowerOff, Play, AlertCircle, Wifi, WifiOff, Activity } from "lucide-react"

import { api } from "@/lib/api"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { Card, CardContent } from "@/components/ui/card"

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

export function Plugins() {
  const queryClient = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  const { data, isLoading } = useQuery({
    queryKey: ["plugins"],
    queryFn: api.plugins,
  })

  const reloadMutation = useMutation({
    mutationFn: api.reloadPlugins,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugins"] }),
  })

  const batchEnableMutation = useMutation({
    mutationFn: ({ ids, enabled }: { ids: string[]; enabled: boolean }) =>
      api.batchEnablePlugins(ids, enabled),
    onSuccess: () => {
      setSelectedIds(new Set())
      queryClient.invalidateQueries({ queryKey: ["plugins"] })
    },
  })

  const batchDeleteMutation = useMutation({
    mutationFn: (ids: string[]) => api.batchDeletePlugins(ids),
    onSuccess: () => {
      setSelectedIds(new Set())
      queryClient.invalidateQueries({ queryKey: ["plugins"] })
    },
  })

  const pingMutation = useMutation({
    mutationFn: (ids: string[]) => api.pingAllPlugins(ids.length > 0 ? ids : []),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["plugins"] }),
  })

  const allPlugins = data?.items || []
  const plugins = allPlugins.filter((p: any) => !p.official)

  const allSelected = plugins.length > 0 && selectedIds.size === plugins.length
  const someSelected = selectedIds.size > 0 && selectedIds.size < plugins.length

  const selectedPlugins = plugins.filter((p: any) => selectedIds.has(p.pluginId))
  const hasEnabled = selectedPlugins.some((p: any) => p.enabled)
  const hasDisabled = selectedPlugins.some((p: any) => !p.enabled)

  const toggleSelectAll = () => {
    if (allSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(plugins.map((p: any) => p.pluginId)))
    }
  }

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }

  const handleBatchEnable = () => {
    if (selectedIds.size === 0) return
    const ids = selectedPlugins.filter((p: any) => !p.enabled).map((p: any) => p.pluginId)
    if (ids.length === 0) return
    batchEnableMutation.mutate({ ids, enabled: true })
  }

  const handleBatchDisable = () => {
    if (selectedIds.size === 0) return
    const ids = selectedPlugins.filter((p: any) => p.enabled).map((p: any) => p.pluginId)
    if (ids.length === 0) return
    batchEnableMutation.mutate({ ids, enabled: false })
  }

  const handleBatchDelete = () => {
    if (selectedIds.size === 0) return
    if (!confirm(`确定要删除选中的 ${selectedIds.size} 个书源吗？`)) return
    batchDeleteMutation.mutate(Array.from(selectedIds))
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <h1 className="text-xl font-semibold">书源</h1>
          <p className="text-sm text-muted-foreground">共 {plugins.length} 个普通书源</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Button
            size="sm"
            onClick={() => reloadMutation.mutate()}
            disabled={reloadMutation.isPending}
          >
            <RefreshCw className="w-4 h-4 mr-1" />
            重新加载
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => pingMutation.mutate(Array.from(selectedIds))}
            disabled={pingMutation.isPending}
          >
            <Activity className="w-4 h-4 mr-1" />
            {pingMutation.isPending ? "Ping中..." : selectedIds.size > 0 ? `Ping选中 (${selectedIds.size})` : "Ping全部"}
          </Button>
        </div>
      </div>

      {selectedIds.size > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">已选 {selectedIds.size} 项</span>
          {hasEnabled && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleBatchDisable}
              disabled={batchEnableMutation.isPending || batchDeleteMutation.isPending}
            >
              <PowerOff className="w-3 h-3 mr-1" />
              批量禁用
            </Button>
          )}
          {hasDisabled && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleBatchEnable}
              disabled={batchEnableMutation.isPending || batchDeleteMutation.isPending}
            >
              <Power className="w-3 h-3 mr-1" />
              批量启用
            </Button>
          )}
          <Button
            variant="destructive"
            size="sm"
            onClick={handleBatchDelete}
            disabled={batchEnableMutation.isPending || batchDeleteMutation.isPending}
          >
            <Trash2 className="w-3 h-3 mr-1" />
            批量删除
          </Button>
        </div>
      )}

      {isLoading ? (
        <div className="text-muted-foreground">加载中...</div>
      ) : plugins.length === 0 ? (
        <Card>
          <CardContent className="p-8 text-center text-muted-foreground">
            暂无书源
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">
                    <Checkbox
                      checked={allSelected}
                      ref={(el) => {
                        if (el) {
                          (el as any).indeterminate = someSelected
                        }
                      }}
                      onCheckedChange={toggleSelectAll}
                    />
                  </TableHead>
                  <TableHead className="w-12">序号</TableHead>
                  <TableHead>名称</TableHead>
                  <TableHead>ID</TableHead>
                  <TableHead>能力</TableHead>
                  <TableHead>版本</TableHead>
                  <TableHead>修改时间</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>代理</TableHead>
                  <TableHead>认证</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>Ping</TableHead>
                  <TableHead>Smoke</TableHead>
                  <TableHead>最近错误</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {plugins.map((p: any, index: number) => (
                  <TableRow key={p.pluginId}>
                    <TableCell>
                      <Checkbox
                        checked={selectedIds.has(p.pluginId)}
                        onCheckedChange={() => toggleSelect(p.pluginId)}
                      />
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">{index + 1}</TableCell>
                    <TableCell>
                      <Link
                        to={`/console/plugins/${p.pluginId}`}
                        className="font-medium hover:text-primary"
                      >
                        {p.name}
                      </Link>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">{p.pluginId}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {p.capabilities.map((c: string) => (
                          <Badge key={c} variant="secondary" className="text-xs">
                            {formatCapability(c)}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground text-xs">{p.version || "-"}</TableCell>
                    <TableCell className="text-muted-foreground text-xs whitespace-nowrap">{p.lastModified || "-"}</TableCell>
                    <TableCell>
                      <Badge variant={p.accessType === "Browser" ? "default" : "outline"} className="text-xs">
                        {p.accessType || p.sourceType || "HTTP"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge
                        variant={p.proxyRequired ? "default" : "outline"}
                        className="text-xs"
                      >
                        {p.proxyRequired ? `${p.proxyMode || "auto"}` : "无"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {p.auth?.mode || "none"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant={p.enabled ? "success" : "outline"}>
                        {p.enabled ? "启用" : "禁用"}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      {p.health?.pingStatus === "reachable" ? (
                        <div className="flex items-center gap-1 text-green-600 text-xs" title={`${p.health.pingLatencyMs}ms`}>
                          <Wifi className="w-3 h-3 shrink-0" />
                          <span>{p.health.pingLatencyMs}ms</span>
                        </div>
                      ) : p.health?.pingStatus === "unreachable" ? (
                        <div className="flex items-center gap-1 text-destructive text-xs" title="不可达">
                          <WifiOff className="w-3 h-3 shrink-0" />
                          <span>不可达</span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-xs">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {p.health?.lastTestResult ? (
                        <Badge variant={p.health.lastTestResult.pass ? "success" : "destructive"} className="text-xs">
                          {p.health.lastTestResult.pass ? "通过" : "失败"}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground text-xs">-</span>
                      )}
                    </TableCell>
                    <TableCell>
                      {p.health?.lastError ? (
                        <div className="flex items-center gap-1 text-destructive text-xs" title={p.health.lastError}>
                          <AlertCircle className="w-3 h-3 shrink-0" />
                          <span className="max-w-[120px] truncate">{p.health.lastError}</span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-xs">-</span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
