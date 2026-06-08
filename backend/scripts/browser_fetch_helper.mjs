import fs from "node:fs"
import path from "node:path"
import { createRequire } from "node:module"

const require = createRequire(path.join(process.cwd(), "package.json"))
const { chromium } = require("playwright")

function arg(name, fallback = "") {
  const index = process.argv.indexOf(`--${name}`)
  if (index < 0 || index + 1 >= process.argv.length) return fallback
  return process.argv[index + 1]
}

const url = arg("url")
const outFile = arg("out")
const userDataDir = arg("user-data-dir")
const proxyServer = arg("proxy")
const waitMs = Number(arg("wait-ms", "2500"))
const userAgent = arg("user-agent")
const method = arg("method", "GET").toUpperCase()
const dataJson = arg("data-json")
const cookiesJson = arg("cookies-json")

if (!url || !outFile || !userDataDir) {
  console.error("Missing --url, --out, or --user-data-dir")
  process.exit(2)
}

fs.mkdirSync(path.dirname(outFile), { recursive: true })
fs.mkdirSync(userDataDir, { recursive: true })

const context = await chromium.launchPersistentContext(userDataDir, {
  headless: true,
  viewport: { width: 390, height: 900 },
  ...(proxyServer ? { proxy: { server: proxyServer } } : {}),
  ...(userAgent ? { userAgent } : {}),
})

if (cookiesJson && fs.existsSync(cookiesJson)) {
  const cookies = JSON.parse(fs.readFileSync(cookiesJson, "utf-8"))
  if (Array.isArray(cookies) && cookies.length > 0) {
    await context.addCookies(cookies)
  }
}

const page = context.pages()[0] || await context.newPage()

async function stableContent(page) {
  let lastError
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      await page.waitForLoadState("domcontentloaded", { timeout: 10000 }).catch(() => undefined)
      await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => undefined)
      return await page.content()
    } catch (error) {
      lastError = error
      await page.waitForTimeout(1000)
    }
  }
  throw lastError
}

try {
  if (method === "POST") {
    const form = dataJson ? JSON.parse(dataJson) : {}
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 })
    for (const [key, value] of Object.entries(form)) {
      const selector = `[name="${String(key).replaceAll('"', '\\"')}"]`
      await page.locator(selector).first().fill(String(value)).catch(() => undefined)
    }
    await Promise.all([
      page.waitForNavigation({ waitUntil: "domcontentloaded", timeout: 60000 }).catch(() => undefined),
      page.locator('input[type="submit"], button[type="submit"], input.go').first().click().catch(async () => {
        await page.locator("form").first().evaluate((formEl) => formEl.submit()).catch(() => undefined)
      }),
    ])
  } else {
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 })
  }
  if (waitMs > 0) {
    await page.waitForTimeout(waitMs)
  }
  const html = await stableContent(page)
  const cookies = await context.cookies()
  fs.writeFileSync(
    outFile,
    JSON.stringify(
      {
        ok: true,
        url: page.url(),
        title: await page.title().catch(() => ""),
        html,
        cookies,
        proxyUsed: Boolean(proxyServer),
        updatedAt: new Date().toISOString(),
      },
      null,
      2,
    ),
    "utf-8",
  )
} catch (error) {
  fs.writeFileSync(
    outFile,
    JSON.stringify(
      {
        ok: false,
        url,
        error: error instanceof Error ? error.message : String(error),
        proxyUsed: Boolean(proxyServer),
        updatedAt: new Date().toISOString(),
      },
      null,
      2,
    ),
    "utf-8",
  )
  process.exitCode = 1
} finally {
  await context.close().catch(() => undefined)
}
