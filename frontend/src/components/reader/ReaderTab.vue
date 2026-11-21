<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { BookX, ArrowUpRight, Camera } from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { renderMarkdown, useCodeCopy } from '@/lib/markdown'
import { originLink } from '@/lib/originLink'
import { useMutations } from '@/composables/useMutations'
import { useSnapshotAvailable } from '@/composables/useSnapshotAvailable'

const ui = useUiStore()
const { openSnapshot } = useMutations()
const origin = computed(() => originLink(ui.activeItem?.url))
const hasSnapshot = useSnapshotAvailable()
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
  <div class="mx-auto max-w-[54rem] p-5 lg:p-8">
    <div
      v-if="ui.activeItem?.content_raw"
      ref="contentRef"
      class="prose-reader mx-auto max-w-[40em]"
      :style="{ fontSize: ui.readerFontSize + 'px', lineHeight: ui.readerLineHeight }"
      v-html="renderMarkdown(ui.activeItem.content_raw)"
    />
    <div v-else class="flex flex-col items-center gap-3 rounded-xl border border-border bg-card py-16 text-center">
      <BookX class="size-8 text-subtle-foreground" />
      <p class="font-mono text-xs text-muted-foreground">未抓取到原文快照或純淨內文</p>
      <div v-if="origin || hasSnapshot" class="mt-1 flex flex-wrap justify-center gap-2">
        <a
          v-if="origin"
          :href="origin.href"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-border px-4 text-sm text-foreground transition-colors hover:bg-accent"
        >{{ origin.action }}<ArrowUpRight class="size-3.5" aria-hidden="true" /><span class="sr-only">（新分頁）</span></a>
        <button
          v-if="hasSnapshot && ui.activeItem"
          type="button"
          class="inline-flex min-h-11 cursor-pointer items-center gap-1.5 rounded-lg border border-border px-4 text-sm text-muted-foreground transition-colors hover:bg-accent"
          @click="openSnapshot(ui.activeItem)"
        ><Camera class="size-3.5" aria-hidden="true" />開啟離線快照</button>
      </div>
    </div>
  </div>
</template>
