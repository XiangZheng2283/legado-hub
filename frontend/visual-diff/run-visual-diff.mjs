import { spawn } from "node:child_process"
import { existsSync } from "node:fs"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { chromium } from "playwright"

const __dirname = dirname(fileURLToPath(import.meta.url))
const frontendDir = resolve(__dirname, "..")
const repoDir = resolve(frontendDir, "..")
const designDir = resolve(repoDir, "untitled")
const outputRoot = resolve(__dirname, "output")

const ports = { current: 5177, design: 5178 }
const npmCmd = process.platform === "win32" ? "npm.cmd" : "npm"
const useShell = process.platform === "win32"

const viewports = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
]

const pages = [
  {
    id: "dashboard",
    title: "仪表盘",
    designPath: "/#/",
    currentPath: "/console",
  },
  {
    id: "subscriptions-results",
    title: "订阅搜索结果",
    designPath: "/#/subscriptions",
    currentPath: "/console/subscription",
    prepare: async (page) => {
      await page.getByPlaceholder(/搜索你想看的小说或作者/).fill("深海")
      await page.keyboard.press("Enter")
      await page.waitForTimeout(1800)
    },
  },
  {
    id: "library",
    title: "书库",
    designPath: "/#/library",
    currentPath: "/console/library",
  },
  {
    id: "book-detail",
    title: "书籍详情",
    designPath: "/#/library/2",
    currentPath: "/console/library/book-2",
  },
  {
    id: "search-workbench",
    title: "搜索工作台",
    designPath: "/#/search-workbench",
    currentPath: "/console/search",
    prepareCurrent: async (page) => {
      await page.getByPlaceholder(/输入测试关键词/).fill("深海")
      await page.getByRole("button", { name: /调试/ }).click()
      await page.waitForTimeout(500)
    },
  },
  {
    id: "sources",
    title: "书源管理",
    designPath: "/#/sources",
    currentPath: "/console/plugins",
  },
  {
    id: "settings",
    title: "系统设置",
    designPath: "/#/settings",
    currentPath: "/console/settings",
  },
]

const now = new Date()
  .toISOString()
  .replace(/[:.]/g, "-")
  .replace("T", "_")
  .replace("Z", "")
const outputDir = join(outputRoot, now)

const books = [
  {
    aggregateBookId: "book-1",
    id: "1",
    displayName: "深海余烬",
    displayAuthor: "远瞳",
    name: "深海余烬",
    author: "远瞳",
    coverUrl: "https://via.placeholder.com/300x400?text=深海",
    intro:
      "在那一天，浓雾封锁了一切。在那一天，他成为了一艘幽灵船的船长。在那一天，他跨过浓雾，直面了一个被彻底颠覆而又支离破碎的世界。",
    wordCount: "320万字",
    totalChapters: 812,
    processedChapters: 812,
    visibleProcessedChapters: 812,
    failedChapters: 0,
    status: "completed",
    bookStatus: "ongoing",
    lastChapterTitle: "第812章 归来",
    primarySourceName: "起点中文网",
  },
  {
    aggregateBookId: "book-2",
    id: "2",
    displayName: "道诡异仙",
    displayAuthor: "狐尾的笔",
    name: "道诡异仙",
    author: "狐尾的笔",
    coverUrl: "https://via.placeholder.com/300x400?text=道诡",
    intro:
      "诡异的天道，异常的仙佛，是真？是假？陷入迷惘的李火旺无法分辨。可让他无法分辨的不仅仅只是这些。还有他自己，他病了，病的很重。",
    wordCount: "280万字",
    totalChapters: 1100,
    processedChapters: 540,
    visibleProcessedChapters: 540,
    failedChapters: 50,
    status: "active",
    bookStatus: "completed",
    lastChapterTitle: "第540章 坐忘道",
    primarySourceName: "起点中文网",
  },
  {
    aggregateBookId: "book-3",
    id: "3",
    displayName: "神秘复苏",
    displayAuthor: "佛前献花",
    name: "神秘复苏",
    author: "佛前献花",
    coverUrl: "https://via.placeholder.com/300x400?text=神秘",
    intro: "五浊恶世，地狱已空，厉鬼复苏，人间如狱。",
    wordCount: "530万字",
    totalChapters: 1540,
    processedChapters: 300,
    visibleProcessedChapters: 300,
    failedChapters: 1,
    status: "error",
    bookStatus: "completed",
    lastChapterTitle: "第300章 鬼眼",
    primarySourceName: "起点中文网",
  },
  {
    aggregateBookId: "book-4",
    id: "4",
    displayName: "黎明之剑",
    displayAuthor: "远瞳",
    name: "黎明之剑",
    author: "远瞳",
    coverUrl: "https://via.placeholder.com/300x400?text=黎明",
    intro:
      "高文穿越了，但穿越的时候稍微出了点问题。在某个异界大陆上空飘了十几万年之后，他觉得自己可能需要一具身体。",
    wordCount: "450万字",
    totalChapters: 1600,
    processedChapters: 1600,
    visibleProcessedChapters: 1600,
    failedChapters: 0,
    status: "archived",
    bookStatus: "completed",
    lastChapterTitle: "尾声",
    primarySourceName: "纵横中文网",
  },
]

