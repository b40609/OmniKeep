<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from 'vue'
import { BookX } from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { renderMarkdown, useCodeCopy } from '@/lib/markdown'

const ui = useUiStore()
const contentRef = ref<HTMLElement | null>(null)
let detachCodeCopy: (() => void) | null = null

watch(
  () => [ui.activeItem?.id, ui.activeItem?.content_raw] as const,
  async () => {
    detachCodeCopy?.()
    detachCodeCopy = null
    if (!ui.activeItem?.content_raw) return
    await Promise.resolve()
    detachCodeCopy = useCodeCopy(contentRef.value)
  },
  { immediate: true },
)
onBeforeUnmount(() => detachCodeCopy?.())
</script>

<template>
  <div class="mx-auto max-w-3xl p-5 lg:p-8">
    <div
      v-if="ui.activeItem?.content_raw"
      ref="contentRef"
      class="prose-reader"
      :style="{ fontSize: ui.readerFontSize + 'px', lineHeight: ui.readerLineHeight }"
      v-html="renderMarkdown(ui.activeItem.content_raw)"
    />
    <div v-else class="flex flex-col items-center gap-3 rounded-xl border border-border bg-card py-16 text-center">
      <BookX class="size-8 text-subtle-foreground" />
      <p class="font-mono text-xs text-muted-foreground">未抓取到原文快照或純淨內文</p>
    </div>
  </div>
</template>
