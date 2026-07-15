import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { login } from '@/lib/api'

// Экран входа Оператора (#36). email+password → POST /v1/auth/login ядра → токен в localStorage.
// Форму заполняет Оператор (RBAC ядра); пароль на фронте не хранится, только opaque-токен.
export function Login() {
  const nav = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
      nav('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка входа')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-void px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-card border border-line bg-card p-6">
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-card border border-copper/40 text-lg text-copper">
            ◈
          </div>
          <div>
            <div className="font-serif text-[18px] text-bone">Citadel</div>
            <div className="text-[11px] text-ash">Merlin Forge · консоль оператора</div>
          </div>
        </div>

        <label className="mb-3 block">
          <span className="mb-1 block text-[12px] text-fog">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            className="w-full rounded-pill border border-line bg-panel px-4 py-2 text-[13px] text-bone focus:border-copper/50 focus:outline-none"
          />
        </label>

        <label className="mb-4 block">
          <span className="mb-1 block text-[12px] text-fog">Пароль</span>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            className="w-full rounded-pill border border-line bg-panel px-4 py-2 text-[13px] text-bone focus:border-copper/50 focus:outline-none"
          />
        </label>

        {error && (
          <div className="mb-3 rounded-card border border-danger/30 bg-danger/5 px-3 py-2 text-[12px] text-danger">
            {error}
          </div>
        )}

        <Button type="submit" variant="primary" disabled={busy} className="w-full">
          {busy ? 'Вход…' : 'Войти'}
        </Button>
        <div className="mt-3 text-center text-[11px] text-ash">
          Доступ только для оператора · вход по RBAC ядра
        </div>
      </form>
    </div>
  )
}
