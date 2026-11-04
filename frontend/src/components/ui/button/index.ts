import { cva, type VariantProps } from 'class-variance-authority'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium transition-colors duration-150 disabled:pointer-events-none disabled:opacity-40 select-none cursor-pointer rounded-lg',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary-hover',
        secondary: 'bg-muted text-primary-soft-foreground font-semibold hover:bg-accent',
        ghost: 'text-primary-soft-foreground hover:bg-muted',
        outline: 'border border-border-strong bg-card text-foreground font-semibold hover:bg-muted',
        danger: 'bg-danger-soft text-danger font-semibold hover:bg-danger/25',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'min-h-11 px-4 text-sm',
        sm: 'min-h-11 px-3 text-xs',
        lg: 'h-11 px-6 text-sm',
        icon: 'size-11',
        'icon-sm': 'size-11',
        'icon-lg': 'size-11',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export type ButtonVariants = VariantProps<typeof buttonVariants>
