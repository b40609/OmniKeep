<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import { Send } from 'lucide-vue-next'
import Button from '@/components/ui/button/Button.vue'
import { buttonVariants } from '@/components/ui/button'
import { createTelegramPairing, getTelegramStatus, type TelegramPairing, type TelegramStatus } from '@/lib/api'

/** Binds a Telegram account as an owner through a one-time t.me link (no .env editing). */
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
  <section class="space-y-2 border-t border-border pt-3 text-sm">
    <h3 class="flex items-center gap-2 font-medium"><Send class="size-4" /> Telegram</h3>
    <p v-if="errorText" class="text-danger">無法讀取 Telegram 狀態：{{ errorText }}</p>
    <p v-else-if="!status" class="text-muted-foreground">檢查中…</p>
    <p v-else-if="!status.configured" class="text-muted-foreground">
      伺服器沒有設定 <code>TELEGRAM_BOT_TOKEN</code>，Telegram Bot 未啟用。
    </p>
    <template v-else>
      <p class="text-muted-foreground">
        {{ status.bound_user_ids.length ? `已綁定的帳號：${status.bound_user_ids.join('、')}` : '還沒有綁定任何 Telegram 帳號。' }}
      </p>
      <div v-if="pairing" class="space-y-2 rounded-lg border border-border p-3">
        <p>
          用要綁定的 Telegram 帳號開啟這個連結，按「開始」即完成。{{ expiresAt }} 前有效，只能用一次。
        </p>
        <div class="flex flex-wrap gap-2">
          <a :href="pairing.link" target="_blank" rel="noopener" :class="buttonVariants()">在 Telegram 開啟</a>
          <Button variant="secondary" @click="copy">複製連結</Button>
          <Button variant="ghost" @click="refresh">我綁好了</Button>
        </div>
      </div>
      <Button v-else variant="secondary" :disabled="busy" @click="pair">產生 Telegram 配對連結</Button>
    </template>
  </section>
</template>
