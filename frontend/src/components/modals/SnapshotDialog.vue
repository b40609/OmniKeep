<script setup lang="ts">
import { computed } from 'vue'
import { Camera, ExternalLink } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { SNAPSHOT_SANDBOX, snapshotSrcdoc } from '@/lib/snapshot'
import { useUiStore } from '@/stores/ui'

/**
 * The offline copy of a page, full screen. The copy is untrusted content from the source
 * site: it is only ever put into the sandboxed frame below (lib/snapshot.ts), never into
 * this document and never opened as a page of this origin.
 */
const ui = useUiStore()
const srcdoc = computed(() => (ui.snapshotView ? snapshotSrcdoc(ui.snapshotView.html) : ''))
const isWebLink = computed(() => /^https?:\/\//i.test(ui.snapshotView?.url ?? ''))

function onOpenChange(open: boolean) {
  if (!open) ui.snapshotView = null
}
</script>

<template>
  <Dialog :open="!!ui.snapshotView" @update:open="onOpenChange">
    <DialogContent
      v-if="ui.snapshotView"
      class="flex h-[94dvh] w-[96vw] max-w-none flex-col gap-0 overflow-hidden p-0"
    >
      <div class="flex shrink-0 items-center gap-2.5 border-b border-border py-3 pl-4 pr-14">
        <div class="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Camera class="size-4" />
        </div>
        <DialogHeader class="min-w-0 flex-1">
          <DialogTitle class="truncate text-sm">{{ ui.snapshotView.title || '離線快照' }}</DialogTitle>
          <DialogDescription class="truncate text-2xs">
            收錄時保存的網頁。這裡不會執行網頁裡的程式，連結會在新分頁開啟。
          </DialogDescription>
        </DialogHeader>
        <a
          v-if="isWebLink"
          :href="ui.snapshotView.url"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex min-h-11 shrink-0 items-center gap-1 rounded-lg border border-border px-3 text-xs text-muted-foreground transition-colors hover:bg-accent"
        >
          <ExternalLink class="size-3.5" />
          <span class="max-sm:hidden">開啟原始網頁</span>
        </a>
      </div>
      <!-- A light background: most pages assume one and set none of their own. -->
      <iframe
        :sandbox="SNAPSHOT_SANDBOX"
        :srcdoc="srcdoc"
        referrerpolicy="no-referrer"
        title="離線快照內容"
        class="min-h-0 w-full flex-1 border-0 bg-white"
      />
    </DialogContent>
  </Dialog>
</template>
