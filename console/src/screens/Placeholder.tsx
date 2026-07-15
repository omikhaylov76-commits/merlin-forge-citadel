import { EmptyState } from '@/components/ui/states'

// Экран-заглушка для разделов, которые раскатываются на следующих шагах Ф4 (по одному).
export function Placeholder({ title }: { title: string }) {
  return (
    <div className="mx-auto max-w-[1216px]">
      <div className="mb-5">
        <div className="text-[11px] uppercase tracking-widest text-ash">Раздел</div>
        <div className="font-serif text-[28px] text-bone">{title}</div>
      </div>
      <div className="rounded-card border border-line bg-card">
        <EmptyState
          title={`${title} — в сборке`}
          hint="Экран появится на следующих шагах Ф4 (раскатка по разделам)."
          icon="◫"
        />
      </div>
    </div>
  )
}
