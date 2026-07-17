import type { ReactNode } from "react"
import { Link } from "react-router-dom"
import { AlertCircle } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

const CAPABILITY_LABELS: Record<string, string> = { search: "搜索", detail: "详情", toc: "目录", chapter: "正文", content: "正文", explore: "发现", auth: "登录" }
const CAPABILITY_COLORS: Record<string, string> = {
  search: "bg-blue-50 text-blue-600",
  detail: "bg-emerald-50 text-emerald-600",
  toc: "bg-purple-50 text-purple-600",
  chapter: "bg-amber-50 text-amber-600",
  content: "bg-amber-50 text-amber-600",
  explore: "bg-cyan-50 text-cyan-600",
  auth: "bg-rose-50 text-rose-600",
}

function sourceCategory(source: any) {
  const tags = (source.tags || []).map((tag: string) => tag.toLowerCase())
  const name = String(source.name || "").toLowerCase()
  if (tags.includes("漫画") || name.includes("漫画")) return "漫画"
  if (tags.includes("轻小说") || name.includes("轻小说")) return "轻小说"
  return "小说"
}

function sourceLatency(source: any) {
  const latency = Number(source.health?.pingLatencyMs ?? source.latency ?? 0)
  return Number.isFinite(latency) ? latency : 0
}

function latencyClass(latency: number) {
  if (latency === 0) return "text-slate-400"
  if (latency < 100) return "text-emerald-500"
  if (latency < 300) return "text-amber-500"
  return "text-rose-500"
}

interface SourceListTableProps {
  items: any[]
  title: string
  description: string
  emptyMessage: string
  switcher?: ReactNode
  toolbar?: ReactNode
  loading?: boolean
  selectable?: boolean
  selectedIds?: Set<string>
  selectionDisabled?: boolean
  onToggleSelectAll?: () => void
  onToggleSelected?: (pluginId: string) => void
  onToggleEnabled?: (pluginId: string, enabled: boolean) => void
  toggleEnabledDisabled?: boolean
  extraHeaders?: ReactNode
  extraColumnCount?: number
  renderExtraCells?: (item: any) => ReactNode
  tableClassName?: string
  testId?: string
}

