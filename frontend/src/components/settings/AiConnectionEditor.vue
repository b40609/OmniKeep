<script setup lang="ts">
import { computed } from 'vue'
import { ExternalLink, Loader2, PlugZap } from 'lucide-vue-next'
import Switch from '@/components/ui/switch/Switch.vue'
import Select from '@/components/ui/select/Select.vue'
import type { AiCard, AiSlot, AiTestResult } from '@/lib/api'
import { SLOT_TEXT } from '@/lib/settingsText'
import type { AiEditor } from './aiEditor'

/** The fields of one AI connection. The parent owns the state and does the saving and testing. */
const props = defineProps<{
  editor: AiEditor
  card: AiCard
  /** Model names to suggest: the card's own and the ones a test listed. */
  models: string[]
  slots: AiSlot[]
  /** Why it cannot be saved yet; null when it can. */
  problem: string | null
  extraError: string
  hasPreset: boolean
  test: AiTestResult | 'running' | undefined
  saving: boolean
}>()
const emit = defineEmits<{ (e: 'test'): void; (e: 'save'): void; (e: 'cancel'): void }>()

// The parent's object: fields are edited in place, which is what the parent expects.
const form = computed(() => props.editor)
const gemini = computed(() => props.card.kind === 'gemini')

const thinkingOptions = [
  { value: 'default', label: '模型預設' },
  { value: 'low', label: '低：快、用量少' },
  { value: 'medium', label: '中' },
  { value: 'high', label: '高：慢、用量多、分析較深入' },
]
const slotOptions = computed(() => [
  { value: 'none', label: '先不要，之後在「用途」加' },
  ...props.slots
    .filter((s) => (s.id !== 'video' || gemini.value) && (s.id !== 'embeddings' || !gemini.value))
    .map((s) => ({ value: s.id, label: `${SLOT_TEXT[s.id]?.label ?? s.label}（第 ${s.entries.length + 1} 順位）` })),
])
const keyPlaceholder = computed(() => {
  if (form.value.mode === 'edit') return form.value.clearKey ? '儲存後移除金鑰' : '留空表示不變'
  return gemini.value ? '多把金鑰用逗號分隔' : '貼上金鑰'
})
</script>

