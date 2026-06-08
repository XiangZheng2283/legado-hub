import { useMemo, useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, ChevronDown, ChevronRight, ExternalLink, Loader2, Search, ShieldAlert } from "lucide-react"

import { api } from "@/lib/api"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

function statusVariant(status?: string) {
  if (status === "completed" || status === "success" || status === "passed") return "success"
  if (status === "running") return "info"
  if (status === "failed" || status === "error" || status === "timeout") return "destructive"
  return "outline"
}

function sourceStatusLabel(event: any) {
  if (!event) return "pending"
  if (event.type === "source_empty") return "empty"
  if (event.type === "source_timeout") return "timeout"
  if (event.type === "source_error") return "error"
  if (event.type === "source_verification_required") return "verification"
  return event.status || "success"
}

function paragraphsFromContent(content?: string, title?: string) {
  const lines = (content || "")
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}|\n/)
    .map((line) => line.trim())
    .filter(Boolean)
  if (lines[0] && title && lines[0] === title.trim()) {
    return lines.slice(1)
  }
  return lines
}

function collectBrowserChallenges(events: any[], job: any) {
  const seen = new Set<string>()
  const challenges: any[] = []
  const add = (challenge: any) => {
    if (!challenge?.sessionId || seen.has(challenge.sessionId)) return
    seen.add(challenge.sessionId)
    challenges.push(challenge)
  }
  ;(job?.browserChallenges || job?.result?.debug?.browserChallenges || []).forEach(add)
  events.forEach((event: any) => {
    add(event?.error?.extra?.browserChallenge)
    ;(event?.error?.extra?.browserChallenges || []).forEach(add)
  })
  return challenges
}

function groupEventResults(events: any[]) {
  const groups = new Map<string, any>()
  events
    .filter((event: any) => event.type === "result" && event.item)
    .forEach((event: any) => {
      const item = {
        ...event.item,
        sourceId: event.item.sourceId || event.sourceId,
        sourceName: event.item.sourceName || event.sourceName,
      }
      const key = `${item.name || ""}::${item.author || ""}`.trim()
      if (!key) return
      const existing = groups.get(key) || {
        candidateId: item.candidateId || key,
        name: item.name || "",
        author: item.author || "",
        latestChapter: item.lastChapter || "",
        score: 0,
        sourceCount: 0,
        items: [],
      }
      if (!existing.items.some((sourceItem: any) => sourceItem.sourceId === item.sourceId && sourceItem.bookUrl === item.bookUrl)) {
        existing.items.push(item)
      }
      existing.sourceCount = existing.items.length
      existing.score = Math.max(existing.score || 0, item.score || 0)
      existing.latestChapter = existing.latestChapter || item.lastChapter || ""
      groups.set(key, existing)
    })
  return Array.from(groups.values()).sort((left, right) => (right.score || 0) - (left.score || 0))
}

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

