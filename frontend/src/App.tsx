import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { Layout } from "@/components/layout/Layout"
import { Dashboard } from "@/routes/Dashboard"
import { Plugins } from "@/routes/Plugins"
import { PluginDetail } from "@/routes/PluginDetail"
import { SearchJobs } from "@/routes/SearchJobs"
import { CachePage } from "@/routes/CachePage"
import { SettingsPage } from "@/routes/SettingsPage"
import { AggregateSourcePage } from "@/routes/AggregateSourcePage"
import { AggregateBookshelfPage } from "@/routes/AggregateBookshelfPage"
import { AggregateBookDetailPage } from "@/routes/AggregateBookDetailPage"
import { AggregateChapterDetailPage } from "@/routes/AggregateChapterDetailPage"
import { VerificationPage } from "@/routes/VerificationPage"
import { OfficialSourcesPage } from "@/routes/OfficialSourcesPage"

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/console" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="plugins" element={<Plugins />} />
          <Route path="plugins/:pluginId" element={<PluginDetail />} />
          <Route path="search" element={<SearchJobs />} />
          <Route path="official-sources" element={<OfficialSourcesPage />} />
          <Route path="cache" element={<CachePage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="aggregate-source" element={<AggregateSourcePage />} />
          <Route path="aggregate-books" element={<AggregateBookshelfPage />} />
          <Route path="aggregate-books/:bookId" element={<AggregateBookDetailPage />} />
          <Route path="aggregate-books/:bookId/chapters/:chapterId" element={<AggregateChapterDetailPage />} />
          <Route path="verification" element={<VerificationPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/console" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
