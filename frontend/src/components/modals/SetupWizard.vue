<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Sparkles, PlugZap, Loader2, CircleCheck, CircleAlert, ExternalLink, Check } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import { checkConnection, getServiceStatus, saveSettings, type ConnectionCheck } from '@/lib/api'
import {
  SETUP_PRESETS, checkServiceFor, formProblem, initialForm, presetById, sameValues, setupValues,
  type SetupForm, type SetupPreset,
} from '@/lib/setup'
import { useUiStore } from '@/stores/ui'

/**
 * First-run guide (after AnythingLLM's onboarding): while no AI provider is
 * usable, walk the owner through address, key and model, test, then save.
 */
const ui = useUiStore()
const LATER_KEY = 'omnikeep-setup-later'

const step = ref<'choose' | 'connect' | 'done'>('choose')
const presetId = ref('openai')
const form = reactive<SetupForm>(initialForm(presetById('openai')!))
const testing = ref(false)
const saving = ref(false)
const result = ref<ConnectionCheck | null>(null)
const testedValues = ref<Record<string, string> | null>(null)

const preset = computed<SetupPreset>(() => presetById(presetId.value) ?? SETUP_PRESETS[0])
const values = computed(() => setupValues(preset.value, form))
const problem = computed(() => formProblem(preset.value, form))
const canSave = computed(() => !!result.value?.ok && sameValues(testedValues.value, values.value) && !saving.value)
const STEPS = [
  { id: 'choose', label: '選服務商' },
  { id: 'connect', label: '連線與測試' },
  { id: 'done', label: '完成' },
] as const
const stepIndex = computed(() => STEPS.findIndex((s) => s.id === step.value))

function choose(id: string) {
  presetId.value = id
  Object.assign(form, initialForm(preset.value))
  result.value = null
  testedValues.value = null
}

// Any edit after a test means the result no longer describes what would be saved.
watch(values, (now) => {
  if (testedValues.value && !sameValues(testedValues.value, now)) result.value = null
})

async function test() {
  if (problem.value || testing.value) return
  testing.value = true
  result.value = null
  const tested = { ...values.value }
  try {
    result.value = await checkConnection(checkServiceFor(preset.value), tested)
  } catch (e) {
    result.value = { ok: false, status: null, message: e instanceof Error ? e.message : String(e), detail: '' }
  } finally {
    testedValues.value = tested
    testing.value = false
  }
}

