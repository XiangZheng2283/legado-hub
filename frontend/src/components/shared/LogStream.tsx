import { useCallback, useEffect, useRef, useState } from "react"

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
}

const MAX_LINES = 2000

function logLevel(record: LogRecord): string {
  if (record.errorCode || record.errorMessage) return "ERROR"
  if (record.event?.toLowerCase().includes("warn") || record.stage?.toLowerCase().includes("warn")) return "WARN"
  return "INFO"
}

function logColor(level: string): string {
  if (level === "ERROR") return "text-rose-400"
  if (level === "WARN") return "text-amber-400"
  return "text-emerald-400"
}

function formatLog(record: LogRecord): string {
  const parts: string[] = [record.event]
  if (record.chapterIndex != null) parts.push(`第${record.chapterIndex}章`)
  if (record.stage) parts.push(record.stage)
  if (record.errorMessage) parts.push(record.errorMessage)
  if (record.payload && Object.keys(record.payload).length > 0) parts.push(JSON.stringify(record.payload, null, 0))
  return parts.join(" ")
}

export function LogStream({ url }: LogStreamProps) {
  const [lines, setLines] = useState<LogRecord[]>([])
  const [status, setStatus] = useState<"connecting" | "open" | "closed" | "error">("connecting")
  const pausedRef = useRef(false)
  const esRef = useRef<EventSource | null>(null)
  const pendingRef = useRef<LogRecord[]>([])
  const bottomRef = useRef<HTMLDivElement | null>(null)

  const flushPending = useCallback(() => {
    if (pendingRef.current.length === 0) return
    const batch = pendingRef.current.splice(0, pendingRef.current.length)
    setLines((prev) => {
      const next = [...prev, ...batch]
      return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next
    })
  }, [])

  useEffect(() => {
    if (!url || typeof EventSource === "undefined") return

    const es = new EventSource(url, { withCredentials: true })
    es.onopen = () => setStatus("open")
    es.onmessage = (event) => {
      try {
        const record = JSON.parse(event.data) as LogRecord
        pendingRef.current.push(record)
        if (!pausedRef.current) {
          flushPending()
        }
      } catch {
        // ignore malformed records
      }
    }
    es.onerror = () => setStatus("error")
    esRef.current = es

    return () => {
      es.close()
      esRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url])

  useEffect(() => {
    if (!pausedRef.current && pendingRef.current.length > 0) {
      flushPending()
    }
  }, [flushPending])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [lines])

  const isEmpty = lines.length === 0 && status !== "error"

  return (
    <div className="h-48 overflow-y-auto bg-slate-900 p-4 font-mono text-xs">
      <div className="space-y-1">
        {isEmpty ? (
          <div className="text-emerald-400/60">等待日志...</div>
        ) : (
          lines.map((line, index) => {
            const level = logLevel(line)
            return (
              <div key={`${line.ts}-${index}`} className={`break-all ${logColor(level)}`}>
                <span className="text-slate-400">[{level}] {new Date(line.ts).toLocaleString("zh-CN")} -</span>{" "}
                {formatLog(line)}
              </div>
            )
          })
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
