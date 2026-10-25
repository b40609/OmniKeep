<script setup lang="ts">
import { type ButtonVariants, buttonVariants } from '.'
import { cn } from '@/lib/utils'

const props = withDefaults(
  defineProps<{
    variant?: ButtonVariants['variant']
    size?: ButtonVariants['size']
    class?: string
  }>(),
  { variant: 'default', size: 'default' },
)
</script>

<template>
  <button :class="cn(buttonVariants({ variant, size }), props.class)">
    <slot />
  </button>
</template>