<template>
  <form class="set-panel set-form" @submit.prevent="emit('save')">
    <div>
      <p class="text-base font-semibold">{{ form.mode === 'new' ? '新增連線' : '編輯連線' }}：{{ card.label }}</p>
      <p class="set-text mt-1">{{ card.limits }}</p>
      <p v-if="card.notes" class="set-text">{{ card.notes }}</p>
      <p v-if="card.training_note" class="set-notice set-notice--warn mt-2">{{ card.training_note }}</p>
      <p v-if="card.ended" class="set-notice set-notice--warn mt-2">限時免費活動已在 {{ card.ends }} 結束，先到官網確認還能不能免費用。</p>
    </div>

    <div class="set-form__pair">
      <div>
        <label for="ai-label" class="set-label">名稱</label>
        <input id="ai-label" v-model="form.label" type="text" class="set-input">
        <p v-if="form.errors.label" class="set-error mt-1">{{ form.errors.label }}</p>
      </div>
      <div>
        <label for="ai-model" class="set-label">模型</label>
        <input id="ai-model" v-model="form.model" type="text" spellcheck="false" list="ai-models" class="set-input">
        <datalist id="ai-models">
          <option v-for="m in models" :key="m" :value="m" />
        </datalist>
        <p v-if="form.errors.model" class="set-error mt-1">{{ form.errors.model }}</p>
      </div>
    </div>

    <div v-if="!gemini">
      <label for="ai-url" class="set-label">API 位址</label>
      <input id="ai-url" v-model="form.baseUrl" type="url" spellcheck="false" class="set-input" :readonly="!card.editable_url && form.mode === 'new'">
      <p v-if="form.errors.base_url" class="set-error mt-1">{{ form.errors.base_url }}</p>
    </div>

    <div v-if="card.key_mode !== 'none'">
      <div class="flex items-baseline justify-between gap-3">
        <label for="ai-key" class="set-label">API 金鑰<span v-if="card.key_mode === 'optional'" class="font-normal text-muted-foreground">（選填）</span></label>
        <a v-if="card.key_url" :href="card.key_url" target="_blank" rel="noopener noreferrer" class="set-link inline-flex items-center gap-1 text-sm">
          取得金鑰 <ExternalLink class="size-4" aria-hidden="true" />
        </a>
      </div>
      <div class="flex gap-2">
        <input
          id="ai-key"
          v-model="form.key"
          type="password"
          autocomplete="new-password"
          spellcheck="false"
          class="set-input min-w-0 flex-1"
          :disabled="form.clearKey"
          :placeholder="keyPlaceholder"
        >
        <button v-if="form.mode === 'edit' && card.key_mode === 'optional'" type="button" class="set-button set-button--text" @click="form.clearKey = !form.clearKey">
          {{ form.clearKey ? '取消移除' : '移除金鑰' }}
        </button>
      </div>
      <p v-if="form.errors.key" class="set-error mt-1">{{ form.errors.key }}</p>
      <p v-else class="set-text mt-1">金鑰加密後存在這台伺服器，之後只顯示末四碼。更換位址時要一併重新輸入。</p>
    </div>

    <div class="set-form__pair">
      <div>
        <label for="ai-interval" class="set-label">請求最小間隔（秒）</label>
        <input id="ai-interval" v-model="form.minInterval" type="number" min="0.05" max="120" step="0.5" class="set-input" :placeholder="String(card.min_interval)">
        <p v-if="form.errors.min_interval" class="set-error mt-1">{{ form.errors.min_interval }}</p>
      </div>
      <div>
        <label for="ai-concurrency" class="set-label">同時請求數</label>
        <input id="ai-concurrency" v-model="form.maxConcurrency" type="number" min="1" max="16" step="1" class="set-input" :placeholder="String(card.max_concurrency)">
      </div>
    </div>

    <div class="flex items-center justify-between gap-4">
      <label for="ai-json" class="text-sm">
        <span class="font-medium">JSON 格式參數</span>
        <span class="block text-muted-foreground">服務不支援時關掉，改用提示要求輸出 JSON。</span>
      </label>
      <Switch id="ai-json" v-model="form.jsonMode" />
    </div>

    <div v-if="gemini">
      <label for="ai-thinking" class="set-label">思考等級</label>
      <Select
        id="ai-thinking"
        block
        :model-value="form.thinkingLevel || 'default'"
        :options="thinkingOptions"
        @update:model-value="form.thinkingLevel = ($event === 'default' ? '' : $event) as AiEditor['thinkingLevel']"
      />
    </div>

    <details v-else>
      <summary class="cursor-pointer text-sm font-medium">額外請求參數</summary>
      <textarea
        id="ai-extra"
        v-model="form.extraBody"
        rows="3"
        spellcheck="false"
        aria-label="額外請求參數（JSON）"
        placeholder="{&quot;reasoning&quot;: {&quot;effort&quot;: &quot;low&quot;}}"
        class="set-input set-mono mt-2"
      />
      <p v-if="extraError" class="set-error mt-1">{{ extraError }}</p>
      <p v-else-if="form.errors.caps" class="set-error mt-1">{{ form.errors.caps }}</p>
      <p class="set-text mt-1">
        JSON 物件，會併進每一次分析請求和連線測試，常用來關閉推理。留空表示不帶。
        <template v-if="hasPreset">這個模型需要的參數已經填好。</template>
      </p>
    </details>

    <div v-if="form.mode === 'new'">
      <label for="ai-slot" class="set-label">儲存後加到</label>
      <Select
        id="ai-slot"
        block
        :model-value="form.slot || 'none'"
        :options="slotOptions"
        @update:model-value="form.slot = ($event === 'none' ? '' : $event) as AiEditor['slot']"
      />
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <button type="submit" class="set-button set-button--primary" :disabled="!!problem || saving">
        <Loader2 v-if="saving" class="animate-spin" aria-hidden="true" />
        儲存
      </button>
      <button type="button" class="set-button" :disabled="!!problem || test === 'running'" @click="emit('test')">
        <Loader2 v-if="test === 'running'" class="animate-spin" aria-hidden="true" />
        <PlugZap v-else aria-hidden="true" />
        測試
      </button>
      <button type="button" class="set-button set-button--text" @click="emit('cancel')">取消</button>
    </div>
    <p class="set-text">{{ problem ?? '測試會先列出模型，再實際送一筆小請求；不會儲存任何東西。' }}</p>

    <div v-if="test && test !== 'running'" role="status" class="set-notice" :class="test.ok ? 'set-notice--ok' : 'set-notice--bad'">
      <p>{{ test.message }}</p>
      <a v-if="test.fix_url" :href="test.fix_url" target="_blank" rel="noopener noreferrer" class="inline-flex items-center gap-1 underline">
        前往處理 <ExternalLink class="size-4" aria-hidden="true" />
      </a>
      <p v-if="test.detail" class="set-mono mt-1 opacity-80">{{ test.detail }}</p>
    </div>
  </form>
</template>