export function SourceListTable({
  items,
  title,
  description,
  emptyMessage,
  switcher,
  toolbar,
  loading = false,
  selectable = false,
  selectedIds = new Set<string>(),
  selectionDisabled = false,
  onToggleSelectAll,
  onToggleSelected,
  onToggleEnabled,
  toggleEnabledDisabled = false,
  extraHeaders,
  extraColumnCount = 0,
  renderExtraCells,
  tableClassName = "min-w-[980px]",
  testId,
}: SourceListTableProps) {
  const allSelected = items.length > 0 && selectedIds.size === items.length

  return (
    <section className="relative">
      {switcher && <div className="absolute -left-3 top-4 z-10">{switcher}</div>}
      <Card className="overflow-hidden border border-slate-200 shadow-sm">
        <CardContent className="p-0" data-testid={testId}>
          <div className={`flex flex-col gap-3 border-b border-slate-200 pb-4 pr-4 pt-4 sm:flex-row sm:items-end sm:justify-between ${switcher ? "pl-12" : "pl-4"}`}>
            <div>
              <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
              <p className="mt-1 text-sm text-slate-500">{description}</p>
            </div>
            {toolbar}
          </div>
          {loading ? (
            <div role="status" className="py-10 text-center text-sm text-slate-500">加载中...</div>
          ) : (
            <Table className={tableClassName}>
              <TableHeader className="border-b border-slate-200 bg-slate-50/75">
                <TableRow>
                  {selectable && (
                    <TableHead className="w-10 text-center">
                      <Checkbox
                        aria-label="全选当前书源"
                        checked={allSelected}
                        disabled={selectionDisabled || items.length === 0}
                        onCheckedChange={onToggleSelectAll}
                      />
                    </TableHead>
                  )}
                  <TableHead className="py-3 font-semibold text-slate-700">名称与版本</TableHead>
                  <TableHead className="font-semibold text-slate-700">插件标识 (ID)</TableHead>
                  <TableHead className="font-semibold text-slate-700">格式/分类</TableHead>
                  <TableHead className="font-semibold text-slate-700">解析能力</TableHead>
                  <TableHead className="font-semibold text-slate-700">Ping 状态</TableHead>
                  <TableHead className="font-semibold text-slate-700">激活状态</TableHead>
                  {extraHeaders}
                </TableRow>
              </TableHeader>
              <TableBody className="divide-y divide-slate-100">
                {items.map((source: any) => {
                  const pingStatus = source.health?.pingStatus || "unknown"
                  const latency = sourceLatency(source)
                  return (
                    <TableRow key={source.pluginId} className={`transition-colors duration-150 hover:bg-slate-50/50 ${!source.enabled ? "bg-slate-50/20 opacity-70" : ""}`}>
                      {selectable && (
                        <TableCell className="py-4 text-center">
                          <Checkbox
                            aria-label={`选择 ${source.name}`}
                            checked={selectedIds.has(source.pluginId)}
                            disabled={selectionDisabled}
                            onCheckedChange={() => onToggleSelected?.(source.pluginId)}
                          />
                        </TableCell>
                      )}
                      <TableCell className="py-4">
                        <div className="flex flex-col">
                          <div className="flex items-center gap-1.5">
                            <Link to={`/console/plugins/${source.pluginId}`} className="text-sm font-semibold text-slate-900 hover:text-blue-600">{source.name}</Link>
                            {source.version && <span className="font-mono text-[10px] font-normal text-slate-400">v{source.version}</span>}
                          </div>
                          <span className="mt-0.5 text-xs text-slate-400">作者: {source.author || source.contributor || source.domain || source.baseUrls?.[0] || "-"}</span>
                        </div>
                      </TableCell>
                      <TableCell className="font-mono text-xs text-slate-500">{source.pluginId}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-1.5">
                          <Badge variant="outline" className="px-1.5 py-0 font-mono text-[10px]">{source.accessType || source.sourceType || "HTTP"}</Badge>
                          <Badge variant="secondary" className="bg-slate-100 px-1.5 py-0 text-[10px] text-slate-600">{sourceCategory(source)}</Badge>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex w-44 flex-wrap gap-0.5">
                          {source.capabilities?.map((capability: string) => (
                            <span key={capability} className={`mr-1 rounded px-1.5 py-0.5 text-[9px] font-medium ${CAPABILITY_COLORS[capability] || "bg-slate-50 text-slate-500"}`}>{CAPABILITY_LABELS[capability] || capability}</span>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex w-28 flex-col gap-1.5">
                          <div className="flex items-center justify-between text-[10px] text-slate-400">
                            <span>状态:</span>
                            <Badge variant={pingStatus === "reachable" ? "success" : pingStatus === "unreachable" ? "destructive" : "outline"} className="px-1.5 py-0 text-[9px]">
                              {pingStatus === "reachable" ? "可达" : pingStatus === "unreachable" ? "不可达" : "未检测"}
                            </Badge>
                          </div>
                          <div className="flex items-center justify-between text-[10px] text-slate-400">
                            <span>延时:</span>
                            <span className={`font-mono font-bold ${latencyClass(latency)}`}>{latency === 0 ? "N/A" : `${latency}ms`}</span>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center">
                          {onToggleEnabled ? (
                            <button
                              type="button"
                              aria-label={source.enabled ? `禁用 ${source.name}` : `启用 ${source.name}`}
                              disabled={toggleEnabledDisabled}
                              onClick={() => onToggleEnabled(source.pluginId, !source.enabled)}
                              className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none ${source.enabled ? "bg-slate-800" : "bg-slate-200"}`}
                            >
                              <span className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${source.enabled ? "translate-x-4" : "translate-x-0"}`} />
                            </button>
                          ) : null}
                          <span className={`text-xs font-medium text-slate-500 ${onToggleEnabled ? "ml-2" : ""}`}>{source.enabled ? "已启用" : "已禁用"}</span>
                        </div>
                      </TableCell>
                      {renderExtraCells?.(source)}
                    </TableRow>
                  )
                })}
                {items.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6 + (selectable ? 1 : 0) + extraColumnCount} className="py-12 text-center text-sm text-slate-400">
                      <AlertCircle className="mx-auto mb-2 h-8 w-8 text-slate-300" />{emptyMessage}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </section>
  )
}
