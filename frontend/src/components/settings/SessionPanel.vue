<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { Loader2, LogIn, RefreshCw } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import * as api from '@/lib/api'
import type { SessionBridgeSnapshot, SessionPlatformId } from '@/lib/api'

/**
 * 社群平台登入: sign in once in OmniKeep's own Chrome profile, so pages that need
 * an account (Reels, members-only videos) can be read. Sessions stay on this computer.
 */
const bridge = ref<SessionBridgeSnapshot | null>(null)
const loading = ref(false)
const loggingIn = ref<SessionPlatformId | null>(null)
let alive = true

const PLATFORM_META: Record<SessionPlatformId, { label: string; desc: string }> = {
  instagram: { label: 'Instagram', desc: 'Reels、貼文與限時動態' },
  facebook: { label: 'Facebook', desc: '貼文、Reels 與社團內容' },
  google: { label: 'YouTube／Google', desc: '會員專屬與有年齡限制的影片' },
  x: { label: 'X', desc: '貼文與串文全文' },
}
const FALLBACK = [
  { id: 'instagram', connected: false, cookies: 0 },
  { id: 'facebook', connected: false, cookies: 0 },
  { id: 'google', connected: false, cookies: 0 },
]
const platforms = computed(() => bridge.value?.platforms ?? FALLBACK)

const modeText = computed(() => {
  switch (bridge.value?.mode) {
    case 'cdp': return '使用 OmniKeep 自己的 Chrome 登入狀態'
    case 'cookiefile': return '使用匯入的 cookies.txt'
    case 'none': return '還沒有登入任何平台'
    default: return '檢查中…'
  }
})

async function load() {
  loading.value = true
  try {
    bridge.value = (await api.getSessionStatus()).bridge
  } catch (e) {
    toast.error('無法取得登入狀態', { description: (e as Error).message })
  } finally {
    loading.value = false
  }
}

async function login(platform: SessionPlatformId) {
  loggingIn.value = platform
  const meta = PLATFORM_META[platform]
  try {
    await api.openPlatformLogin(platform)
    toast.info(`已開啟 ${meta.label} 的登入視窗`, {
      description: '登入完成後按「重新檢查」。登入狀態只存在這台電腦。',
      duration: 8000,
    })
    // Poll briefly for the connection to appear
    for (let i = 0; i < 12; i++) {
      await new Promise((r) => setTimeout(r, 5000))
      if (!alive) break // the settings page was closed
      await load()
      const p = bridge.value?.platforms.find((x) => x.id === platform)
      if (p?.connected) {
        toast.success(`${meta.label} 已登入`)
        break
      }
      if (!loggingIn.value) break
    }
  } catch (e) {
    toast.error('無法開啟登入視窗', { description: (e as Error).message })
  } finally {
    loggingIn.value = null
  }
}

async function refresh() {
  loading.value = true
  try {
    bridge.value = (await api.refreshSession()).bridge
    toast.success('已重新檢查登入狀態')
  } catch (e) {
    toast.error('重新檢查失敗', { description: (e as Error).message })
  } finally {
    loading.value = false
  }
}

onMounted(load)
onBeforeUnmount(() => (alive = false))
</script>

<template>
  <SettingBlock
    id="sessions"
    title="社群平台登入"
    description="登入一次，之後讀取需要帳號才看得到的內容時會帶上登入狀態。登入視窗是 OmniKeep 自己的 Chrome，和你平常用的瀏覽器分開；登入狀態只存在這台電腦。"
  >
    <SettingRow :name="modeText">
      <template v-if="bridge" #below>
        <p class="set-row__help">共 {{ bridge.total_cookies }} 筆 cookie<template v-if="bridge.cookie_file_exists">，另有 cookies.txt</template>。</p>
        <p v-if="bridge.playwright_installed === false" class="set-notice set-notice--warn mt-2">
          這台電腦沒有安裝 playwright，沒辦法開登入視窗。請改用 cookies.txt：放在專案資料夾就會自動採用。
        </p>
      </template>
      <button type="button" class="set-button" :disabled="loading" @click="refresh">
        <RefreshCw :class="loading ? 'animate-spin' : ''" aria-hidden="true" />重新檢查
      </button>
    </SettingRow>
    <SettingRow
      v-for="p in platforms"
      :key="p.id"
      :name="PLATFORM_META[p.id as SessionPlatformId]?.label ?? p.id"
      :help="PLATFORM_META[p.id as SessionPlatformId]?.desc"
    >
      <span class="set-status" :class="{ 'set-status--ok': p.connected }">{{ p.connected ? '已登入' : '未登入' }}</span>
      <button type="button" class="set-button" :disabled="loggingIn !== null" @click="login(p.id as SessionPlatformId)">
        <Loader2 v-if="loggingIn === p.id" class="animate-spin" aria-hidden="true" />
        <LogIn v-else aria-hidden="true" />
        {{ p.connected ? '重新登入' : '登入' }}
      </button>
    </SettingRow>
  </SettingBlock>
</template>
