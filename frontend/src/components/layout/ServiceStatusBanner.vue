<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { TriangleAlert, X } from 'lucide-vue-next'
import Button from '@/components/ui/button/Button.vue'
import { getServiceStatus, type ServiceStatus } from '@/lib/api'
import { summarizeServiceStatus } from '@/lib/serviceBanner'
import { useUiStore } from '@/stores/ui'

/** Says so when AI calls fail (a revoked key used to show up only in the server log). */
const ui = useUiStore()
const status = ref<ServiceStatus | null>(null)
const dismissed = ref(sessionStorageGet())

const POLL_MS = 120_000

function sessionStorageGet() {
  try {
    return sessionStorage.getItem('omnikeep-status-dismissed') ?? ''
  } catch {
    return ''
  }
}

const problem = computed(() => summarizeServiceStatus(status.value))

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
  else if (tab === 'push-keys') ui.openSettings('advanced', '', 'push-keys')
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
    <p class="min-w-0 flex-1 truncate" :title="problem.detail">{{ problem.text }}</p>
    <Button size="sm" variant="secondary" class="shrink-0" @click="act">{{ problem.action }}</Button>
    <button type="button" class="shrink-0 cursor-pointer rounded p-1 text-muted-foreground hover:text-foreground" aria-label="暫時隱藏" @click="dismiss">
      <X class="size-3.5" />
    </button>
  </div>
</template>
