export interface AuthUser {
  userId: string
  username: string
  role: "admin" | "user"
}
