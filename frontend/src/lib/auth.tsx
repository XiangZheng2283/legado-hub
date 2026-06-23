import { createContext, useContext, useEffect, useState, type ReactNode } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { api } from "@/lib/api"

export interface AuthUser {
  userId: string
  username: string
  role: "admin" | "user"
}

interface AuthContextValue {
  user: AuthUser | null
  isLoading: boolean
  isAuthenticated: boolean
  needsBootstrap: boolean
  login: (username: string, password: string) => Promise<void>
  bootstrap: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [needsBootstrap, setNeedsBootstrap] = useState(false)

  const {
    data: user,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ["auth", "me"],
    queryFn: api.auth.me,
    retry: false,
    staleTime: Infinity,
  })

  useEffect(() => {
    if (!isLoading && !user) {
      // Check if bootstrap is needed by trying to detect 403/no users
      api.auth
        .me()
        .catch((err) => {
          if (err instanceof Error && err.message.includes("401")) {
            // Could be unauthenticated or no users; login page handles bootstrap prompt
          }
        })
    }
  }, [isLoading, user])

  const loginMutation = useMutation({
    mutationFn: api.auth.login,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] })
      refetch()
    },
  })

  const bootstrapMutation = useMutation({
    mutationFn: api.auth.bootstrap,
    onSuccess: () => {
      setNeedsBootstrap(false)
      queryClient.invalidateQueries({ queryKey: ["auth", "me"] })
      refetch()
    },
  })

  const logoutMutation = useMutation({
    mutationFn: api.auth.logout,
    onSuccess: () => {
      queryClient.clear()
      refetch()
    },
  })

  const value: AuthContextValue = {
    user: user?.user || null,
    isLoading,
    isAuthenticated: !!user?.user,
    needsBootstrap,
    login: async (username: string, password: string) => {
      await loginMutation.mutateAsync({ username, password })
    },
    bootstrap: async (username: string, password: string) => {
      await bootstrapMutation.mutateAsync({ username, password })
    },
    logout: async () => {
      await logoutMutation.mutateAsync()
    },
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider")
  }
  return ctx
}
