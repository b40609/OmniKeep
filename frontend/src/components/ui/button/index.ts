import { cva, type VariantProps } from 'class-variance-authority'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium transition-all duration-200 active:scale-[0.96] disabled:pointer-events-none disabled:opacity-40 select-none cursor-pointer rounded-full',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground shadow-sm hover:brightness-95 active:brightness-90',
        secondary: 'bg-muted text-primary font-semibold hover:bg-accent',
        ghost: 'text-primary hover:bg-muted',
        outline: 'border border-border-strong bg-card text-foreground font-semibold hover:bg-muted',
        danger: 'bg-danger-soft text-danger font-semibold hover:bg-danger/25',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-9 px-4 text-xs',
        sm: 'h-7 px-3 text-2xs',
        lg: 'h-11 px-6 text-sm',
        icon: 'size-9',
        'icon-sm': 'size-7',
        'icon-lg': 'size-11',
      },
    },
    defaultVariants: { variant: 'default', size: 'default' },
  },
)

export type ButtonVariants = VariantProps<typeof buttonVariants>
