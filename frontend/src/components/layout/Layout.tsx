import { Outlet, NavLink, useLocation } from "react-router-dom"
import {
  LayoutDashboard,
  Puzzle,
  Search,
  HardDrive,
  Settings,
  FileJson,
  ShieldCheck,
} from "lucide-react"
import { Separator } from "@/components/ui/separator"

const navItems = [
  { to: "/console", label: "仪表盘", icon: LayoutDashboard, end: true },
  { to: "/console/plugins", label: "插件", icon: Puzzle },
  { to: "/console/search", label: "搜索", icon: Search },
  { to: "/console/cache", label: "缓存", icon: HardDrive },
  { to: "/console/settings", label: "设置", icon: Settings },
  { to: "/console/aggregate-source", label: "聚合书源", icon: FileJson },
  { to: "/console/verification", label: "验证", icon: ShieldCheck },
]

export function Layout() {
  const location = useLocation()
  return (
    <div className="flex min-h-screen">
      <aside className="w-56 bg-card border-r flex flex-col sticky top-0 h-screen">
        <div className="h-14 flex items-center px-4 border-b">
          <span className="font-semibold">LegadoHub 控制台</span>
        </div>
        <nav className="flex-1 p-2 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const active = item.end
              ? location.pathname === item.to
              : location.pathname.startsWith(item.to)
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={() =>
                  `flex items-center gap-3 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    active
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-foreground"
                  }`
                }
              >
                <item.icon className="w-4 h-4" />
                {item.label}
              </NavLink>
            )
          })}
        </nav>
        <Separator />
        <div className="p-3 text-xs text-muted-foreground">
          Plugin Runtime Stage 3
        </div>
      </aside>
      <main className="flex-1 p-6 overflow-y-auto bg-background">
        <Outlet />
      </main>
    </div>
  )
}
