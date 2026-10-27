<script setup lang="ts">
import { ref, computed } from 'vue'
import {
  Instagram, Facebook, Youtube, AtSign, Globe, KeyRound,
  LogIn, RefreshCw, CheckCircle2, CircleDashed, ShieldCheck, Loader2,
} from 'lucide-vue-next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Badge from '@/components/ui/badge/Badge.vue'
import Button from '@/components/ui/button/Button.vue'
import * as api from '@/lib/api'
import type { SessionBridgeSnapshot, SessionPlatformId } from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import { toast } from 'vue-sonner'

const ui = useUiStore()
const bridge = ref<SessionBridgeSnapshot | null>(null)
const loading = ref(false)
const loggingIn = ref<SessionPlatformId | null>(null)

const PLATFORM_META: Record<SessionPlatformId, { label: string; desc: string; icon: unknown }> = {
  instagram: { label: 'Instagram', desc: 'Reels、貼文與限時動態', icon: Instagram },
  facebook: { label: 'Facebook', desc: '貼文、Reels 與社團內容', icon: Facebook },
  google: { label: 'YouTube / Google', desc: '會員專屬與年齡限制影片', icon: Youtube },
  x: { label: 'X (Twitter)', desc: '貼文與 Thread 全文', icon: AtSign },
}

const connectedCount = computed(
  () => bridge.value?.platforms.filter((p) => p.connected).length ?? 0,
)

const modeLabel = computed(() => {
  switch (bridge.value?.mode) {
    case 'cdp': return 'CDP 會話橋接'
    case 'cookiefile': return 'cookies.txt 匯入'
    case 'none': return '尚未連結'
    default: return '偵測中…'
  }
})

async function load() {
  loading.value = true
  try {
    bridge.value = (await api.getSessionStatus()).bridge
  } catch (e) {
    toast.error('無法取得會話狀態', { description: (e as Error).message })
  } finally {
    loading.value = false
  }
}

async function login(platform: SessionPlatformId) {
  loggingIn.value = platform
  const meta = PLATFORM_META[platform]
  try {
    await api.openPlatformLogin(platform)
    toast.info(`${meta.label} 登入視窗已開啟`, {
      description: '完成登入後按「重新檢測」，Chrome 將返回背景模式並保留本機登入狀態。',
      duration: 8000,
    })
    // Poll briefly for the connection to appear
    for (let i = 0; i < 12; i++) {
      await new Promise((r) => setTimeout(r, 5000))
      await load()
      const p = bridge.value?.platforms.find((x) => x.id === platform)
      if (p?.connected) {
        toast.success(`${meta.label} 已連結`)
        break
      }
      if (!loggingIn.value) break // dialog closed by user
    }
  } catch (e) {
    toast.error('開啟登入視窗失敗', { description: (e as Error).message })
  } finally {
    loggingIn.value = null
  }
}

async function refresh() {
  loading.value = true
  try {
    bridge.value = (await api.refreshSession()).bridge
    toast.success('已重新提取會話')
  } catch (e) {
    toast.error('重新提取失敗', { description: (e as Error).message })
  } finally {
    loading.value = false
  }
}

// Load on open
import { watch } from 'vue'
watch(
  () => ui.showSessionModal,
  (open) => {
    if (open) load()
  },
)
</script>

<template>
  <Dialog :open="ui.showSessionModal" @update:open="(v) => (ui.showSessionModal = v)">
    <DialogContent class="max-w-lg">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <KeyRound class="size-4 text-primary-soft-foreground" />
          會話連結 · Account Sessions
        </DialogTitle>
        <DialogDescription>
          登入一次即永久保存於本機自動化 Chrome profile，所有平台內容解析都會帶上你的會員狀態。Session 只存本機，不會上傳。
        </DialogDescription>
      </DialogHeader>

      <!-- Bridge status banner -->
      <div class="glass-tint flex items-center justify-between rounded-xl px-3.5 py-2.5 text-xs">
        <div class="flex items-center gap-2">
          <ShieldCheck class="size-4" :class="connectedCount > 0 ? 'text-success' : 'text-subtle-foreground'" />
          <div>
            <p class="font-semibold text-foreground">{{ modeLabel }}</p>
            <p v-if="bridge" class="font-mono text-2xs text-subtle-foreground">
              CDP :{{ bridge.cdp_port }} · {{ bridge.total_cookies }} cookies
              <span v-if="bridge.cookie_file_exists"> · cookies.txt</span>
            </p>
          </div>
        </div>
        <Button variant="secondary" size="sm" :disabled="loading" @click="refresh">
          <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
          重新檢測
        </Button>
      </div>

      <!-- Platform rows -->
      <div class="space-y-2">
        <div
          v-for="p in bridge?.platforms ?? [
            { id: 'instagram', connected: false, cookies: 0 },
            { id: 'facebook', connected: false, cookies: 0 },
            { id: 'google', connected: false, cookies: 0 },
          ]"
          :key="p.id"
          class="flex items-center justify-between gap-3 rounded-xl border p-3 transition-all duration-150"
          :class="p.connected ? 'border border-success/30 bg-success-soft/40' : 'border-0 bg-white/45 shadow-sm dark:bg-white/[0.06]'"
        >
          <div class="flex min-w-0 items-center gap-3">
            <div
              class="flex size-9 shrink-0 items-center justify-center rounded-lg border"
              :class="p.connected ? 'border-success/30 bg-success-soft text-success' : 'border-border bg-muted text-muted-foreground'"
            >
              <component :is="PLATFORM_META[p.id as SessionPlatformId]?.icon ?? Globe" class="size-4.5" />
            </div>
            <div class="min-w-0">
              <p class="flex items-center gap-1.5 text-xs font-bold text-foreground">
                {{ PLATFORM_META[p.id as SessionPlatformId]?.label ?? p.id }}
                <CheckCircle2 v-if="p.connected" class="size-3.5 text-success" />
                <CircleDashed v-else class="size-3.5 text-subtle-foreground" />
              </p>
              <p class="truncate text-2xs text-muted-foreground">
                {{ PLATFORM_META[p.id as SessionPlatformId]?.desc }}
                <span v-if="p.connected" class="font-mono text-success/80">· {{ p.cookies }} cookies</span>
              </p>
            </div>
          </div>
          <Button
            :variant="p.connected ? 'secondary' : 'default'"
            size="sm"
            :disabled="loggingIn !== null"
            @click="login(p.id as SessionPlatformId)"
          >
            <Loader2 v-if="loggingIn === p.id" class="size-3.5 animate-spin" />
            <LogIn v-else class="size-3.5" />
            {{ p.connected ? '重新登入' : '登入' }}
          </Button>
        </div>
      </div>

      <p class="rounded-lg border border-border bg-background-subtle p-2.5 text-2xs leading-relaxed text-muted-foreground">
        <Badge class="mr-1 bg-primary-soft text-primary-soft-foreground border border-primary/30">提示</Badge>
        登入視窗是獨立的 OmniKeep 自動化 Chrome，與你日常瀏覽器互不干擾。也可改用
        <span class="font-mono text-foreground">cookies.txt</span> 匯入（放置於專案根目錄即自動優先採用）。
      </p>
    </DialogContent>
  </Dialog>
</template>
