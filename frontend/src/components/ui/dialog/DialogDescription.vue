<script setup lang="ts">
import { DialogDescription, type DialogDescriptionProps } from 'reka-ui'
import { cn } from '@/lib/utils'
const props = defineProps<DialogDescriptionProps & { class?: string }>()
</script>

<template>
  <DialogDescription v-bind="props" :class="cn('text-xs text-muted-foreground', props.class)">
    <slot />
  </DialogDescription>
</template>
