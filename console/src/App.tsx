import { type ReactNode } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { Login } from '@/screens/Login'
import { getToken } from '@/lib/api'
import { Overview } from '@/screens/Overview'
import { Fleet } from '@/screens/Fleet'
import { Deals } from '@/screens/Deals'
import { Clients } from '@/screens/Clients'
import { ClientCard } from '@/screens/ClientCard'
import { Constructor } from '@/screens/Constructor'
import { Scout } from '@/screens/Scout'
import { Screener } from '@/screens/Screener'
import { Basket } from '@/screens/Basket'
import { Profiles } from '@/screens/Profiles'
import { Reports } from '@/screens/Reports'
import { Alerts } from '@/screens/Alerts'
import { Settings } from '@/screens/Settings'
import { Portal } from '@/screens/Portal'

// Гейт: нет токена оператора → на экран входа. Токен — opaque, в localStorage (api.getToken).
function RequireAuth({ children }: { children: ReactNode }) {
  return getToken() ? <>{children}</> : <Navigate to="/login" replace />
}

// Роутер консоли: /login (вне оболочки) + оболочка под гейтом с 11 экранами.
export const router = createBrowserRouter([
  { path: '/login', element: <Login /> },
  {
    path: '/',
    element: (
      <RequireAuth>
        <AppShell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Overview /> },
      { path: 'fleet', element: <Fleet /> },
      { path: 'deals', element: <Deals /> },
      { path: 'clients', element: <Clients /> },
      { path: 'clients/:id', element: <ClientCard /> },
      { path: 'scout', element: <Scout /> },
      { path: 'screener', element: <Screener /> },
      { path: 'basket', element: <Basket /> },
      { path: 'profiles', element: <Profiles /> },
      { path: 'constructor', element: <Constructor /> },
      { path: 'reports', element: <Reports /> },
      { path: 'alerts', element: <Alerts /> },
      { path: 'settings', element: <Settings /> },
      { path: 'portal', element: <Portal /> },
    ],
  },
])
