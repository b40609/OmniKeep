<script setup lang="ts">
import { ref } from 'vue'
import { Loader2, PlugZap } from 'lucide-vue-next'
import { checkConnection, type CheckService, type ConnectionCheck } from '@/lib/api'
import { useSettingsForm } from '@/composables/useSettingsForm'

/**
 * Tests a service with what is typed in its block right now (saved or not);
 * empty boxes use the value in effect. Testing saves nothing.
 */
const props = defineProps<{ service: CheckService; label: string; keys: string[] }>()
const form = useSettingsForm()
const result = ref<ConnectionCheck | 'running' | null>(null)

async function run() {
  result.value = 'running'
  const values = Object.fromEntries(Object.entries(form.pendingFor(props.keys).values).filter(([, v]) => v !== ''))
  try {
    result.value = await checkConnection(props.service, values)
  } catch (e) {
    result.value = { ok: false, status: null, message: e instanceof Error ? e.message : String(e), detail: '' }
  }
}
</script>

<template>
  <button type="button" class="set-button" :disabled="result === 'running'" title="用目前輸入的值測試，不會儲存" @click="run">
    <Loader2 v-if="result === 'running'" class="animate-spin" aria-hidden="true" />
    <PlugZap v-else aria-hidden="true" />
    {{ label }}
  </button>
  <div v-if="result && result !== 'running'" role="status" class="set-notice basis-full" :class="result.ok ? 'set-notice--ok' : 'set-notice--bad'">
    <p>{{ result.message }}</p>
    <p v-if="result.detail" class="set-mono mt-1 opacity-80">{{ result.detail }}</p>
  </div>
</template>