export function SearchJobs() {
  const queryClient = useQueryClient()
  const [keyword, setKeyword] = useState("")
  const [activeKeyword, setActiveKeyword] = useState("")
  const [jobId, setJobId] = useState<string | null>(null)
  const [pendingJob, setPendingJob] = useState<any>(null)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [bookDetail, setBookDetail] = useState<any>(null)
  const [activeChapterIndex, setActiveChapterIndex] = useState(0)
  const [cookieDrafts, setCookieDrafts] = useState<Record<string, string>>({})
  const [cookieSaveResults, setCookieSaveResults] = useState<Record<string, string>>({})
  const [challengeRetryResults, setChallengeRetryResults] = useState<Record<string, any>>({})
  const [browserHelperResults, setBrowserHelperResults] = useState<Record<string, string>>({})
  const [manualChallenges, setManualChallenges] = useState<any[]>([])

  const createMutation = useMutation({
    mutationFn: (kw: string) => api.createSearchJob(kw),
    onSuccess: (data) => {
      if (!data.jobId) return
      const initialEvents = data.events || []
      setPendingJob(data)
      setJobId(data.jobId)
      queryClient.setQueryData(["search-job", data.jobId], data)
      queryClient.setQueryData(["search-job-events", data.jobId], {
        jobId: data.jobId,
        events: initialEvents,
        nextAfter: initialEvents.length,
      })
      queryClient.setQueryData(["search-job-candidates", data.jobId], {
        jobId: data.jobId,
        items: [],
      })
      queryClient.invalidateQueries({ queryKey: ["search-job", data.jobId] })
      queryClient.invalidateQueries({ queryKey: ["search-job-events", data.jobId] })
    },
  })

  const cancelMutation = useMutation({
    mutationFn: (id: string) => api.cancelSearchJob(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["search-job", jobId] }),
  })

  const verifyMutation = useMutation({
    mutationFn: ({ candidateId, chapterIndex }: { candidateId: string; chapterIndex?: number }) =>
      api.verifySearchCandidate(jobId!, candidateId, chapterIndex || 0),
    onSuccess: (data, variables) => {
      setActiveChapterIndex(variables.chapterIndex || 0)
      setBookDetail(data.result)
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
      setCookieSaveResults((state) => ({
        ...state,
        [variables.challenge.sessionId]: data.saved ? `Cookie 已保存，重新发起搜索或详情请求即可重试。${clearance}` : data.error || "保存失败",
      }))
    },
    onError: (error: any, variables) => {
      setCookieSaveResults((state) => ({
        ...state,
        [variables.challenge.sessionId]: error?.message || "保存失败",
      }))
    },
  })

  const retryChallengeMutation = useMutation({
    mutationFn: (challenge: any) => api.retryBrowserChallengeLiveCheck(challenge.sessionId, activeKeyword || keyword),
    onSuccess: (data, challenge) => {
      const result = data.retryResult || data
      setChallengeRetryResults((state) => ({ ...state, [challenge.sessionId]: result }))
      if (result.browserChallenges?.length) {
        setManualChallenges((state) => [...state, ...result.browserChallenges])
      }
    },
    onError: (error: any, challenge) => {
      setChallengeRetryResults((state) => ({
        ...state,
        [challenge.sessionId]: { status: "failed", diagnostics: [{ message: error?.message || "重试失败" }] },
      }))
    },
  })

  const openBrowserMutation = useMutation({
    mutationFn: (challenge: any) => api.openBrowserChallengeBrowser(challenge.sessionId),
    onSuccess: (data, challenge) => {
      setBrowserHelperResults((state) => ({
        ...state,
        [challenge.sessionId]: data.started ? data.message || "浏览器已启动" : data.error || "启动失败",
      }))
    },
    onError: (error: any, challenge) => {
      setBrowserHelperResults((state) => ({
        ...state,
        [challenge.sessionId]: error?.message || "启动失败",
      }))
    },
  })

  const importBrowserCookiesMutation = useMutation({
    mutationFn: (challenge: any) => api.importBrowserChallengeCookies(challenge.sessionId),
    onSuccess: (data, challenge) => {
      setCookieSaveResults((state) => ({
        ...state,
        [challenge.sessionId]: data.saved
          ? `已导入浏览器 Cookie，可以重试验收。${
              data.clearanceDomains?.length ? `cf_clearance: ${data.clearanceDomains.join(", ")}` : "未检测到 cf_clearance"
            }`
          : data.error || "导入失败",
      }))
    },
    onError: (error: any, challenge) => {
      setCookieSaveResults((state) => ({
        ...state,
        [challenge.sessionId]: error?.message || "导入失败",
      }))
    },
  })

  const { data: jobData } = useQuery({
    queryKey: ["search-job", jobId],
    queryFn: () => api.searchJob(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => (query.state.data?.status === "completed" ? false : 500),
  })

  const { data: candidatesData } = useQuery({
    queryKey: ["search-job-candidates", jobId],
    queryFn: () => api.searchJobCandidates(jobId!),
    enabled: !!jobId,
    refetchInterval: (query) => (jobData?.status === "completed" || query.state.data?.items?.length ? 1500 : 500),
  })

  const { data: eventsData } = useQuery({
    queryKey: ["search-job-events", jobId],
    queryFn: () => api.searchJobEvents(jobId!),
    enabled: !!jobId,
    refetchInterval: jobData?.status === "completed" ? false : 500,
  })

  const events = useMemo(() => eventsData?.events || [], [eventsData?.events])
  const visibleJob = jobData || pendingJob
  const candidates = useMemo(() => {
    const stable = candidatesData?.items || visibleJob?.candidateGroups || visibleJob?.result?.candidateGroups || []
    if (stable.length) return stable
    return groupEventResults(events)
  }, [candidatesData?.items, visibleJob, events])
  const browserChallenges = useMemo(() => {
    const syntheticJob = {
      ...(visibleJob || {}),
      browserChallenges: [...(visibleJob?.browserChallenges || []), ...manualChallenges],
    }
    return collectBrowserChallenges(events, syntheticJob)
  }, [events, visibleJob, manualChallenges])

  const progress = useMemo(() => {
    const summary = events.find((event: any) => event.type === "summary") || {}
    const doneBySource = new Map<string, any>()
    events.forEach((event: any) => {
      if (["source_done", "source_empty", "source_timeout", "source_error", "source_verification_required"].includes(event.type)) {
        doneBySource.set(event.sourceId || `${event.type}-${doneBySource.size}`, event)
      }
    })
    const running = events
      .filter((event: any) => event.type === "source_start" && !doneBySource.has(event.sourceId))
      .map((event: any) => ({ id: event.sourceId, name: event.sourceName }))
    const completed = visibleJob?.completedCount ?? doneBySource.size
    const total = visibleJob?.sourceCount ?? summary.sourceCount ?? 0
    const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0
    return { completed, total, percent, running, doneBySource }
  }, [events, visibleJob])

  const handleSearch = () => {
    const value = keyword.trim()
    if (!value) return
    setActiveKeyword(value)
    setJobId(null)
    setExpanded({})
    setBookDetail(null)
    setActiveChapterIndex(0)
    setPendingJob({
      status: "starting",
      keyword: value,
      sourceCount: 0,
      completedCount: 0,
      successCount: 0,
      errorCount: 0,
      elapsedMs: 0,
      candidateGroups: [],
    })
    createMutation.mutate(value)
  }

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">搜索工作台</h1>
        <p className="text-sm text-muted-foreground">按书籍聚合结果，并实时显示当前调用的书源。</p>
      </div>

      <Card>
        <CardContent className="space-y-4 p-4">
          <div className="flex flex-col gap-2 md:flex-row">
            <Input
              placeholder="输入书名或关键词"
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && handleSearch()}
              className="h-10 flex-1"
            />
            <div className="flex gap-2">
              <Button onClick={handleSearch} disabled={createMutation.isPending} className="h-10">
                {createMutation.isPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Search className="mr-2 h-4 w-4" />}
                搜索
              </Button>
              {visibleJob?.status === "running" && jobId && (
                <Button variant="outline" onClick={() => cancelMutation.mutate(jobId)} className="h-10">
                  取消
                </Button>
              )}
            </div>
          </div>

          {visibleJob && (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={statusVariant(visibleJob.status) as any}>{visibleJob.status}</Badge>
                  <span className="font-medium">{progress.completed}/{progress.total} 书源</span>
                  <span className="text-muted-foreground">成功 {visibleJob.successCount || 0}</span>
                  <span className="text-muted-foreground">失败 {visibleJob.errorCount || 0}</span>
                  <span className="text-muted-foreground">耗时 {visibleJob.elapsedMs || 0}ms</span>
                </div>
                <div className="flex flex-wrap items-center gap-1">
                  <span className="text-muted-foreground">当前</span>
                  {progress.running.length === 0 ? (
                    <Badge variant="outline">{visibleJob.status === "completed" ? "已完成" : "等待调度"}</Badge>
                  ) : (
                    progress.running.map((source: any) => (
                      <Badge key={`${source.id}-${source.name}`} variant="info">{source.name || source.id}</Badge>
                    ))
                  )}
                </div>
              </div>
              <div className="h-2 overflow-hidden rounded bg-muted">
                <div className="h-full bg-primary transition-all" style={{ width: `${progress.percent}%` }} />
              </div>
              {browserChallenges.length > 0 && (
                <div className="space-y-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950">
                  <div className="flex items-center gap-2 font-medium">
                    <ShieldAlert className="h-4 w-4" />
                    需要浏览器验证
                  </div>
                  <div className="text-xs text-amber-900">
                    以下书源返回了 Cloudflare 或浏览器挑战。打开验证页，在真实浏览器完成验证并保存 Cookie 后，重新发起当前搜索或详情请求。
                  </div>
                  <div className="grid gap-2">
                    {browserChallenges.map((challenge: any) => (
                      <div key={challenge.sessionId} className="flex flex-col gap-2 rounded border border-amber-200 bg-background p-2 md:flex-row md:items-center md:justify-between">
                        <div className="min-w-0">
                          <div className="font-medium">{challenge.sourceName || challenge.sourceId}</div>
                          <div className="truncate text-xs text-muted-foreground">{challenge.openUrl}</div>
                          <div className="text-xs text-muted-foreground">会话 {challenge.sessionId}</div>
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
                            disabled={importBrowserCookiesMutation.isPending}
                            onClick={() => importBrowserCookiesMutation.mutate(challenge)}
                          >
                            导入浏览器 Cookie
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
                            {retryChallengeMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <BookOpen className="h-4 w-4" />}
                            重试验收
                          </Button>
                        </div>
                        <textarea
                          value={cookieDrafts[challenge.sessionId] || ""}
                          onChange={(event) =>
                            setCookieDrafts((state) => ({
                              ...state,
                              [challenge.sessionId]: event.target.value,
                            }))
                          }
                          placeholder='粘贴浏览器 cookies JSON，或 cf_clearance=...; key=value'
                          className="min-h-16 w-full rounded-md border bg-background px-3 py-2 text-xs outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring md:col-span-2"
                        />
                        {cookieSaveResults[challenge.sessionId] && (
                          <div className="text-xs text-muted-foreground md:col-span-2">
                            {cookieSaveResults[challenge.sessionId]}
                          </div>
                        )}
                        {browserHelperResults[challenge.sessionId] && (
                          <div className="text-xs text-muted-foreground md:col-span-2">
                            {browserHelperResults[challenge.sessionId]}
                          </div>
                        )}
                        {challengeRetryResults[challenge.sessionId] && (
                          <div className="rounded border bg-muted/40 p-2 text-xs md:col-span-2">
                            <div className="font-medium">
                              验收状态: {challengeRetryResults[challenge.sessionId].status || "unknown"}
                            </div>
                            <div className="text-muted-foreground">
                              排行榜正文 {challengeRetryResults[challenge.sessionId].explore?.contentLength || 0} 字；
                              搜索结果 {challengeRetryResults[challenge.sessionId].search?.count || 0}；
                              目录 {challengeRetryResults[challenge.sessionId].toc?.count || 0} 章；
                              正文 {challengeRetryResults[challenge.sessionId].chapter?.contentLength || 0} 字
                            </div>
                            {(challengeRetryResults[challenge.sessionId].diagnostics || []).slice(0, 2).map((item: any, index: number) => (
                              <div key={index} className="text-destructive">
                                {item.stage || "runtime"} · {item.code || "error"} · {item.message}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      <div className="rounded-md border bg-background">
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div>
            <div className="text-sm font-semibold">书籍结果</div>
            <div className="text-xs text-muted-foreground">每本书下方展开显示命中的书源和验证入口</div>
          </div>
          <Badge variant="outline">{candidates.length} 本</Badge>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead>书名</TableHead>
              <TableHead>作者</TableHead>
              <TableHead>最新章节</TableHead>
              <TableHead>命中书源</TableHead>
              <TableHead>评分</TableHead>
              <TableHead className="text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {candidates.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="h-28 text-center text-sm text-muted-foreground">
                  {visibleJob ? "搜索进行中，结果会实时出现" : "输入关键词后开始搜索"}
                </TableCell>
              </TableRow>
            )}
            {candidates.map((candidate: any) => {
              const isOpen = expanded[candidate.candidateId]
              return (
                <>
                  <TableRow key={candidate.candidateId}>
                    <TableCell>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setExpanded((state) => ({ ...state, [candidate.candidateId]: !isOpen }))}
                      >
                        {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </Button>
                    </TableCell>
                    <TableCell className="font-medium">{candidate.name || "-"}</TableCell>
                    <TableCell>{candidate.author || "-"}</TableCell>
                    <TableCell className="max-w-64 truncate">{candidate.latestChapter || "-"}</TableCell>
                    <TableCell>{candidate.sourceCount || candidate.items?.length || 0}</TableCell>
                    <TableCell>{candidate.score || 0}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={verifyMutation.isPending}
                        onClick={() => verifyMutation.mutate({ candidateId: candidate.candidateId })}
                      >
                        {verifyMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <BookOpen className="h-4 w-4" />}
                        查看详情
                      </Button>
                    </TableCell>
                  </TableRow>
                  {isOpen && (
                    <TableRow key={`${candidate.candidateId}-sources`}>
                      <TableCell />
                      <TableCell colSpan={6}>
                        <div className="rounded-md border bg-muted/30 p-2">
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead>书源</TableHead>
                                <TableHead>插件 ID</TableHead>
                                <TableHead>原始书名</TableHead>
                                <TableHead>原始作者</TableHead>
                                <TableHead>最新章节</TableHead>
                                <TableHead>状态</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {(candidate.items || []).map((item: any) => {
                                const sourceEvent = progress.doneBySource.get(item.sourceId)
                                const label = sourceStatusLabel(sourceEvent)
                                return (
                                  <TableRow key={item.candidateId || `${item.sourceId}-${item.bookUrl}`}>
                                    <TableCell>{item.sourceName || item.sourceId}</TableCell>
                                    <TableCell className="font-mono text-xs">{item.sourceId}</TableCell>
                                    <TableCell>{item.name || "-"}</TableCell>
                                    <TableCell>{item.author || "-"}</TableCell>
                                    <TableCell className="max-w-60 truncate">{item.lastChapter || "-"}</TableCell>
                                    <TableCell>
                                      <Badge variant={statusVariant(label) as any}>{label}</Badge>
                                    </TableCell>
                                  </TableRow>
                                )
                              })}
                            </TableBody>
                          </Table>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </>
              )
            })}
          </TableBody>
        </Table>
      </div>

      {events.length > 0 && (
        <div className="rounded-md border bg-background">
          <div className="border-b px-4 py-3 text-sm font-semibold">书源进度明细</div>
          <ScrollArea className="h-56 px-4 py-3">
            <div className="space-y-1 text-xs">
              {events
                .filter((event: any) => event.type !== "result" && event.type !== "candidate_grouped")
                .slice(-80)
                .map((event: any, index: number) => (
                  <div key={`${event.type}-${index}`} className="flex flex-wrap items-center gap-2 rounded bg-muted px-2 py-1">
                    <Badge variant="outline">{event.type}</Badge>
                    {event.sourceName && <span>{event.sourceName}</span>}
                    {event.resultCount !== undefined && <span>结果 {event.resultCount}</span>}
                    {event.completedCount !== undefined && <span>{event.completedCount}/{event.sourceCount}</span>}
                    {event.error && <span className="text-destructive">{JSON.stringify(event.error).slice(0, 120)}</span>}
                  </div>
                ))}
            </div>
          </ScrollArea>
        </div>
      )}

      <Dialog open={!!bookDetail} onOpenChange={(open) => !open && setBookDetail(null)}>
        <DialogContent className="max-h-[92vh] max-w-6xl overflow-hidden p-0">
          <DialogHeader>
            <DialogTitle className="px-6 pt-6">小说详情</DialogTitle>
          </DialogHeader>
          {bookDetail && (
            <div className="grid min-h-0 gap-0 border-t text-sm lg:grid-cols-[1fr_320px]">
              <ScrollArea className="max-h-[78vh]">
                <div className="space-y-5 p-6">
                  <div className="grid gap-4 sm:grid-cols-[112px_1fr]">
                    <div className="h-40 w-28 overflow-hidden rounded border bg-muted">
                      {bookDetail.detail?.coverUrl ? (
                        <img
                          src={bookDetail.detail.coverUrl}
                          alt={bookDetail.detail?.name || bookDetail.selectedCandidate?.name || "cover"}
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-xs text-muted-foreground">无封面</div>
                      )}
                    </div>
                    <div className="min-w-0 space-y-3">
                      <div>
                        <h2 className="text-2xl font-semibold">
                          {bookDetail.detail?.name || bookDetail.selectedCandidate?.name || "-"}
                        </h2>
                        <div className="mt-2 flex flex-wrap items-center gap-2 text-muted-foreground">
                          <span>{bookDetail.detail?.author || bookDetail.selectedCandidate?.author || "未知作者"}</span>
                          <Badge variant={statusVariant(bookDetail.status) as any}>{bookDetail.status}</Badge>
                          <Badge variant="outline">{bookDetail.selectedCandidate?.sourceName || bookDetail.selectedCandidate?.sourceId || "未知书源"}</Badge>
                        </div>
                      </div>
                      <div className="grid gap-2 text-muted-foreground sm:grid-cols-3">
                        <div>目录: {bookDetail.toc?.chapterCount || 0} 章</div>
                        <div>正文: {bookDetail.chapter?.contentLength || 0} 字</div>
                        <div>字数: {bookDetail.detail?.wordCountText || bookDetail.detail?.wordCount || "未知"}</div>
                      </div>
                      <div className="grid gap-1 text-muted-foreground">
                        <div>最新: {bookDetail.detail?.lastChapter || bookDetail.selectedCandidate?.lastChapter || "-"}</div>
                        <div className="truncate">来源: {bookDetail.detail?.bookUrl || bookDetail.selectedCandidate?.bookUrl || "-"}</div>
                      </div>
                      <p className="line-clamp-4 leading-7 text-muted-foreground">
                        {bookDetail.detail?.intro || "暂无简介"}
                      </p>
                    </div>
                  </div>

                  <div className="rounded-md border bg-[#f8f3e8] px-8 py-7 text-[#2f261d]">
                    <div className="mb-6 text-center text-xl font-semibold">
                      {bookDetail.chapter?.title || "请选择章节"}
                    </div>
                    <div className="space-y-5 text-lg leading-9">
                      {paragraphsFromContent(bookDetail.chapter?.content, bookDetail.chapter?.title).length > 0 ? (
                        paragraphsFromContent(bookDetail.chapter?.content, bookDetail.chapter?.title).map((paragraph, index) => (
                          <p key={index} className="indent-8">
                            {paragraph}
                          </p>
                        ))
                      ) : (
                        <p className="text-center text-sm text-muted-foreground">暂无正文</p>
                      )}
                    </div>
                  </div>

                  {bookDetail.diagnostics?.length > 0 && (
                    <div className="space-y-1">
                      <div className="font-medium">诊断</div>
                      {bookDetail.diagnostics.map((item: any, index: number) => (
                        <div key={index} className="rounded bg-muted px-2 py-1 text-xs">
                          {item.stage} · {item.code} · {item.message}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </ScrollArea>

              <div className="border-l bg-muted/20">
                <div className="border-b px-4 py-3">
                  <div className="font-semibold">目录</div>
                  <div className="text-xs text-muted-foreground">点击章节可切换阅读内容</div>
                </div>
                <ScrollArea className="h-[72vh]">
                  <div className="space-y-1 p-3">
                    {(bookDetail.search?.groups?.[0]?.items || []).length > 1 && (
                      <div className="mb-3 rounded border bg-background p-2 text-xs text-muted-foreground">
                        当前来源: {bookDetail.selectedCandidate?.sourceName || bookDetail.selectedCandidate?.sourceId}
                      </div>
                    )}
                    {(bookDetail.toc?.items || bookDetail.toc?.chapters || []).length === 0 && (
                      <div className="p-4 text-center text-muted-foreground">暂无目录</div>
                    )}
                    {(bookDetail.toc?.items || bookDetail.toc?.chapters || []).map((chapter: any, index: number) => (
                      <Button
                        key={chapter.chapterUrl || index}
                        variant={activeChapterIndex === index ? "secondary" : "ghost"}
                        className="h-auto w-full justify-start whitespace-normal px-3 py-2 text-left"
                        disabled={verifyMutation.isPending}
                        onClick={() =>
                          verifyMutation.mutate({
                            candidateId: bookDetail.selectedCandidate?.candidateId,
                            chapterIndex: index,
                          })
                        }
                      >
                        <span className="mr-2 text-xs text-muted-foreground">{index + 1}</span>
                        <span>{chapter.title || `第 ${index + 1} 章`}</span>
                      </Button>
                    ))}
                  </div>
                </ScrollArea>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
