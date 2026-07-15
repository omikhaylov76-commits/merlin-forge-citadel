import { cva, type VariantProps } from 'class-variance-authority'
import { type HTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

// Пилюля-статус «слаш»: семафор состояния бота/периода (в работе/пауза/тревога/стоп/деньги).
const badge = cva(
  'inline-flex items-center gap-1.5 rounded-pill border px-2.5 py-0.5 text-[11px] font-medium tracking-tight',
  {
    variants: {
      tone: {
        neutral: 'border-line bg-floating text-fog',
        live: 'border-ok/40 bg-ok/10 text-ok',
        pause: 'border-steel/40 bg-floating text-mist',
        alarm: 'border-copper/50 bg-copper/10 text-copper',
        kill: 'border-danger/50 bg-danger/10 text-danger',
        gold: 'border-gold/40 bg-gold/10 text-gold',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badge> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badge({ tone }), className)} {...props} />
}
