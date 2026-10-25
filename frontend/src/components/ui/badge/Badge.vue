<script setup lang="ts">
import { cn } from '@/lib/utils'

const props = defineProps<{ class?: string }>()
</script>

<template>
  <span
    :class="
      cn(
        'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-2xs font-semibold tracking-normal',
        props.class,
      )
    "
  >
    <slot />
  </span>
</template>
