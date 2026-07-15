import { createBrowserRouter } from 'react-router-dom'
import { AppShell } from '@/components/layout/AppShell'
import { Overview } from '@/screens/Overview'
import { Placeholder } from '@/screens/Placeholder'

// Роутер консоли: оболочка + 11 экранов (Обзор реален, остальные — заглушки до раскатки).
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Overview /> },
      { path: 'fleet', element: <Placeholder title="Флот" /> },
      { path: 'deals', element: <Placeholder title="Сделки" /> },
      { path: 'clients', element: <Placeholder title="Клиенты" /> },
      { path: 'scout', element: <Placeholder title="Разведка" /> },
      { path: 'profiles', element: <Placeholder title="Профили" /> },
      { path: 'constructor', element: <Placeholder title="Конструктор" /> },
      { path: 'reports', element: <Placeholder title="Отчёты" /> },
      { path: 'alerts', element: <Placeholder title="Тревоги" /> },
      { path: 'settings', element: <Placeholder title="Настройки" /> },
      { path: 'portal', element: <Placeholder title="Портал клиента" /> },
    ],
  },
])
