import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom"
import { QueryClientProvider } from "@tanstack/react-query"
import { queryClient } from "@/lib/query"
import { AuthProvider, useAuth } from "@/lib/auth"
import { Layout } from "@/components/layout/Layout"
import { LoginPage } from "@/routes/LoginPage"
import { Dashboard } from "@/routes/Dashboard"
import { Plugins } from "@/routes/Plugins"
import { PluginDetail } from "@/routes/PluginDetail"
import { SearchJobs } from "@/routes/SearchJobs"
import { CachePage } from "@/routes/CachePage"
import { SettingsPage } from "@/routes/SettingsPage"
import { OfficialSourcesPage } from "@/routes/OfficialSourcesPage"
import { SubscriptionDiscoveryPage } from "@/routes/SubscriptionDiscoveryPage"
import { LibraryPage } from "@/routes/LibraryPage"
import { LibraryBookDetailPage } from "@/routes/LibraryBookDetailPage"

function ProtectedLayout() {
  const { isLoading, isAuthenticated } = useAuth()
  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-muted-foreground">加载中...</div>
      </div>
    )
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }
  return <Outlet />
}

function AuthRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedLayout />}>
          <Route path="/console" element={<Layout />}>
            <Route index element={<Dashboard />} />
            <Route path="plugins" element={<Plugins />} />
            <Route path="plugins/:pluginId" element={<PluginDetail />} />
            <Route path="search" element={<SearchJobs />} />
            <Route path="official-sources" element={<OfficialSourcesPage />} />
            <Route path="cache" element={<CachePage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="subscription" element={<SubscriptionDiscoveryPage />} />
            <Route path="library" element={<LibraryPage />} />
            <Route path="library/:bookId" element={<LibraryBookDetailPage />} />
          </Route>
        </Route>
        <Route path="*" element={<Navigate to="/console" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AuthRouter />
      </AuthProvider>
    </QueryClientProvider>
  )
}

export default App
