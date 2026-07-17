import { afterEach, describe, expect, it, vi } from "vitest"
import { api, ApiError, apiErrorMessage } from "./api"

describe("subscription API errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("preserves structured error details", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        detail: {
          code: "subscription_limit_reached",
          message: "已达到当前订阅上限",
          retryable: false,
        },
      }),
      { status: 429, headers: { "Content-Type": "application/json" } },
    )))

    const error = await api.subscribe.myLibrary().catch((caught) => caught)

    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({
      status: 429,
      message: "已达到当前订阅上限",
      detail: {
        code: "subscription_limit_reached",
        retryable: false,
      },
    })
  })
})

describe("apiErrorMessage", () => {
  it("prefers the backend structured message", () => {
    expect(apiErrorMessage(new ApiError(403, { message: "仅管理员可执行" }))).toBe("仅管理员可执行")
  })

  it.each([
    [401, "登录状态已失效，请重新登录。"],
    [403, "你没有权限执行此操作。"],
    [404, "请求的资源不存在或已被删除。"],
    [429, "操作过于频繁，请稍后重试。"],
    [503, "服务暂时不可用，请稍后重试。"],
  ])("maps status %s when the backend has no message", (status, expected) => {
    expect(apiErrorMessage(new ApiError(status, {}))).toBe(expected)
  })

  it("uses the supplied fallback for unknown errors", () => {
    expect(apiErrorMessage({}, "自定义失败文案")).toBe("自定义失败文案")
  })
})
