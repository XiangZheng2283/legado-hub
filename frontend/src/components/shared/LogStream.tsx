import { useEffect, useRef, useState } from "react"

interface LogRecord {
  ts: string
  event: string
  bookId?: string
  chapterIndex?: number | null
  stage?: string | null
  errorCode?: string | null
  errorMessage?: string | null
  payload?: Record<string, unknown> | null
}

interface LogStreamProps {
  url: string
  onRecord?: (record: LogRecord) => void
}

const MAX_LINES = 2000

function logLevel(record: LogRecord): string {
  if (record.errorCode || record.errorMessage) return "ERROR"
  if (record.event?.toLowerCase().includes("warn") || record.stage?.toLowerCase().includes("warn")) return "WARN"
  return "INFO"
}

function logLevelClass(level: string): string {
  if (level === "ERROR") return "border-rose-200 bg-rose-50 text-rose-700"
  if (level === "WARN") return "border-amber-200 bg-amber-50 text-amber-700"
  return "border-emerald-200 bg-emerald-50 text-emerald-700"
}

function formatLog(record: LogRecord): string {
  const parts: string[] = [record.event]
  if (record.chapterIndex != null) parts.push(`第${record.chapterIndex}章`)
  if (record.stage) parts.push(record.stage)
  if (record.errorMessage) parts.push(record.errorMessage)
  if (record.payload && Object.keys(record.payload).length > 0) parts.push(JSON.stringify(record.payload, null, 0))
  return parts.join(" ")
}

export function LogStream({ url, onRecord }: LogStreamProps) {
  const [lines, setLines] = useState<LogRecord[]>([])
  const [status, setStatus] = useState<"connecting" | "open" | "error">("connecting")
  const containerRef = useRef<HTMLDivElement | null>(null)
  const stickToBottomRef = useRef(true)
  const onRecordRef = useRef(onRecord)

  useEffect(() => {
    onRecordRef.current = onRecord
  }, [onRecord])

  useEffect(() => {
    if (!url || typeof EventSource === "undefined") return

    const es = new EventSource(url, { withCredentials: true })
    es.onopen = () => setStatus("open")
    es.onmessage = (event) => {
      try {
        const record = JSON.parse(event.data) as LogRecord
        setLines((previous) => {
          const next = [...previous, record]
          return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next
        })
        onRecordRef.current?.(record)
      } catch {
        // ignore malformed records
      }
    }
    es.onerror = () => setStatus("error")

    return () => {
      es.close()
    }
  }, [url])

  useEffect(() => {
    const container = containerRef.current
    if (container && stickToBottomRef.current) {
      container.scrollTop = container.scrollHeight
    }
  }, [lines])

  const isEmpty = lines.length === 0 && status !== "error"

  return (
    <div
      ref={containerRef}
      role="log"
      onScroll={() => {
        const container = containerRef.current
        if (!container) return
        stickToBottomRef.current = container.scrollHeight - container.scrollTop - container.clientHeight <= 24
      }}
      className="h-48 overflow-y-auto bg-slate-50 px-4 py-3 font-mono text-xs text-slate-700"
    >
      <div className="space-y-1.5">
        {isEmpty ? (
          <div className="py-2 text-slate-400">{status === "connecting" ? "正在连接日志..." : "等待新日志..."}</div>
        ) : status === "error" && lines.length === 0 ? (
          <div className="py-2 text-rose-600">日志连接中断，等待自动重连。</div>
        ) : (
          lines.map((line, index) => {
            const level = logLevel(line)
            return (
              <div key={`${line.ts}-${index}`} className="grid grid-cols-[auto_1fr] items-start gap-x-2 gap-y-1 border-b border-slate-200/70 py-1.5 last:border-0 sm:flex">
                <span className={`inline-flex w-12 shrink-0 justify-center rounded border px-1 py-0.5 text-[10px] font-semibold ${logLevelClass(level)}`}>{level}</span>
                <span className="shrink-0 py-0.5 text-slate-400">{new Date(line.ts).toLocaleString("zh-CN")}</span>
                <span className="col-span-2 min-w-0 break-words py-0.5 text-slate-700 sm:col-auto">{formatLog(line)}</span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
