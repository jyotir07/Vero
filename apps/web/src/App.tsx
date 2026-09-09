import { Route, Routes } from 'react-router-dom'

import { ApplicationDetail } from '@/pages/ApplicationDetail'
import { ApplicationList } from '@/pages/ApplicationList'
import { NewApplication } from '@/pages/NewApplication'

export default function App() {
  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto flex max-w-6xl items-baseline gap-3 px-6 py-4">
          <span className="text-lg font-semibold tracking-tight text-foreground">Vero</span>
          <span className="text-xs text-muted-foreground">
            Simulated credit underwriting · synthetic data, not a real decisioning system
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-8">
        <Routes>
          <Route path="/" element={<ApplicationList />} />
          <Route path="/applications/new" element={<NewApplication />} />
          <Route path="/applications/:id" element={<ApplicationDetail />} />
        </Routes>
      </main>
    </div>
  )
}
