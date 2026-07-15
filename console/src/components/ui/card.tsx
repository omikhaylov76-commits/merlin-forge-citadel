import { type HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

// Карточка «слаш»: утоплённая поверхность (глубже фона) со скруглением 10px и тонкой границей.
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-card border border-line bg-card p-6', className)}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cn('mb-4 flex items-center justify-between gap-3', className)} {...props} />
  )
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h3 className={cn('text-[15px] font-semibold tracking-tight text-silver', className)} {...props} />
  )
}
