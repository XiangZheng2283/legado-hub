import { chromium } from "playwright"
import fs from "node:fs"
import path from "node:path"

function arg(name, fallback = "") {
  const index = process.argv.indexOf(`--${name}`)
  if (index < 0 || index + 1 >= process.argv.length) return fallback
  return process.argv[index + 1]
}

function args(name) {
  const values = []
  for (let index = 0; index < process.argv.length; index += 1) {
    if (process.argv[index] === `--${name}` && index + 1 < process.argv.length) {
      values.push(process.argv[index + 1])
    }
  }
  return values
}

const sessionId = arg("session-id")
const openUrl = arg("url")
const outFile = arg("out")
const proxyServer = arg("proxy")
const cookieDomains = args("cookie-domain")

if (!sessionId || !openUrl || !outFile) {
  console.error("Missing --session-id, --url, or --out")
  process.exit(2)
}

fs.mkdirSync(path.dirname(outFile), { recursive: true })

const userDataDir = path.join(path.dirname(outFile), `${sessionId}-profile`)
const context = await chromium.launchPersistentContext(userDataDir, {
  headless: false,
  viewport: { width: 1280, height: 860 },
  ...(proxyServer ? { proxy: { server: proxyServer } } : {}),
})

const page = context.pages()[0] || await context.newPage()

function cookieUrls() {
  const urls = new Set([openUrl])
  for (const domain of cookieDomains) {
    const clean = String(domain || "").replace(/^\./, "")
    if (!clean) continue
    urls.add(`https://${clean}/`)
    urls.add(`http://${clean}/`)
  }
  return Array.from(urls)
}

function dedupeCookies(cookies) {
  const seen = new Set()
  const result = []
  for (const cookie of cookies) {
    const key = `${cookie.domain}|${cookie.path}|${cookie.name}`
    if (seen.has(key)) continue
    seen.add(key)
    result.push(cookie)
  }
  return result
}

async function writeCookies(status = "running") {
  const cookies = dedupeCookies([
    ...(await context.cookies().catch(() => [])),
    ...(await context.cookies(cookieUrls()).catch(() => [])),
  ])
  const cookieNames = Array.from(new Set(cookies.map((cookie) => cookie.name))).sort()
  const savedDomains = Array.from(new Set(cookies.map((cookie) => String(cookie.domain || "").replace(/^\./, "")))).sort()
  const clearanceDomains = Array.from(
    new Set(
      cookies
        .filter((cookie) => cookie.name === "cf_clearance")
        .map((cookie) => String(cookie.domain || "").replace(/^\./, "")),
    ),
  ).sort()
  fs.writeFileSync(
    outFile,
    JSON.stringify(
      {
        sessionId,
        status,
        openUrl,
        currentUrl: page.url(),
        proxyServer,
        proxyUsed: Boolean(proxyServer),
        cookieCount: cookies.length,
        cookieDomains: savedDomains,
        cookieNames,
        clearanceDomains,
        targetCookieDomains: cookieDomains,
        cookies,
        updatedAt: new Date().toISOString(),
      },
      null,
      2,
    ),
    "utf-8",
  )
}

page.on("framenavigated", () => {
  writeCookies().catch(() => undefined)
})
page.on("response", (response) => {
  const headers = response.headers()
  if (headers["set-cookie"]) {
    writeCookies().catch(() => undefined)
  }
})

await page.goto(openUrl, { waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => undefined)
await writeCookies()

const timer = setInterval(() => {
  writeCookies().catch(() => undefined)
}, 2000)

context.on("close", () => {
  clearInterval(timer)
})

process.on("SIGTERM", async () => {
  await writeCookies("closed").catch(() => undefined)
  await context.close().catch(() => undefined)
})

await new Promise((resolve) => {
  context.on("close", resolve)
})
await writeCookies("closed").catch(() => undefined)
