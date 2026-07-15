import { useState, type ReactNode } from 'react'
import { PageHead } from '@/components/ui/page'
import { Card } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/cn'

// Настройки ПЛАТФОРМЫ (спека #34) — 8 подразделов, сохранение ПОБЛОЧНО. Профиль настраивается в
// Конструкторе, клиент — в его карточке; сюда не дублируем. Опасное действие = подтверждение+аудит
// (control-пароль/2FA-гейт НЕ делаем — один пользователь). Демо; живое сохранение — бэкенд-подзадача.
const SUBS = [
  'Безопасность',
  'Биржи и ключи',
  'Уведомления',
  'Правила риска',
  'Блэклист',
  'Биллинг-дефолты',
  'Помощники',
  'Журнал аудита',
]

export function Settings() {
  const [sel, setSel] = useState(0) // старт с первого пункта «Безопасность» (#37 🟢)
  return (
    <div className="mx-auto max-w-[1216px]">
      <PageHead eyebrow="Система" title="Настройки" desc="конфигурация платформы · сохранение поблочно" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[224px_1fr]">
        <nav className="h-max rounded-card border border-line bg-card p-2">
          {SUBS.map((s, i) => (
            <button
              key={s}
              onClick={() => setSel(i)}
              className={cn(
                'block w-full rounded-nav px-3 py-2 text-left text-[13px] transition-colors',
                i === sel ? 'bg-floating text-bone' : 'text-fog hover:text-mist',
              )}
            >
              {s}
            </button>
          ))}
        </nav>
        <Card>{renderSub(sel)}</Card>
      </div>
    </div>
  )
}

function renderSub(i: number): ReactNode {
  switch (i) {
    case 0:
      return <Security />
    case 1:
      return <Keys />
    case 2:
      return <Notifications />
    case 3:
      return <RiskRules />
    case 4:
      return <Blacklist />
    case 5:
      return <BillingDefaults />
    case 6:
      return <Assistants />
    default:
      return <AuditLog />
  }
}

// ── строительные блоки ──────────────────────────────────────────────────────────
function SubHead({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3 border-b border-line pb-3">
      <h3 className="text-[15px] font-semibold text-silver">{title}</h3>
      {hint && <span className="text-[12px] text-ash">{hint}</span>}
    </div>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="text-[13px] text-silver">{label}</div>
        {hint && <div className="text-[11px] text-ash">{hint}</div>}
      </div>
      {children}
    </div>
  )
}

const inputCls =
  'w-28 rounded-pill border border-line bg-panel px-3 py-1 text-right text-[13px] tnum text-bone focus:border-copper/50 focus:outline-none'
const selectCls =
  'rounded-pill border border-line bg-panel px-3 py-1 text-[13px] text-bone focus:border-copper/50 focus:outline-none'

function SaveBar({ note }: { note?: string }) {
  return (
    <div className="mt-4 flex items-center justify-between gap-3 border-t border-line pt-3">
      <span className="text-[11px] text-ash">{note ?? 'изменения сохраняются в этом блоке'}</span>
      <Button variant="primary" size="sm">
        Сохранить
      </Button>
    </div>
  )
}

// ── подразделы ──────────────────────────────────────────────────────────────────
function Security() {
  const [twofa, setTwofa] = useState(false)
  return (
    <>
      <SubHead title="Безопасность" hint="один пользователь" />
      <Field label="Двухфакторная аутентификация (2FA)" hint="TOTP на вход в консоль">
        <Switch checked={twofa} onChange={setTwofa} />
      </Field>
      <Field label="Активные сессии" hint="этот браузер · macOS · сейчас">
        <Button variant="ghost" size="sm">
          Завершить прочие
        </Button>
      </Field>
      <div className="mt-2 rounded-card border border-line bg-panel px-3 py-2 text-[12px] text-ash">
        Control-пароль поверх сейфа НЕ делаем — один оператор. Опасные действия защищены
        подтверждением и строкой аудита.
      </div>
      <SaveBar />
    </>
  )
}

function Keys() {
  return (
    <>
      <SubHead title="Биржи и ключи" hint="ключи шифрованы (ADR-0004) · плейнтекст нигде" />
      <div className="flex items-center gap-3 rounded-card border border-line bg-panel px-4 py-3">
        <Badge tone="live">Bybit ✓</Badge>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] tnum text-silver">•••• •••• •••• 1234</div>
          <div className="text-[11px] text-ash">режим: demo (api-demo) · здоровье: ок · права: торговля, без вывода</div>
        </div>
        <Button variant="ghost" size="sm">
          Проверить соединение
        </Button>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <Button size="sm">Ротация ключа</Button>
        <Button variant="danger" size="sm">
          Боевой режим (mainnet)
        </Button>
      </div>
      <div className="mt-3 rounded-card border border-copper/30 bg-copper/5 px-3 py-2 text-[12px] text-copper">
        Боевой режим (реальные деньги) — отдельный гейт go-live: ключи вводит Оператор, подтверждение +
        аудит. Сейчас demo, ALLOW_MAINNET не задан.
      </div>
      <SaveBar note="здоровье ключей — по клиентам (сводка)" />
    </>
  )
}

