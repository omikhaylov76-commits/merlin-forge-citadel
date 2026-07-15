import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

// Слияние классов Tailwind без конфликтов (паттерн shadcn/ui).
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
