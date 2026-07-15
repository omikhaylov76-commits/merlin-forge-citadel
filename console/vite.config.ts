import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Консоль Оператора (Ф4): React+Vite, тема shadcn на слаш-токенах (CSS-first Tailwind v4).
// Прокси /api → ядро: фронт зовёт относительный /api, dev-сервер перенаправляет на MF_CORE_URL
// (по умолчанию облачное ядро). Так деньги-логика остаётся в ядре, консоль — только дисплей.
const CORE = process.env.MF_CORE_URL ?? 'https://core-production-429b.up.railway.app'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5173,
    strictPort: true,
    proxy: { '/api': { target: CORE, changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, '') } },
  },
})
