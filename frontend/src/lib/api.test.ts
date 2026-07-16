import { afterEach, describe, expect, it, vi } from "vitest"
import { api, ApiError } from "./api"

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
