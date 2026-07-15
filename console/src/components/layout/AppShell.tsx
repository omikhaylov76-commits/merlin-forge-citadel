import { Outlet } from 'react-router-dom'
import { Sidebar } from './Sidebar'
import { Header } from './Header'

// Каркас консоли: сайдбар слева, хедер сверху, экран (Outlet) в прокручиваемой области.
export function AppShell() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-void text-bone">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header />
        <main className="flex-1 overflow-y-auto px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