function Notifications() {
  const fams = ['KILL', 'ALARM', 'КЛЮЧ', 'БИЛЛИНГ', 'HEARTBEAT']
  const [on, setOn] = useState<Record<string, boolean>>({ KILL: true, ALARM: true, КЛЮЧ: true, БИЛЛИНГ: true, HEARTBEAT: false })
  return (
    <>
      <SubHead title="Уведомления · Telegram" hint="токен+chat_id кладёт Оператор" />
      <div className="text-[12px] text-ash">Какие тревоги слать:</div>
      {fams.map((f) => (
        <Field key={f} label={f}>
          <Switch checked={on[f]} onChange={(v) => setOn((s) => ({ ...s, [f]: v }))} />
        </Field>
      ))}
      <Field label="Тихие часы" hint="не слать несрочные в это окно">
        <input className={inputCls} defaultValue="23–08" />
      </Field>
      <SaveBar note="Telegram-доставка ядра — отложена (нужен токен бота)" />
    </>
  )
}

function RiskRules() {
  return (
    <>
      <SubHead title="Правила риска" hint="дефолты флота (мастер деплоя)" />
      <Field label="Порог тревоги (ALARM), по умолчанию" hint="доля просадки 0–1">
        <input className={inputCls} defaultValue="0.40" />
      </Field>
      <Field label="Аварийный стоп (KILL), по умолчанию" hint="тревога < стоп < 1">
        <input className={inputCls} defaultValue="0.50" />
      </Field>
      <div className="mt-2 rounded-card border border-ok/30 bg-ok/5 px-3 py-2 text-[12px] text-ok">
        Безопасный стоп клиенту −50%: мастер деплоя форсит его вместо demo −70%. Клиента нельзя
        развернуть с более рискованным стопом, чем платформенный дефолт.
      </div>
      <SaveBar />
    </>
  )
}

function Blacklist() {
  const rows = [
    { pair: 'LUNAUSDT', reason: 'делистинг', date: '2026-05-12' },
    { pair: 'OPUSDT', reason: 'чистый драг (аудит)', date: '2026-06-01' },
  ]
  return (
    <>
      <SubHead title="Блэклист пар" hint="исключены из вселенной" />
      <div className="overflow-x-auto">
        <table className="dt">
          <thead>
            <tr>
              <th>Пара</th>
              <th>Причина</th>
              <th>Дата</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.pair}>
                <td className="font-semibold text-bone">{r.pair}</td>
                <td className="text-fog">{r.reason}</td>
                <td className="tnum text-ash">{r.date}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Button size="sm" className="mt-3">
        + Добавить пару
      </Button>
      <SaveBar />
    </>
  )
}

function BillingDefaults() {
  return (
    <>
      <SubHead title="Биллинг-дефолты" hint="префилл договора" />
      <Field label="Комиссия с прибыли, %" hint="модель HWM (ADR-0011)">
        <input className={inputCls} defaultValue="15" />
      </Field>
      <Field label="Мин. депозит, $" hint="пол $500">
        <input className={inputCls} defaultValue="1000" />
      </Field>
      <Field label="Период расчёта" hint="v1 — месяц">
        <select className={selectCls} defaultValue="месяц">
          <option>месяц</option>
          <option>квартал</option>
        </select>
      </Field>
      <Field label="Валюта">
        <select className={selectCls} defaultValue="USDT">
          <option>USDT</option>
          <option>USDC</option>
        </select>
      </Field>
      <SaveBar note="дефолты подставляются при создании договора клиента" />
    </>
  )
}

function Assistants() {
  const [cavall, setCavall] = useState(true)
  const [archimed, setArchimed] = useState(false)
  return (
    <>
      <SubHead title="Помощники" hint="сборка помощников — отдельной фазой" />
      <Field label="Ключ ИИ" hint="из подписки · маскирован">
        <input className={inputCls + ' w-40'} defaultValue="sk-••••••" />
      </Field>
      <Field label="Кавалл — сторож-диагност" hint="мониторинг 24/7 → Системные тревоги">
        <Switch checked={cavall} onChange={setCavall} />
      </Field>
      <Field label="Архимед — авто-испытатель" hint="Оптимизатор в Кузнице (fitness = OOS-канон)">
        <Switch checked={archimed} onChange={setArchimed} />
      </Field>
      <div className="mt-2 rounded-card border border-line bg-panel px-3 py-2 text-[12px] text-ash">
        Кавалл и Архимед — витрина; полноценная сборка после консоли (отдельная фаза, #34).
      </div>
      <SaveBar />
    </>
  )
}

function AuditLog() {
  const rows = [
    { ts: '10:14', actor: 'Оператор', action: 'contract_signed', entity: 'Клиент-11' },
    { ts: '09:02', actor: 'Оператор', action: 'billing_activated', entity: 'acc-021' },
    { ts: '08:47', actor: 'system:period-generator', action: 'period_generation_skipped', entity: 'acc-007' },
  ]
  return (
    <>
      <SubHead title="Журнал аудита" hint="каждое действие — строка (закон №4)" />
      <div className="overflow-x-auto">
        <table className="dt">
          <thead>
            <tr>
              <th>Время</th>
              <th>Кто</th>
              <th>Действие</th>
              <th>Объект</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="tnum text-ash">{r.ts}</td>
                <td className="text-fog">{r.actor}</td>
                <td className="text-silver">{r.action}</td>
                <td className="text-fog">{r.entity}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}
