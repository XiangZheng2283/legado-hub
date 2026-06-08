import { useQuery } from "@tanstack/react-query"
import { api } from "@/lib/api"
import { Puzzle, BookOpen, Activity, AlertTriangle } from "lucide-react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"

function StatCard({
  label,
  value,
  icon: Icon,
}: {
  label: string
  value: string | number
  icon: React.ElementType
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{label}</p>
            <p className="text-2xl font-semibold mt-1">{value}</p>
          </div>
          <Icon className="w-5 h-5 text-muted-foreground" />
        </div>
      </CardContent>
    </Card>
  )
}

export function Dashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["status"],
    queryFn: api.status,
  })

  if (isLoading) {
    return <div className="text-muted-foreground">加载中...</div>
  }

  const stats = data || {}
  const pluginStats = stats.pluginStats || stats.plugins || {}
  const sourceStats = stats.sourceStats || {}

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">仪表盘</h1>
        <Badge variant="outline">{stats.phase || "plugin-runtime-stage-3"}</Badge>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="插件总数" value={pluginStats.total || 0} icon={Puzzle} />
        <StatCard label="已启用插件" value={pluginStats.enabled || 0} icon={BookOpen} />
        <StatCard label="健康插件" value={pluginStats.healthy || 0} icon={Activity} />
        <StatCard label="需要代理" value={pluginStats.proxyNeeded || 0} icon={AlertTriangle} />
      </div>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">系统信息</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-sm text-muted-foreground space-y-1">
            <p>版本: {stats.version || "0.1.0"}</p>
            <p>阶段: {stats.phase || "plugin-runtime-stage-3"}</p>
            <p>书源总数 (兼容): {sourceStats.total ?? "-"}</p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