async function save() {
  if (!canSave.value) return
  saving.value = true
  try {
    await saveSettings(values.value)
    ui.settingsVersion++
    form.apiKey = ''
    step.value = 'done'
  } catch (e) {
    toast.error('儲存失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    saving.value = false
  }
}

function later() {
  try {
    sessionStorage.setItem(LATER_KEY, '1')
  } catch {
    /* private mode */
  }
  ui.showSetupWizard = false
}

function openFullSettings() {
  ui.showSetupWizard = false
  ui.openSettings('ai')
}

function onOpenChange(open: boolean) {
  if (open) return
  if (step.value === 'done') ui.showSetupWizard = false
  else later()
}

watch(
  () => ui.showSetupWizard,
  (open) => {
    if (!open) return
    step.value = 'choose'
    choose(presetId.value)
  },
)

onMounted(async () => {
  try {
    if (sessionStorage.getItem(LATER_KEY)) return
  } catch {
    /* private mode: ask anyway */
  }
  try {
    const status = await getServiceStatus()
    // A key that cannot be decrypted is a different problem; the banner explains that one.
    if (status.needs_setup && !status.undecryptable.length && !ui.showSettingsModal) ui.showSetupWizard = true
  } catch {
    /* offline or signed out */
  }
})

const inputClass =
  'h-9 w-full rounded-lg border border-border bg-input px-3 text-xs text-foreground transition-all placeholder:text-subtle-foreground focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none disabled:opacity-50'
</script>

<template>
  <Dialog :open="ui.showSetupWizard" @update:open="onOpenChange">
    <DialogContent class="flex max-h-[90vh] max-w-xl flex-col gap-0 overflow-hidden p-0">
      <div class="flex shrink-0 items-center gap-2.5 border-b border-border p-5 pb-4">
        <div class="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Sparkles class="size-4.5" />
        </div>
        <DialogHeader>
          <DialogTitle>開始使用 OmniKeep</DialogTitle>
          <DialogDescription class="text-xs">
            OmniKeep 用 AI 幫收藏寫摘要、分類並建立語意搜尋。先接上一個 AI 服務商，之後隨時可以在「設定」更換。
          </DialogDescription>
        </DialogHeader>
      </div>

      <ol class="flex shrink-0 items-center gap-2 border-b border-border px-5 py-2.5 text-2xs" aria-label="設定步驟">
        <li
          v-for="(s, i) in STEPS"
          :key="s.id"
          class="flex items-center gap-1.5"
          :class="i === stepIndex ? 'font-semibold text-foreground' : 'text-muted-foreground'"
          :aria-current="i === stepIndex ? 'step' : undefined"
        >
          <span
            class="flex size-5 items-center justify-center rounded-full border text-2xs"
            :class="i < stepIndex ? 'border-primary bg-primary text-primary-foreground' : i === stepIndex ? 'border-primary text-primary-soft-foreground' : 'border-border'"
          >
            <Check v-if="i < stepIndex" class="size-3" />
            <template v-else>{{ i + 1 }}</template>
          </span>
          {{ s.label }}
          <span v-if="i < STEPS.length - 1" class="mx-1 h-px w-6 bg-border" aria-hidden="true" />
        </li>
      </ol>

      <div class="min-h-0 flex-1 space-y-4 overflow-y-auto p-5 text-sm">
        <!-- 1. Choose a provider -->
        <template v-if="step === 'choose'">
          <div class="grid gap-2 sm:grid-cols-2" role="radiogroup" aria-label="AI 服務商">
            <button
              v-for="p in SETUP_PRESETS"
              :key="p.id"
              type="button"
              role="radio"
              :aria-checked="presetId === p.id"
              class="cursor-pointer rounded-lg border p-3 text-left transition-colors"
              :class="presetId === p.id ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'"
              @click="choose(p.id)"
            >
              <span class="block text-xs font-semibold">{{ p.label }}</span>
              <span class="mt-0.5 block text-2xs text-muted-foreground">{{ p.description }}</span>
            </button>
          </div>
        </template>

        <!-- 2. Address, key, model, then test -->
        <template v-else-if="step === 'connect'">
          <p class="text-xs text-muted-foreground">
            <span class="font-semibold text-foreground">{{ preset.label }}</span>：{{ preset.description }}
          </p>

          <div v-if="preset.provider === 'openai_compatible'" class="space-y-1.5">
            <label for="setup-url" class="text-xs font-semibold">API 位址</label>
            <input
              id="setup-url"
              v-model="form.baseUrl"
              type="url"
              spellcheck="false"
              placeholder="https://…/v1"
              :readonly="!preset.editableUrl"
              :class="[inputClass, !preset.editableUrl && 'text-muted-foreground']"
            >
            <p v-if="preset.id === 'ollama'" class="text-2xs text-muted-foreground">
              Ollama 裝在別台電腦時，把 127.0.0.1 換成那台的位址。模型要先下載：<code>ollama pull {{ form.model || 'qwen3:8b' }}</code>
            </p>
          </div>

          <div v-if="preset.keyMode !== 'none'" class="space-y-1.5">
            <div class="flex items-center justify-between gap-2">
              <label for="setup-key" class="text-xs font-semibold">
                API 金鑰<span v-if="preset.keyMode === 'optional'" class="font-normal text-muted-foreground">（選填）</span>
              </label>
              <a
                v-if="preset.keyUrl"
                :href="preset.keyUrl"
                target="_blank"
                rel="noopener noreferrer"
                class="inline-flex items-center gap-1 text-2xs text-primary hover:underline"
              >
                取得金鑰 <ExternalLink class="size-3" />
              </a>
            </div>
            <input
              id="setup-key"
              v-model="form.apiKey"
              type="password"
              autocomplete="new-password"
              spellcheck="false"
              :placeholder="preset.provider === 'gemini' ? '多把金鑰用逗號分隔' : '貼上金鑰'"
              :class="inputClass"
            >
            <p class="text-2xs text-muted-foreground">金鑰會加密後存在這台伺服器，之後不會再顯示。</p>
          </div>

          <div class="space-y-1.5">
            <label for="setup-model" class="text-xs font-semibold">分析模型</label>
            <input id="setup-model" v-model="form.model" type="text" spellcheck="false" :class="inputClass">
          </div>

          <div class="space-y-2 border-t border-border pt-3">
            <div class="flex flex-wrap items-center gap-2">
              <Button variant="outline" size="sm" :disabled="!!problem || testing" @click="test">
                <Loader2 v-if="testing" class="size-3 animate-spin" />
                <PlugZap v-else class="size-3" />
                測試連線
              </Button>
              <span v-if="problem" class="text-2xs text-muted-foreground">{{ problem }}</span>
              <span v-else-if="!result" class="text-2xs text-muted-foreground">測試成功後才能儲存。</span>
            </div>
            <div
              v-if="result"
              role="status"
              class="flex gap-2 rounded-lg border p-2.5 text-xs"
              :class="result.ok ? 'border-success/30 text-success' : 'border-danger/30 text-danger'"
            >
              <CircleCheck v-if="result.ok" class="mt-0.5 size-3.5 shrink-0" />
              <CircleAlert v-else class="mt-0.5 size-3.5 shrink-0" />
              <div class="min-w-0">
                <p>{{ result.message }}</p>
                <p v-if="result.detail" class="mt-1 break-all font-mono text-2xs opacity-80">{{ result.detail }}</p>
              </div>
            </div>
          </div>
        </template>

        <!-- 3. Done -->
        <template v-else>
          <div class="flex gap-2 rounded-lg border border-success/30 p-3 text-xs text-success">
            <CircleCheck class="mt-0.5 size-4 shrink-0" />
            <p>已經接上 {{ preset.label }}，立即生效。新的收藏會自動經過 AI 分析。</p>
          </div>
          <ul class="list-disc space-y-1 pl-5 text-2xs text-muted-foreground">
            <li>語意搜尋的向量預設交給本機 Ollama 計算，連不上時改用上面的服務商；可以在「設定 › AI 服務商」測試。</li>
            <li>Telegram、LINE Bot、GitHub Token 與備份也都在「設定」裡填，不需要修改 .env。</li>
          </ul>
        </template>
      </div>

      <div class="flex shrink-0 items-center justify-between gap-2 border-t border-border px-5 py-3">
        <button
          v-if="step !== 'done'"
          type="button"
          class="cursor-pointer text-2xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          @click="later"
        >
          稍後再說
        </button>
        <button
          v-else
          type="button"
          class="cursor-pointer text-2xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          @click="openFullSettings"
        >
          開啟完整設定
        </button>
        <div class="flex gap-2">
          <template v-if="step === 'choose'">
            <Button size="sm" @click="step = 'connect'">下一步</Button>
          </template>
          <template v-else-if="step === 'connect'">
            <Button variant="ghost" size="sm" :disabled="saving" @click="step = 'choose'">上一步</Button>
            <Button size="sm" :disabled="!canSave" @click="save">
              <Loader2 v-if="saving" class="size-3 animate-spin" />
              儲存並完成
            </Button>
          </template>
          <Button v-else size="sm" @click="ui.showSetupWizard = false">開始使用</Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
