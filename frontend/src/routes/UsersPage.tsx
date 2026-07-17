import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { KeyRound, Loader2, Plus, RefreshCw, UserCheck, Users, UserX } from "lucide-react"
import { api, apiErrorMessage, type ManagedUser } from "@/lib/api"
import { useAuth } from "@/lib/auth"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"

function formatDate(value?: string) {
  if (!value) return "-"
  try {
    return new Date(value).toLocaleString("zh-CN")
  } catch {
    return value
  }
}

export function UsersPage() {
  const queryClient = useQueryClient()
  const { user: currentUser } = useAuth()
  const [createOpen, setCreateOpen] = useState(false)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [role, setRole] = useState<"admin" | "user">("user")
  const [resetTarget, setResetTarget] = useState<ManagedUser | null>(null)
  const [resetPassword, setResetPassword] = useState("")

  const usersQuery = useQuery({ queryKey: ["users"], queryFn: api.users.list })
  const refreshUsers = () => queryClient.invalidateQueries({ queryKey: ["users"] })

  const createMutation = useMutation({
    mutationFn: (payload: { username: string; password: string; role: "admin" | "user" }) => api.users.create(payload),
    onSuccess: async () => {
      setPassword("")
      setUsername("")
      setRole("user")
      setCreateOpen(false)
      await refreshUsers()
    },
  })
  const resetMutation = useMutation({
    mutationFn: ({ userId, nextPassword }: { userId: string; nextPassword: string }) =>
      api.users.resetPassword(userId, nextPassword),
    onSuccess: async () => {
      setResetPassword("")
      setResetTarget(null)
      await refreshUsers()
    },
  })
  const statusMutation = useMutation({
    mutationFn: ({ userId, disabled }: { userId: string; disabled: boolean }) =>
      api.users.setDisabled(userId, disabled),
    onSuccess: refreshUsers,
  })

  const openCreateDialog = () => {
    createMutation.reset()
    setUsername("")
    setPassword("")
    setRole("user")
    setCreateOpen(true)
  }
  const closeCreateDialog = () => {
    setCreateOpen(false)
    setPassword("")
    createMutation.reset()
  }
  const closeResetDialog = () => {
    setResetTarget(null)
    setResetPassword("")
    resetMutation.reset()
  }
  const users = usersQuery.data?.items || []
  const enabledCount = users.filter((item) => !item.disabled).length
  const adminCount = users.filter((item) => item.role === "admin" && !item.disabled).length
  const pageError = usersQuery.error || statusMutation.error

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">用户管理</h1>
          <p className="mt-1 text-sm text-slate-500">账户、角色与访问状态</p>
        </div>
        <Button onClick={openCreateDialog}><Plus className="mr-2 h-4 w-4" /> 新建用户</Button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div className="border-l-2 border-slate-400 bg-white px-4 py-3">
          <div className="text-xs text-slate-500">用户总数</div>
          <div className="mt-1 text-xl font-semibold text-slate-900">{users.length}</div>
        </div>
        <div className="border-l-2 border-emerald-500 bg-white px-4 py-3">
          <div className="text-xs text-slate-500">可用账户</div>
          <div className="mt-1 text-xl font-semibold text-emerald-700">{enabledCount}</div>
        </div>
        <div className="col-span-2 border-l-2 border-blue-500 bg-white px-4 py-3 sm:col-span-1">
          <div className="text-xs text-slate-500">可用管理员</div>
          <div className="mt-1 text-xl font-semibold text-blue-700">{adminCount}</div>
        </div>
      </div>

      {pageError && (
        <Alert variant="destructive">
          <AlertDescription className="flex items-center justify-between gap-3">
            <span>{apiErrorMessage(pageError, "用户数据加载失败。")}</span>
            {usersQuery.error && (
              <Button variant="outline" size="sm" onClick={() => usersQuery.refetch()}>
                <RefreshCw className="mr-2 h-4 w-4" /> 重试
              </Button>
            )}
          </AlertDescription>
        </Alert>
      )}

      <Card className="border-slate-200 shadow-sm">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader className="bg-slate-50">
                <TableRow>
                  <TableHead>用户名</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>创建时间</TableHead>
                  <TableHead>最后更新</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {usersQuery.isLoading ? (
                  <TableRow><TableCell colSpan={6} className="h-28 text-center text-slate-500"><Loader2 className="mr-2 inline h-4 w-4 animate-spin" />加载中</TableCell></TableRow>
                ) : users.length === 0 ? (
                  <TableRow><TableCell colSpan={6} className="h-28 text-center text-slate-500"><Users className="mr-2 inline h-4 w-4" />暂无用户</TableCell></TableRow>
                ) : users.map((item) => {
                  const isCurrentUser = item.userId === currentUser?.userId
                  const statusPending = statusMutation.isPending && statusMutation.variables?.userId === item.userId
                  return (
                    <TableRow key={item.userId} className={item.disabled ? "bg-slate-50/60 text-slate-500" : ""}>
                      <TableCell className="font-medium text-slate-900">
                        {item.username}
                        {isCurrentUser && <span className="ml-2 text-xs font-normal text-slate-400">当前账户</span>}
                      </TableCell>
                      <TableCell><Badge variant="outline">{item.role === "admin" ? "管理员" : "普通用户"}</Badge></TableCell>
                      <TableCell>
                        <Badge className={item.disabled ? "bg-slate-100 text-slate-600" : "bg-emerald-50 text-emerald-700"}>
                          {item.disabled ? "已禁用" : "可用"}
                        </Badge>
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-slate-500">{formatDate(item.createdAt)}</TableCell>
                      <TableCell className="whitespace-nowrap text-slate-500">{formatDate(item.updatedAt)}</TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-2">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => { resetMutation.reset(); setResetPassword(""); setResetTarget(item) }}
                          >
                            <KeyRound className="mr-2 h-4 w-4" /> 重置密码
                          </Button>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={isCurrentUser || statusPending}
                            title={isCurrentUser ? "不能禁用当前账户" : undefined}
                            onClick={() => {
                              const disabled = !item.disabled
                              if (!disabled || window.confirm(`确定禁用用户“${item.username}”吗？`)) {
                                statusMutation.mutate({ userId: item.userId, disabled })
                              }
                            }}
                          >
                            {statusPending ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : item.disabled ? <UserCheck className="mr-2 h-4 w-4" /> : <UserX className="mr-2 h-4 w-4" />}
                            {item.disabled ? "启用" : "禁用"}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => { if (!open) closeCreateDialog() }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>新建用户</DialogTitle>
            <DialogDescription>创建可登录 LegadoHub 的账户。</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              createMutation.mutate({ username, password, role })
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="managed-user-name">用户名</Label>
              <Input id="managed-user-name" autoComplete="off" maxLength={64} value={username} onChange={(event) => setUsername(event.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="managed-user-password">初始密码</Label>
              <Input id="managed-user-password" type="password" autoComplete="new-password" minLength={8} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="managed-user-role">角色</Label>
              <select id="managed-user-role" value={role} onChange={(event) => setRole(event.target.value as "admin" | "user")} className="h-10 w-full rounded-md border border-slate-200 bg-white px-3 text-sm">
                <option value="user">普通用户</option>
                <option value="admin">管理员</option>
              </select>
            </div>
            {createMutation.error && <Alert variant="destructive"><AlertDescription>{apiErrorMessage(createMutation.error, "用户创建失败。")}</AlertDescription></Alert>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={closeCreateDialog}>取消</Button>
              <Button type="submit" disabled={createMutation.isPending || !username.trim() || password.length < 8}>
                {createMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}创建
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!resetTarget} onOpenChange={(open) => { if (!open) closeResetDialog() }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>重置密码</DialogTitle>
            <DialogDescription>{resetTarget?.username || "用户"}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault()
              if (resetTarget) resetMutation.mutate({ userId: resetTarget.userId, nextPassword: resetPassword })
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="managed-user-reset-password">新密码</Label>
              <Input id="managed-user-reset-password" type="password" autoComplete="new-password" minLength={8} maxLength={128} value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} />
            </div>
            {resetMutation.error && <Alert variant="destructive"><AlertDescription>{apiErrorMessage(resetMutation.error, "密码重置失败。")}</AlertDescription></Alert>}
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={closeResetDialog}>取消</Button>
              <Button type="submit" disabled={resetMutation.isPending || resetPassword.length < 8}>
                {resetMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}重置
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  )
}
