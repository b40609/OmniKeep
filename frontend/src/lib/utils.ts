import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Standardized motion easings/durations used across interactive components. */
export const motion = {
  fast: 120,
  base: 200,
  slow: 350,
  easeOut: 'cubic-bezier(0.22, 1, 0.36, 1)',
  spring: 'cubic-bezier(0.34, 1.3, 0.64, 1)',
} as const
