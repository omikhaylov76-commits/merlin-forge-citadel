import { PageHead, Toolbar, Chip } from '@/components/ui/page'
import { Badge } from '@/components/ui/badge'
import { reportsFixture as rows } from '@/lib/fixtures'

const statusTone = (s: string) =>
  s === 'отправлен' ? 'live' : s === 'скачан' ? 'neutral' : 'gold'

// Экран Отчёты (v1, спека #34): лёгкий архив документов. Сам отчёт клиента формируется КНОПКОЙ
// в карточке клиента; числа (комиссия/net) — из ядра (HWM). Здесь — список отправленного (демо).
export function Reports() {
  return (
    <div className="mx-auto max-w-[1880px]">
      <PageHead
        eyebrow="Журналы"
        title="Отчёты"
        desc="архив документов · отчёт клиента формируется в его карточке"
      />
      <Toolbar>
        <Chip active>Все</Chip>
        <Chip>HWM-счёт</Chip>
        <Chip>Выписка</Chip>
        <Chip>Налоговый</Chip>
      </Toolbar>
      <div className="overflow-x-auto rounded-card border border-line bg-card">
        <table className="dt">
          <thead>
            <tr>
              <th>Документ</th>
              <th>Тип</th>
              <th>Клиент</th>
              <th>Период</th>
              <th>Статус</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <td className="font-semibold text-bone">{r.doc}</td>
                <td className="text-fog">{r.type}</td>
                <td>{r.client}</td>
                <td className="tnum text-fog">{r.period}</td>
                <td>
                  <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
