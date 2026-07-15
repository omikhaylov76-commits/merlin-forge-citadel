import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { Overview } from '@/screens/Overview'
import { Fleet } from '@/screens/Fleet'
import { Deals } from '@/screens/Deals'
import { Clients } from '@/screens/Clients'
import { ClientCard } from '@/screens/ClientCard'
import { Constructor } from '@/screens/Constructor'
import { Placeholder } from '@/screens/Placeholder'

// Роутер консоли: оболочка + 11 экранов. Реальны: Обзор/Флот/Сделки/Клиенты; прочие — заглушки.
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'fleet', element: <Fleet /> },
      { path: 'deals', element: <Deals /> },
      { path: 'clients', element: <Clients /> },
      { path: 'clients/:id', element: <ClientCard /> },
      { path: 'scout', element: <Placeholder title="Разведка" /> },
      { path: 'profiles', element: <Placeholder title="Профили" /> },
      { path: 'constructor', element: <Constructor /> },
      { path: 'reports', element: <Placeholder title="Отчёты" /> },
      { path: 'alerts', element: <Placeholder title="Тревоги" /> },
      { path: 'settings', element: <Placeholder title="Настройки" /> },
      { path: 'portal', element: <Placeholder title="Портал клиента" /> },
    ],
  },
])
