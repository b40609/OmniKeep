<script setup lang="ts">
import { Toaster as Sonner } from 'vue-sonner'
import { useTheme } from '@/composables/useTheme'

const { resolved } = useTheme()
</script>

<template>
  <Sonner
    :theme="resolved"
    class="toaster group"
    position="top-center"
    :offset="16"
    :duration="4500"
    :toast-options="{
      classes: {
        toast:
          'group toast group-[.toaster]:bg-white/75 group-[.toaster]:backdrop-blur-2xl group-[.toaster]:text-foreground group-[.toaster]:border group-[.toaster]:border-white/60 group-[.toaster]:shadow-float group-[.toaster]:rounded-2xl dark:group-[.toaster]:bg-zinc-800/75 dark:group-[.toaster]:border-white/10',
        title: 'group-[.toast]:text-sm group-[.toast]:font-semibold',
        description: 'group-[.toast]:text-muted-foreground group-[.toast]:text-xs',
        actionButton:
          'group-[.toast]:bg-primary group-[.toast]:text-primary-foreground group-[.toast]:rounded-full group-[.toast]:font-semibold',
        cancelButton:
          'group-[.toast]:bg-muted group-[.toast]:text-muted-foreground group-[.toast]:rounded-full',
      },
    }"
  />
</template>