const searchCards = [
  {
    candidateId: "1",
    aggregateBookId: "book-1",
    name: "深海余烬",
    author: "远瞳",
    coverUrl: "https://via.placeholder.com/300x400?text=深海",
    intro: books[0].intro,
    wordCount: "320万字",
    chapterCount: 812,
    completed: false,
    alreadyIngested: true,
    sourceSummary: [{ sourceName: "起点中文网" }],
  },
  {
    candidateId: "2",
    aggregateBookId: "book-2",
    name: "道诡异仙",
    author: "狐尾的笔",
    coverUrl: "https://via.placeholder.com/300x400?text=道诡",
    intro: books[1].intro,
    wordCount: "280万字",
    chapterCount: 1100,
    completed: true,
    alreadyIngested: false,
    sourceSummary: [{ sourceName: "起点中文网" }],
  },
  {
    candidateId: "3",
    name: "大奉打更人",
    author: "卖报小郎君",
    coverUrl: "https://via.placeholder.com/300x400?text=大奉",
    intro: "这个世界，有儒；有道；有佛；有妖；有术士。",
    wordCount: "480万字",
    chapterCount: 1205,
    completed: true,
    alreadyIngested: false,
    sourceSummary: [{ sourceName: "起点中文网" }],
  },
  {
    candidateId: "4",
    name: "赤心巡天",
    author: "情何以甚",
    coverUrl: "https://via.placeholder.com/300x400?text=赤心",
    intro: "山河千里写伏尸，乾坤百年描饿殍。天地至公如无情，我有赤心一颗，以巡天。",
    wordCount: "650万字",
    chapterCount: 2150,
    completed: false,
    alreadyIngested: true,
    aggregateBookId: "book-4",
    sourceSummary: [{ sourceName: "起点中文网" }],
  },
]

