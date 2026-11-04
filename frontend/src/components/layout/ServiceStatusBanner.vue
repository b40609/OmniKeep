<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { TriangleAlert, X } from 'lucide-vue-next'
import Button from '@/components/ui/button/Button.vue'
import { getServiceStatus, type ServiceStatus } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/** Says so when AI calls fail (a revoked key used to show up only in the server log). */
const ui = useUiStore()
const status = ref<ServiceStatus | null>(null)
const dismissed = ref(sessionStorageGet())

const LABELS = { llm: 'AI 分析', embeddings: '雲端向量', gemini: 'Gemini', ollama: '本機 Ollama 向量' } as const
const POLL_MS = 120_000

function sessionStorageGet() {
  try {
    return sessionStorage.getItem('omnikeep-status-dismissed') ?? ''
  } catch {
    return ''
  }
}

const problem = computed(() => {
  const s = status.value
  if (!s) return null
  const unreadable = s.undecryptable.filter((k) => !k.startsWith('VAPID_'))
  if (unreadable.length) {
    return { text: `有 ${unreadable.length} 個金鑰無法解密，目前改用 .env 的值，請到設定重新輸入。`, action: '重新輸入', tab: 'ai' }
  }
  if (s.undecryptable.length) {
    return { text: '推播金鑰無法解密（主金鑰和當初加密時不同），推播暫停。請還原主金鑰檔，或到設定重新產生。', action: '查看', tab: 'push' }
  }
  const failing = (Object.entries(s.services) as [keyof typeof LABELS, { ok: boolean; status: number | null; message: string }][])
    .filter(([, o]) => o && !o.ok)
  if (failing.length) {
    const [name, outcome] = failing[0]
    const code = outcome.status ? `HTTP ${outcome.status}` : '連線失敗'
    const names = failing.map(([n]) => LABELS[n]).join('、')
    return { text: `${names}目前無法使用（${LABELS[name]}：${code}${outcome.message ? `，${outcome.message}` : ''}）。`, action: '檢查設定', tab: 'ai' }
  }
  if (s.needs_setup) return { text: '還沒設定 AI 服務商，新收藏不會經過 AI 分析。', action: '開始設定', tab: 'wizard' }
  return null
})

const visible = computed(() => problem.value && problem.value.text !== dismissed.value)

async function refresh() {
  try {
    status.value = await getServiceStatus()
  } catch {
    /* offline or signed out: keep the last state */
  }
}

function act() {
  const tab = problem.value?.tab ?? 'ai'
  if (tab === 'wizard') ui.showSetupWizard = true
  else ui.openSettings(tab)
}

function dismiss() {
  if (!problem.value) return
  dismissed.value = problem.value.text
  try {
    sessionStorage.setItem('omnikeep-status-dismissed', dismissed.value)
  } catch {
    /* private mode */
  }
}

let timer: ReturnType<typeof setInterval> | undefined
onMounted(() => {
  refresh()
  timer = setInterval(refresh, POLL_MS)
  window.addEventListener('focus', refresh)
})
onUnmounted(() => {
  clearInterval(timer)
  window.removeEventListener('focus', refresh)
})
watch(() => ui.settingsVersion, refresh)
</script>

<template>
  <div
    v-if="visible && problem"
    role="alert"
    class="flex shrink-0 items-center gap-2 border-b border-warning/30 bg-warning/10 px-4 py-2 text-xs text-foreground"
  >
    <TriangleAlert class="size-4 shrink-0 text-warning" />
    <p class="min-w-0 flex-1 truncate" :title="problem.text">{{ problem.text }}</p>
    <Button size="sm" variant="secondary" class="shrink-0" @click="act">{{ problem.action }}</Button>
    <button type="button" class="shrink-0 cursor-pointer rounded p-1 text-muted-foreground hover:text-foreground" aria-label="暫時隱藏" @click="dismiss">
      <X class="size-3.5" />
    </button>
  </div>
</template>
