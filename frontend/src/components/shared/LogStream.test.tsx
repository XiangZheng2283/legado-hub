import { act, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { LogStream } from "@/components/shared/LogStream"

class FakeEventSource {
  static current: FakeEventSource | null = null
  static instances: FakeEventSource[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  readonly url: string
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.current = this
    FakeEventSource.instances.push(this)
  }

  close() {
    this.closed = true
  }
}

describe("LogStream", () => {
  beforeEach(() => {
    FakeEventSource.current = null
    FakeEventSource.instances = []
    vi.stubGlobal("EventSource", FakeEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("keeps automatic scrolling inside the log container", async () => {
    const onRecord = vi.fn()
    render(<div data-testid="page-scroll"><LogStream url="/logs" onRecord={onRecord} /></div>)
    const log = screen.getByRole("log")
    const pageScroll = screen.getByTestId("page-scroll")
    Object.defineProperty(log, "scrollHeight", { configurable: true, value: 320 })
    Object.defineProperty(log, "clientHeight", { configurable: true, value: 100 })
    let scrollTop = 0
    Object.defineProperty(log, "scrollTop", {
      configurable: true,
      get: () => scrollTop,
      set: (value: number) => {
        scrollTop = Math.min(value, 220)
      },
    })

    act(() => {
      FakeEventSource.current?.onmessage?.({ data: JSON.stringify({ ts: "2026-07-17T08:00:00Z", event: "chapter_ready" }) })
    })

    await waitFor(() => expect(screen.getByText("chapter_ready")).toBeInTheDocument())
    expect(onRecord).toHaveBeenCalledWith({ ts: "2026-07-17T08:00:00Z", event: "chapter_ready" })
    expect(log.scrollTop).toBe(220)
    expect(pageScroll.scrollTop).toBe(0)
  })

  it("does not pull the log back down after the user scrolls up", async () => {
    render(<LogStream url="/logs" />)
    const log = screen.getByRole("log")
    Object.defineProperty(log, "scrollHeight", { configurable: true, value: 400 })
    Object.defineProperty(log, "clientHeight", { configurable: true, value: 100 })
    log.scrollTop = 80
    fireEvent.scroll(log)

    act(() => {
      FakeEventSource.current?.onmessage?.({ data: JSON.stringify({ ts: "2026-07-17T08:00:00Z", event: "chapter_ready" }) })
    })

    await waitFor(() => expect(screen.getByText("chapter_ready")).toBeInTheDocument())
    expect(log.scrollTop).toBe(80)
  })

  it("closes stale connections when the URL changes or the component unmounts", () => {
    const { rerender, unmount } = render(<LogStream url="/logs-a" />)
    const first = FakeEventSource.current

    expect(first?.url).toBe("/logs-a")
    expect(first?.closed).toBe(false)

    rerender(<LogStream url="/logs-b" />)
    const second = FakeEventSource.current

    expect(first?.closed).toBe(true)
    expect(second).not.toBe(first)
    expect(second?.url).toBe("/logs-b")
    expect(second?.closed).toBe(false)

    unmount()

    expect(second?.closed).toBe(true)
    expect(FakeEventSource.instances).toHaveLength(2)
  })

  it("uses the latest record callback without reconnecting", () => {
    const firstHandler = vi.fn()
    const secondHandler = vi.fn()
    const { rerender } = render(<LogStream url="/logs" onRecord={firstHandler} />)
    const source = FakeEventSource.current

    rerender(<LogStream url="/logs" onRecord={secondHandler} />)
    act(() => {
      source?.onmessage?.({ data: JSON.stringify({ ts: "2026-07-17T08:00:00Z", event: "chapter_ready" }) })
    })

    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.current).toBe(source)
    expect(firstHandler).not.toHaveBeenCalled()
    expect(secondHandler).toHaveBeenCalledTimes(1)
  })
})