const plugins = [
  {
    pluginId: "com.qidian.sandbox",
    name: "起点中文网 (官方备份)",
    accessType: "JSON",
    capabilities: ["search", "detail", "toc", "chapter", "auth"],
    enabled: true,
    official: false,
    author: "阅读官方团队",
    tags: ["小说"],
    version: "1.4.2",
    health: { lastTestResult: "pass", pingStatus: "reachable", pingLatencyMs: 32 },
  },
  {
    pluginId: "com.biquge.general",
    name: "笔趣阁 (通用多路合并)",
    accessType: "HTML",
    capabilities: ["search", "detail", "toc", "chapter"],
    enabled: true,
    official: false,
    author: "社区协作者",
    tags: ["小说"],
    version: "2.1.0",
    health: { lastTestResult: "pass", pingStatus: "reachable", pingLatencyMs: 124, successRate: 94.5 },
  },
  {
    pluginId: "com.copymanga",
    name: "拷贝漫画 (高清镜像)",
    accessType: "JSON",
    capabilities: ["search", "detail", "toc", "chapter"],
    enabled: true,
    official: false,
    author: "MangaFan",
    tags: ["漫画"],
    version: "1.0.5",
    health: { lastTestResult: "pass", pingStatus: "reachable", pingLatencyMs: 184, successRate: 98.1 },
  },
  {
    pluginId: "net.wenku8",
    name: "轻小说文库 (Wenku8)",
    accessType: "HTML",
    capabilities: ["search", "detail", "toc", "chapter", "auth"],
    enabled: true,
    official: false,
    author: "WenkuLover",
    tags: ["轻小说"],
    version: "1.1.2",
    health: { lastTestResult: "untested", pingStatus: "reachable", pingLatencyMs: 245, successRate: 91.2 },
  },
  {
    pluginId: "com.tadu",
    name: "塔读文学 (免广告规则)",
    accessType: "JSON",
    capabilities: ["search", "detail", "toc"],
    enabled: false,
    official: false,
    author: "黑白调",
    tags: ["小说"],
    version: "1.0.1",
    health: { lastTestResult: "untested", pingStatus: "unknown", pingLatencyMs: 0, successRate: 0 },
  },
  {
    pluginId: "net.unknown.novel",
    name: "未知小站 (测试源)",
    accessType: "HTML",
    capabilities: ["search", "chapter", "auth"],
    enabled: true,
    official: false,
    author: "匿名贡献者",
    tags: ["小说"],
    version: "0.8.0",
    health: { lastTestResult: "fail", pingStatus: "unreachable", pingLatencyMs: 890, successRate: 35.8 },
  },
]

function run(command, args, cwd, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      cwd,
      env: { ...process.env, DISABLE_HMR: "true", BROWSER: "none", ...options.env },
      stdio: options.stdio ?? "pipe",
      shell: useShell,
    })
    let output = ""
    child.stdout?.on("data", (data) => {
      output += data.toString()
      options.onOutput?.(data.toString())
    })
    child.stderr?.on("data", (data) => {
      output += data.toString()
      options.onOutput?.(data.toString())
    })
    child.on("error", reject)
    child.on("close", (code) => {
      if (code === 0) resolvePromise(output)
      else reject(new Error(`${command} ${args.join(" ")} failed with ${code}\n${output}`))
    })
  })
}

async function ensureDeps(projectDir) {
  const viteBin = join(projectDir, "node_modules", ".bin", process.platform === "win32" ? "vite.cmd" : "vite")
  if (existsSync(viteBin)) return
  console.log(`[deps] ${projectDir} 缺少 node_modules，执行 npm ci --no-audit --no-fund`)
  await run(npmCmd, ["ci", "--no-audit", "--no-fund"], projectDir, { stdio: "inherit" })
}

function startVite(projectDir, port) {
  const viteEntry = join(projectDir, "node_modules", "vite", "bin", "vite.js")
  const child = spawn(process.execPath, [viteEntry, "--host", "127.0.0.1", "--port", String(port)], {
    cwd: projectDir,
    env: { ...process.env, DISABLE_HMR: "true", BROWSER: "none" },
    stdio: "pipe",
    shell: false,
  })
  child.stdout.on("data", (data) => process.stdout.write(`[vite:${port}] ${data}`))
  child.stderr.on("data", (data) => process.stderr.write(`[vite:${port}] ${data}`))
  return child
}

