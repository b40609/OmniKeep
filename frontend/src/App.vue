<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { toast } from 'vue-sonner'
import { initTheme } from '@/composables/useTheme'
import { useKeyboard } from '@/composables/useKeyboard'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { getSessionStatus, logBehaviorEvent, type SessionBridgeSnapshot } from '@/lib/api'
import AppHeader from '@/components/layout/AppHeader.vue'
import TriageBar from '@/components/layout/TriageBar.vue'
import ItemList from '@/components/items/ItemList.vue'
import ReaderPane from '@/components/reader/ReaderPane.vue'
import NoteDialog from '@/components/modals/NoteDialog.vue'
import CategoryDialog from '@/components/modals/CategoryDialog.vue'
import ShortcutsDialog from '@/components/modals/ShortcutsDialog.vue'
import RadarDialog from '@/components/modals/RadarDialog.vue'
import SessionDialog from '@/components/modals/SessionDialog.vue'
import WatchDialog from '@/components/modals/WatchDialog.vue'
import { Toaster } from '@/components/ui/sonner'

initTheme()

const items = useItemsStore()
const ui = useUiStore()

const headerRef = ref<InstanceType<typeof AppHeader> | null>(null)
const listRef = ref<InstanceType<typeof ItemList> | null>(null)
useKeyboard(() => headerRef.value)

// J/K navigation keeps the active row in view.
watch(
  () => ui.activeItem?.id,
  (id) => {
    if (id == null || items.viewMode !== 'list') return
    const idx = items.items.findIndex((i) => i.id === id)
    if (idx >= 0) listRef.value?.scrollToIndex(idx)
  },
)

// P1 behavior fuel: opening an item counts as a view event (fire-and-forget).
watch(
  () => ui.activeItem?.id,
  (id) => {
    if (id != null) logBehaviorEvent({ event_type: 'view', item_id: String(id) }).catch(() => {})
  },
)

/** Non-intrusive first-run hint when no platform session is connected. */
async function maybeShowSessionHint() {
  const DISMISS_KEY = 'omnikeep-session-hint-dismissed'
  try {
    if (localStorage.getItem(DISMISS_KEY)) return
    const bridge: SessionBridgeSnapshot = (await getSessionStatus()).bridge
    const socialItems = items.items.some(
      (i) => ['instagram', 'facebook', 'reel'].includes(i.source_type.toLowerCase()),
    )
    const connected = bridge.platforms.some((p) => p.connected)
    if (connected || !socialItems) return
    toast.info('提升 Reel / 社群內容解析成功率', {
      description: '偵測到尚未連結任何平台會話。登入一次 Instagram 或 Facebook，解析即可帶入會員狀態。',
      duration: 10000,
      action: {
        label: '前往設定',
        onClick: () => {
          ui.showSessionModal = true
        },
      },
      onDismiss: () => localStorage.setItem(DISMISS_KEY, '1'),
      onAutoClose: () => localStorage.setItem(DISMISS_KEY, '1'),
    })
  } catch {
    /* status endpoint unavailable — stay silent */
  }
}

onMounted(() => {
  items.refreshAll().then(maybeShowSessionHint)
})
</script>

<template>
  <!-- Liquid glass backdrop: colorful aurora the panels blur against -->
  <div class="aurora" aria-hidden="true">
    <i /><i /><i /><i />
  </div>

  <div class="relative z-10 flex h-screen flex-col overflow-hidden text-foreground">
    <AppHeader ref="headerRef" />
    <TriageBar />

    <!-- Master–detail workbench body -->
    <div class="relative flex min-h-0 flex-1 overflow-hidden">
      <!-- Master stream: one shared blur layer, rows are glass tints inside -->
      <div
        class="flex h-full min-w-0 flex-col transition-[width] duration-300 ease-out max-lg:w-full"
        :class="ui.activeItem ? 'lg:w-1/2 xl:w-5/12' : 'w-full'"
      >
        <ItemList ref="listRef" />
      </div>

      <!-- Detail reader -->
      <ReaderPane v-if="ui.activeItem" />
    </div>

    <!-- Modals -->
    <NoteDialog />
    <CategoryDialog />
    <ShortcutsDialog />
    <RadarDialog />
    <SessionDialog />
    <WatchDialog />
  </div>
  <Toaster />
</template>
