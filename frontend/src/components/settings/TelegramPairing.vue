<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Link2 } from 'lucide-vue-next'
import { createTelegramPairing, getTelegramStatus, type TelegramPairing, type TelegramStatus } from '@/lib/api'

/**
 * Binds a Telegram account through a one-time t.me link. Sits under the list of
 * bound accounts in 設定 › 收錄管道, which is the one place those accounts are shown.
 */
const emit = defineEmits<{ (e: 'refreshed', boundIds: number[]): void }>()
const status = ref<TelegramStatus | null>(null)
const pairing = ref<TelegramPairing | null>(null)
const busy = ref(false)
const errorText = ref('')

const expiresAt = computed(() =>
  pairing.value ? new Date(pairing.value.expires_at * 1000).toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' }) : '',
)

async function refresh() {
  errorText.value = ''
  try {
    status.value = await getTelegramStatus()
    if (pairing.value && !status.value.pairing_expires_at) pairing.value = null // used or expired
    emit('refreshed', status.value.bound_user_ids)
  } catch (e) {
    errorText.value = e instanceof Error ? e.message : String(e)
  }
}

async function pair() {
  busy.value = true
  try {
    pairing.value = await createTelegramPairing()
  } catch (e) {
    toast.error('無法產生配對連結', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    busy.value = false
  }
}

async function copy() {
  if (!pairing.value) return
  await navigator.clipboard.writeText(pairing.value.link)
  toast.success('已複製配對連結')
}

onMounted(refresh)
defineExpose({ refresh })
</script>

<template>
  <div class="space-y-3">
    <p v-if="errorText" class="set-error">無法讀取 Telegram 狀態：{{ errorText }}</p>
    <p v-else-if="status && !status.configured" class="set-text">先儲存機器人權杖，才能產生配對連結。</p>
    <template v-else-if="status">
      <div v-if="pairing" class="set-panel space-y-3">
        <p class="text-sm">用要綁定的 Telegram 帳號開啟這個連結，按「開始」就完成。{{ expiresAt }} 前有效，只能用一次。</p>
        <div class="flex flex-wrap gap-2">
          <a :href="pairing.link" target="_blank" rel="noopener" class="set-button set-button--primary">在 Telegram 開啟</a>
          <button type="button" class="set-button" @click="copy">複製連結</button>
          <button type="button" class="set-button set-button--text" @click="refresh">我綁好了</button>
        </div>
      </div>
      <button v-else type="button" class="set-button" :disabled="busy" @click="pair"><Link2 aria-hidden="true" />產生配對連結</button>
    </template>
  </div>
</template>