async function waitFor(url, timeoutMs = 30000) {
  const deadline = Date.now() + timeoutMs
  let lastError
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url)
      if (res.ok) return
      lastError = new Error(`HTTP ${res.status}`)
    } catch (error) {
      lastError = error
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 500))
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError?.message || "unknown error"}`)
}

async function installMocks(page) {
  await page.route("**/api/**", async (route) => {
    const req = route.request()
    const url = new URL(req.url())
    const path = url.pathname
    const method = req.method()
    const json = mockApi(path, method)
    await route.fulfill({
      status: typeof json.status === "number" ? json.status : 200,
      contentType: "application/json",
      body: JSON.stringify(json.body ?? json),
    })
  })
}

function mockApi(path, method) {
  if (path === "/api/auth/me") {
    return { user: { userId: "admin", username: "管理员", role: "admin" } }
  }
  if (path === "/api/console/status") {
    return {
      phase: "Uptime: 14 天 3 小时",
      version: "1.2.0-beta",
      plugins: { total: 342, enabled: 310, healthy: 298, unhealthy: 12 },
    }
  }
  if (path === "/api/console/plugins") return { items: plugins, total: plugins.length }
  if (path.startsWith("/api/console/plugins/")) return plugins[0]
  if (path === "/api/console/plugins/reload" || path.includes("/enable") || path.includes("/batch-")) {
    return { ok: true }
  }
  if (path === "/api/console/search-jobs" && method === "POST") {
    return searchJob()
  }
  if (path === "/api/console/search-jobs" || path === "/api/console/search-jobs/") {
    return { items: [searchJob()], total: 1 }
  }
  if (path.includes("/api/console/search-jobs/job-1/events")) {
    return { events: searchEvents() }
  }
  if (path.includes("/api/console/search-jobs/job-1")) return searchJob()
  if (path === "/api/console/settings") return settings()
  if (path === "/api/console/aggregate-settings") return aggregateSettings()
  if (path === "/api/console/lexicon/status") {
    return { commitSha: "a1b2c3d4ef", fileCount: 45, wordCount: 12400, updatedAt: "2026-07-08T10:00:00+08:00" }
  }
  if (path === "/api/console/lexicon/update") return { ok: true }
  if (path === "/api/subscribe/search") return subscribeJob()
  if (path === "/api/subscribe/search/job-sub-1") return subscribeJob()
  if (path === "/api/subscribe/library" || path === "/api/subscribe/library/mine") {
    return { items: books, total: books.length }
  }
  if (path === "/api/console/library-books") return { items: books, total: books.length }
  if (path.includes("/api/console/library-books/book-2/summary")) return bookSummary(books[1])
  if (path.includes("/api/console/library-books/book-2/chapters")) return { items: chapters(), total: 50 }
  if (path.includes("/api/console/library-books/book-2/logs")) return { items: [], total: 0 }
  if (path.includes("/api/console/chapter/")) {
    return {
      title: "第1章 诡异天道",
      content:
        "这里是试读的预览内容。文字排版模仿真实的阅读体验。\n“你醒了？”一个沙哑的声音从角落里传来。\n李火旺转过头，看到一个身披破烂道袍的老者正盘腿坐在蒲团上。",
    }
  }
  return { ok: true }
}

function subscribeJob() {
  return {
    jobId: "job-sub-1",
    status: "completed",
    cards: searchCards,
    events: searchEvents(),
  }
}

function searchJob() {
  return {
    jobId: "job-1",
    status: "completed",
    sourceCount: 124,
    completedCount: 124,
    successCount: 89,
    errorCount: 35,
    resultCount: 12,
    result: {
      items: [
        { name: "深海余烬", author: "远瞳", sourceCount: 18, score: 98, sourceId: "com.qidian" },
        { name: "深海", author: "未知", sourceCount: 3, score: 45, sourceId: "net.biquge" },
      ],
    },
  }
}

function searchEvents() {
  return [
    { type: "summary", sourceCount: 124 },
    { type: "source_complete", sourceId: "com.qidian", sourceName: "com.qidian", status: "success", latencyMs: 120, count: 18 },
    { type: "source_complete", sourceId: "net.biquge", sourceName: "net.biquge", status: "success", latencyMs: 840, count: 3 },
    { type: "source_complete", sourceId: "org.tadu", sourceName: "org.tadu", status: "timeout", latencyMs: 5000, count: 0 },
    { type: "source_complete", sourceId: "com.zongheng", sourceName: "com.zongheng", status: "error", latencyMs: 45, error: "HTTP 500", count: 0 },
  ]
}

function bookSummary(book) {
  return {
    found: true,
    ...book,
    book,
    addedByUsername: "System",
    startChapterIndex: 1,
    totalChaptersAtSubscribe: book.totalChapters,
    currentPolicyVersion: 2,
    autoArchiveOnComplete: true,
    searchVisibilityStatus: "visible",
    lastCheckedAt: "2026-07-08T14:30:00+08:00",
    nextCheckTime: "2026-07-08T20:30:00+08:00",
    freeChapterEndIndex: 532,
    bookState: {
      readableChapterCount: 540,
      previewChapterCount: 150,
      failedChapterCount: 50,
    },
    sourceMapRefresh: { completed: true, lastVerifiedAt: "2026-07-08T12:30:00+08:00" },
    sourceMapSummary: [
      { sourceId: "biquge", sourceName: "笔趣阁", score: 98, chapterCount: 1100, lastChapter: "第1100章", bookStatus: "正常" },
      { sourceId: "shuqige", sourceName: "书趣阁", score: 85, chapterCount: 1089, lastChapter: "第1089章", bookStatus: "延迟" },
      { sourceId: "piaotian", sourceName: "飘天文学", score: 80, chapterCount: 1050, lastChapter: "第1050章", bookStatus: "延迟" },
      { sourceId: "dingdian", sourceName: "顶点小说", score: 75, chapterCount: 1010, lastChapter: "第1010章", bookStatus: "离线" },
      { sourceId: "miaobige", sourceName: "妙笔阁", score: 72, chapterCount: 980, lastChapter: "第980章", bookStatus: "正常" },
    ],
  }
}

function chapters() {
  return Array.from({ length: 50 }, (_, index) => {
    const chapterIndex = index + 1
    let status = "readable"
    let isVip = false
    let previewOnly = false
    if (index > 45) {
      status = "pending"
      isVip = true
    } else if (index > 40) {
      status = "failed"
      isVip = true
    } else if (index > 35) {
      status = "preview"
      isVip = true
      previewOnly = true
    } else if (index > 20) {
      isVip = true
    }
    return {
      chapterId: `chapter-${chapterIndex}`,
      readChapterId: `legadohub_ai_aggregate:chapter-${chapterIndex}`,
      chapterIndex,
      title: `第${chapterIndex}章 诡异天道`,
      status,
      isVip,
      previewOnly,
      sourceId: index % 3 === 0 ? "备用源" : "主源",
      sourceWordCount: 3200,
      contentLength: 3200,
      hasContent: status !== "pending" && status !== "failed",
      error: status === "failed" ? "超时" : "",
    }
  })
}

function settings() {
  return {
    sourcePool: {
      max_concurrency: 64,
      source_batch_size: 50,
      source_timeout_seconds: 5,
      browser_search_timeout_seconds: 15,
      default_user_agent: "Mozilla/5.0...",
      officialSourceInNormalSearch: true,
      proxy: { url: "http://127.0.0.1:7890" },
    },
    searchScoreFilter: 40,
    contentWorkflow: { aggregationMode: "balanced", purifyMode: "conservative" },
  }
}

function aggregateSettings() {
  return {
    contentWorkflow: {
      sourceCandidateLimit: 5,
      aggregateCheckIntervalMinutes: 60,
      primarySourcePriority: ["起点中文网", "纵横中文网", "番茄小说"],
      candidateSourcePriority: ["笔趣阁", "书趣阁", "看书阁"],
    },
  }
}

async function capture(browser, url, viewport, isCurrent, prepare) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    reducedMotion: "reduce",
    colorScheme: "light",
  })
  const page = await context.newPage()
  if (isCurrent) await installMocks(page)
  page.on("pageerror", (error) => console.warn(`[pageerror] ${url}: ${error.message}`))
  page.on("console", (msg) => {
    if (msg.type() === "error") console.warn(`[console] ${url}: ${msg.text()}`)
  })
  await page.addInitScript(() => {
    window.EventSource = class {
      constructor(url) {
        setTimeout(() => this.onopen?.({}), 0)
        if (typeof url === "string" && url.includes("book-2/logs")) {
          const messages = [
            { ts: "2023-10-27T14:30:00", event: "Checking for updates..." },
            { ts: "2023-10-27T14:30:01", event: "No new chapters found." },
            { ts: "2023-10-27T14:32:11", event: "Chapter 541 processing failed: rate limit exceeded.", errorCode: "RATE_LIMIT" },
          ]
          messages.forEach((msg, i) => {
            setTimeout(() => this.onmessage?.({ data: JSON.stringify(msg) }), 50 + i * 50)
          })
        }
      }
      close() {}
    }
  })
  await page.goto(url, { waitUntil: "networkidle" })
  await page.addStyleTag({
    content: `
      *, *::before, *::after {
        animation-duration: 0s !important;
        animation-delay: 0s !important;
        transition-duration: 0s !important;
        caret-color: transparent !important;
      }
      html { scroll-behavior: auto !important; }
    `,
  })
  if (prepare) await prepare(page)
  await page.waitForLoadState("networkidle").catch(() => {})
  await page.waitForTimeout(250)
  await page.evaluate(() => window.scrollTo(0, 0))
  const screenshot = await page.screenshot({ fullPage: false, animations: "disabled" })
  await context.close()
  return screenshot
}

async function compareImages(browser, expected, actual, threshold = 16) {
  const page = await browser.newPage({ viewport: { width: 64, height: 64 } })
  const result = await page.evaluate(
    async ({ expectedBase64, actualBase64, thresholdValue }) => {
      const load = (src) =>
        new Promise((resolvePromise, reject) => {
          const img = new Image()
          img.onload = () => resolvePromise(img)
          img.onerror = reject
          img.src = src
        })
      const expectedImg = await load(`data:image/png;base64,${expectedBase64}`)
      const actualImg = await load(`data:image/png;base64,${actualBase64}`)
      const width = Math.max(expectedImg.width, actualImg.width)
      const height = Math.max(expectedImg.height, actualImg.height)
      const canvas = document.createElement("canvas")
      const ctx = canvas.getContext("2d")
      canvas.width = width
      canvas.height = height
      ctx.fillStyle = "#fff"
      ctx.fillRect(0, 0, width, height)
      ctx.drawImage(expectedImg, 0, 0)
      const expectedData = ctx.getImageData(0, 0, width, height).data
      ctx.fillStyle = "#fff"
      ctx.fillRect(0, 0, width, height)
      ctx.drawImage(actualImg, 0, 0)
      const actualData = ctx.getImageData(0, 0, width, height).data
      const diffCanvas = document.createElement("canvas")
      const diffCtx = diffCanvas.getContext("2d")
      diffCanvas.width = width
      diffCanvas.height = height
      const diff = diffCtx.createImageData(width, height)
      let mismatch = 0
      for (let i = 0; i < expectedData.length; i += 4) {
        const delta =
          Math.abs(expectedData[i] - actualData[i]) +
          Math.abs(expectedData[i + 1] - actualData[i + 1]) +
          Math.abs(expectedData[i + 2] - actualData[i + 2]) +
          Math.abs(expectedData[i + 3] - actualData[i + 3])
        const out = i
        if (delta > thresholdValue) {
          mismatch += 1
          diff.data[out] = 239
          diff.data[out + 1] = 68
          diff.data[out + 2] = 68
          diff.data[out + 3] = 255
        } else {
          const gray = Math.round((actualData[i] + actualData[i + 1] + actualData[i + 2]) / 3)
          diff.data[out] = gray
          diff.data[out + 1] = gray
          diff.data[out + 2] = gray
          diff.data[out + 3] = 60
        }
      }
      diffCtx.putImageData(diff, 0, 0)
      return {
        width,
        height,
        mismatch,
        ratio: mismatch / (width * height),
        diffBase64: diffCanvas.toDataURL("image/png").split(",")[1],
      }
    },
    {
      expectedBase64: expected.toString("base64"),
      actualBase64: actual.toString("base64"),
      thresholdValue: threshold,
    },
  )
  await page.close()
  return { ...result, diff: Buffer.from(result.diffBase64, "base64") }
}

async function main() {
  await mkdir(outputDir, { recursive: true })
  await ensureDeps(frontendDir)
  await ensureDeps(designDir)

  const currentServer = startVite(frontendDir, ports.current)
  const designServer = startVite(designDir, ports.design)
  const servers = [currentServer, designServer]
  const stopServers = () => servers.forEach((child) => child.kill())
  process.on("exit", stopServers)
  process.on("SIGINT", () => {
    stopServers()
    process.exit(130)
  })

  try {
    await Promise.all([
      waitFor(`http://127.0.0.1:${ports.current}/console`),
      waitFor(`http://127.0.0.1:${ports.design}/#/`),
    ])

    const browser = await chromium.launch()
    const records = []
    try {
      for (const viewport of viewports) {
        for (const pageDef of pages) {
          const prefix = `${viewport.name}-${pageDef.id}`
          const designUrl = `http://127.0.0.1:${ports.design}${pageDef.designPath}`
          const currentUrl = `http://127.0.0.1:${ports.current}${pageDef.currentPath}`
          console.log(`[capture] ${prefix}`)
          const designShot = await capture(browser, designUrl, viewport, false, pageDef.prepare)
          const currentShot = await capture(
            browser,
            currentUrl,
            viewport,
            true,
            pageDef.prepareCurrent || pageDef.prepare,
          )
          const comparison = await compareImages(browser, designShot, currentShot)
          await writeFile(join(outputDir, `${prefix}-design.png`), designShot)
          await writeFile(join(outputDir, `${prefix}-current.png`), currentShot)
          await writeFile(join(outputDir, `${prefix}-diff.png`), comparison.diff)
          records.push({
            viewport: viewport.name,
            page: pageDef.id,
            title: pageDef.title,
            designPath: pageDef.designPath,
            currentPath: pageDef.currentPath,
            mismatchPixels: comparison.mismatch,
            mismatchRatio: Number(comparison.ratio.toFixed(4)),
            width: comparison.width,
            height: comparison.height,
            files: {
              design: `${prefix}-design.png`,
              current: `${prefix}-current.png`,
              diff: `${prefix}-diff.png`,
            },
          })
        }
      }
    } finally {
      await browser.close()
    }

    const report = {
      generatedAt: new Date().toISOString(),
      outputDir,
      currentBaseUrl: `http://127.0.0.1:${ports.current}`,
      designBaseUrl: `http://127.0.0.1:${ports.design}`,
      threshold: 16,
      note: "official-sources 在 untitled/src/App.tsx 中没有独立路由，首轮映射到 sources/书源管理整体页。",
      records,
    }
    await writeFile(join(outputDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`)
    await writeFile(join(outputDir, "report.md"), renderMarkdown(report))
    console.log(`\n[done] report: ${join(outputDir, "report.md")}`)
  } finally {
    stopServers()
  }
}

function renderMarkdown(report) {
  const lines = [
    "# Console Visual Diff Report",
    "",
    `Generated: ${report.generatedAt}`,
    "",
    report.note,
    "",
    "| Viewport | Page | Mismatch | Files |",
    "| --- | --- | ---: | --- |",
  ]
  for (const item of report.records) {
    const pct = `${(item.mismatchRatio * 100).toFixed(2)}%`
    lines.push(
      `| ${item.viewport} | ${item.title} | ${pct} | [design](${item.files.design}) / [current](${item.files.current}) / [diff](${item.files.diff}) |`,
    )
  }
  lines.push("")
  lines.push("## How To Re-run")
  lines.push("")
  lines.push("```powershell")
  lines.push("cd C:\\Home\\Workspace\\UGit\\legado-hub\\frontend")
  lines.push("node .\\visual-diff\\run-visual-diff.mjs")
  lines.push("```")
  lines.push("")
  return `${lines.join("\n")}\n`
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
