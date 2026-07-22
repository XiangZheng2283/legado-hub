import { render, screen } from "@testing-library/react"
import { MemoryRouter, Route, Routes } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"
import { AdminOnly } from "./App"

const authState = vi.hoisted(() => ({
  role: "user" as "admin" | "user",
  entrypoint: "combined" as "public" | "admin" | "combined",
}))

vi.mock("@/lib/auth", () => ({
  AuthProvider: ({ children }: { children: React.ReactNode }) => children,
  useAuth: () => ({
    entrypoint: authState.entrypoint,
    user: { userId: "user-1", username: "tester", role: authState.role },
  }),
}))

function renderGuard() {
  return render(
    <MemoryRouter initialEntries={["/console/settings"]}>
      <Routes>
        <Route path="/" element={<div>用户首页</div>} />
        <Route element={<AdminOnly />}>
          <Route path="/console/settings" element={<div>订阅政策</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

describe("AdminOnly", () => {
  it("redirects ordinary users away from administrator settings", () => {
    authState.role = "user"
    authState.entrypoint = "combined"
    renderGuard()
    expect(screen.getByText("用户首页")).toBeInTheDocument()
    expect(screen.queryByText("订阅政策")).not.toBeInTheDocument()
  })

  it("allows administrators to open administrator settings", () => {
    authState.role = "admin"
    authState.entrypoint = "admin"
    renderGuard()
    expect(screen.getByText("订阅政策")).toBeInTheDocument()
  })

  it("blocks administrator routes on the public entrypoint", () => {
    authState.role = "admin"
    authState.entrypoint = "public"
    renderGuard()
    expect(screen.getByText("用户首页")).toBeInTheDocument()
    expect(screen.queryByText("订阅政策")).not.toBeInTheDocument()
  })
})
