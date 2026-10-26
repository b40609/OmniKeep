<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { toast } from 'vue-sonner'
import { initTheme } from '@/composables/useTheme'
import { useKeyboard } from '@/composables/useKeyboard'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { getSessionStatus, getStats, setApiKey, logBehaviorEvent, type SessionBridgeSnapshot } from '@/lib/api'
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
import ImportDialog from '@/components/modals/ImportDialog.vue'
import { Toaster } from '@/components/ui/sonner'


initTheme()

const items = useItemsStore()
const ui = useUiStore()
const signedIn = ref(false)
const credential = ref('')
const loginError = ref('')
const loggingIn = ref(false)

function requireLogin() {
  signedIn.value = false
  setApiKey('')
  ui.activeItem = null
  items.items = []
  items.categories = []
  items.stats = { inbox: 0, starred: 0, archived: 0, total: 0 }
}

async function login() {
  loggingIn.value = true
  loginError.value = ''
  setApiKey(credential.value.trim())
  try {
    await getStats()
    credential.value = ''
    signedIn.value = true
    await items.refreshAll()
    await maybeShowSessionHint()
  } catch (error) {
    requireLogin()
    loginError.value = error instanceof Error ? error.message : '登入失敗'
  } finally {
    loggingIn.value = false
  }
}

const headerRef = ref<InstanceType<typeof AppHeader> | null>(null)
const listRef = ref<InstanceType<typeof ItemList> | null>(null)
useKeyboard(() => headerRef.value, () => signedIn.value)

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
  window.addEventListener('omnikeep-auth-required', requireLogin)
})
onUnmounted(() => window.removeEventListener('omnikeep-auth-required', requireLogin))
</script>

<template>
  <!-- Liquid glass backdrop: colorful aurora the panels blur against -->
  <div class="aurora" aria-hidden="true">
    <i /><i /><i /><i />
  </div>

  <form v-if="!signedIn" class="relative z-10 mx-auto mt-24 flex max-w-sm flex-col gap-4 rounded-xl border bg-background p-8 text-foreground" @submit.prevent="login">
    <h1 class="text-xl font-semibold">登入 OmniKeep</h1>
    <label for="api-key">存取金鑰</label>
    <input id="api-key" v-model="credential" type="password" autocomplete="off" required class="rounded border bg-background p-3" />
    <p class="text-sm text-muted-foreground">金鑰僅保留於本頁記憶體，重新整理後需再次登入。</p>
    <p v-if="loginError" role="alert" class="text-sm text-red-500">{{ loginError }}</p>
    <button type="submit" :disabled="loggingIn" class="rounded bg-primary p-3 text-primary-foreground">{{ loggingIn ? '驗證中…' : '登入' }}</button>
  </form>
  <div v-else class="relative z-10 flex h-screen flex-col overflow-hidden text-foreground">
    <button class="absolute right-4 bottom-2 z-50 text-xs text-muted-foreground" @click="requireLogin">登出</button>
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
    <ImportDialog />
  </div>

  <Toaster />
</template>
