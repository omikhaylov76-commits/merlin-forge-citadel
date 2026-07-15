import { cva, type VariantProps } from 'class-variance-authority'
import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/cn'

// Кнопка «слаш» (пилюля). Паттерн shadcn/ui: CVA-варианты + forwardRef.
const button = cva(
  'inline-flex items-center justify-center gap-2 rounded-pill text-[13px] font-medium tracking-tight ' +
    'transition-colors disabled:opacity-50 disabled:pointer-events-none whitespace-nowrap ' +
    'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-copper/60',
  {
    variants: {
      variant: {
        default: 'bg-floating text-bone border border-line hover:border-copper/50',
        primary: 'bg-copper/15 text-copper border border-copper/40 hover:bg-copper/25',
        ghost: 'text-fog hover:text-bone hover:bg-floating',
        danger: 'bg-danger/12 text-danger border border-danger/40 hover:bg-danger/20',
      },
      size: { sm: 'h-8 px-3', md: 'h-9 px-4', icon: 'h-9 w-9' },
    },
    defaultVariants: { variant: 'default', size: 'md' },
  },
)

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button ref={ref} className={cn(button({ variant, size }), className)} {...props} />
  ),
)
Button.displayName = 'Button'
