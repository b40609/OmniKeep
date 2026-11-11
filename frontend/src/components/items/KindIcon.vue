<script setup lang="ts">
import { Code, MessageSquare, SquarePlay, FileText } from 'lucide-vue-next'
import type { ItemKind } from '@/lib/wall'

defineProps<{ kind: ItemKind }>()
const icons = { project: Code, post: MessageSquare, video: SquarePlay, article: FileText }
</script>

<template>
  <component :is="icons[kind] ?? FileText" aria-hidden="true" />
</template>
