<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Settings, PlugZap, ShieldAlert, X, Loader2, CircleCheck, CircleAlert } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import {
  checkConnection, getSettings, importEnvSettings, saveSettings,
  type CheckService, type ConnectionCheck, type SettingField, type SettingValue, type SettingsSnapshot,
} from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import TelegramPairing from './TelegramPairing.vue'

/** Everything that used to need .env edits: saved in the app, applied at once, keys never shown again. */
const ui = useUiStore()

const snapshot = ref<SettingsSnapshot | null>(null)
const loadError = ref('')
const saving = ref(false)
const importing = ref(false)
const draft = reactive<Record<string, SettingValue>>({})
const secretDraft = reactive<Record<string, string>>({})
const idInput = reactive<Record<string, string>>({})
const clears = ref(new Set<string>())
const resets = ref(new Set<string>())
const errors = ref<Record<string, string>>({})
const checks = reactive<Partial<Record<CheckService, ConnectionCheck | 'running'>>>({})
const telegram = ref<InstanceType<typeof TelegramPairing> | null>(null)

const CHECKS_BY_GROUP: Record<string, { service: CheckService; label: string }[]> = {
  ai: [
    { service: 'llm', label: '測試 OpenAI 相容服務' },
    { service: 'embeddings', label: '測試向量模型' },
    { service: 'gemini', label: '測試 Gemini' },
  ],
  telegram: [{ service: 'telegram', label: '測試 Bot' }],
  line: [{ service: 'line', label: '測試 LINE Bot' }],
  github: [{ service: 'github', label: '測試 Token' }],
}
const SOURCE_LABEL = { app: 'App 設定', env: '.env', default: '預設值' } as const

const tabs = computed(() => [
  ...(snapshot.value?.groups.map((g) => ({ id: g.id, label: g.label })) ?? []),
  { id: 'system', label: '系統' },
])
const fields = computed<SettingField[]>(() => snapshot.value?.groups.find((g) => g.id === ui.settingsTab)?.fields ?? [])
const byKey = computed(() => {
  const map = new Map<string, SettingField>()
  snapshot.value?.groups.forEach((g) => g.fields.forEach((f) => map.set(f.key, f)))
  return map
})

function same(a: SettingValue | undefined, b: SettingValue | undefined) {
  return JSON.stringify(a) === JSON.stringify(b)
}

function resetDrafts() {
  for (const key of Object.keys(draft)) delete draft[key]
  for (const key of Object.keys(secretDraft)) delete secretDraft[key]
  for (const field of byKey.value.values()) {
    if (field.kind === 'secret') secretDraft[field.key] = ''
    else draft[field.key] = Array.isArray(field.value) ? [...field.value] : (field.value as SettingValue)
  }
  clears.value = new Set()
  resets.value = new Set()
  errors.value = {}
}

async function refresh() {
  loadError.value = ''
  try {
    snapshot.value = await getSettings()
    resetDrafts()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e)
  }
}

const pending = computed(() => {
  const values: Record<string, SettingValue> = {}
  for (const field of byKey.value.values()) {
    if (resets.value.has(field.key)) continue
    if (field.kind === 'secret') {
      const typed = (secretDraft[field.key] ?? '').trim()
      if (clears.value.has(field.key)) values[field.key] = ''
      else if (typed) values[field.key] = typed
    } else if (!same(draft[field.key], field.value)) {
      values[field.key] = draft[field.key]
    }
  }
  return { values, reset: [...resets.value] }
})
const changeCount = computed(() => Object.keys(pending.value.values).length + pending.value.reset.length)

const baseUrlNeedsKey = computed(() => {
  const url = byKey.value.get('OPENAI_BASE_URL')
  const key = byKey.value.get('OPENAI_API_KEY')
  if (!url || !key || !('OPENAI_BASE_URL' in pending.value.values)) return false
  return !!key.configured && !('OPENAI_API_KEY' in pending.value.values)
})
const embeddingChanged = computed(() => 'EMBEDDING_MODEL' in pending.value.values)

function toggle(set: typeof clears, key: string) {
  const next = new Set(set.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  set.value = next
}

function toggleReset(field: SettingField) {
  toggle(resets, field.key)
  if (field.kind === 'secret') secretDraft[field.key] = ''
  else draft[field.key] = Array.isArray(field.value) ? [...field.value] : (field.value as SettingValue)
  clears.value.delete(field.key)
}

function toggleClear(key: string) {
  toggle(clears, key)
  secretDraft[key] = ''
}

function addIds(key: string) {
  const current = (draft[key] as string[]) ?? []
  const added = (idInput[key] ?? '').split(/[,\s]+/).map((s) => s.trim()).filter(Boolean)
  draft[key] = [...new Set([...current, ...added])]
  idInput[key] = ''
}

function removeId(key: string, id: string) {
  draft[key] = ((draft[key] as string[]) ?? []).filter((x) => x !== id)
}

function secretPlaceholder(field: SettingField) {
  if (clears.value.has(field.key)) return '儲存後清除這個金鑰'
  if (field.undecryptable) return '無法解密，請重新輸入'
  if (field.configured) return `已設定 ${field.hint || ''}（留空表示不變）`.replace('  ', ' ')
  return '尚未設定'
}

function display(value: SettingValue | undefined) {
  if (Array.isArray(value)) return value.length ? value.join('、') : '（空）'
  if (typeof value === 'boolean') return value ? '開' : '關'
  return value === '' || value === undefined ? '（空）' : String(value)
}

async function save() {
  if (!changeCount.value || saving.value) return
  saving.value = true
  errors.value = {}
  try {
    const { values, reset } = pending.value
    snapshot.value = await saveSettings(values, reset)
    resetDrafts()
    ui.settingsVersion++
    telegram.value?.refresh()
    toast.success('設定已儲存，立即生效')
  } catch (e) {
    errors.value = (e as { fieldErrors?: Record<string, string> }).fieldErrors ?? {}
    const tab = snapshot.value?.groups.find((g) => g.fields.some((f) => f.key in errors.value))?.id
    if (tab) ui.settingsTab = tab
    toast.error('儲存失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    saving.value = false
  }
}

async function runCheck(service: CheckService) {
  checks[service] = 'running'
  const values = Object.fromEntries(Object.entries(pending.value.values).filter(([, v]) => v !== ''))
  try {
    checks[service] = await checkConnection(service, values)
  } catch (e) {
    checks[service] = { ok: false, status: null, message: e instanceof Error ? e.message : String(e), detail: '' }
  }
}

async function importEnv() {
  importing.value = true
  try {
    const result = await importEnvSettings()
    snapshot.value = result
    resetDrafts()
    ui.settingsVersion++
    toast.success(`已把 ${result.imported?.length ?? 0} 項設定從 .env 匯入 App`, {
      description: '之後可以把 .env 裡這些行刪掉，App 內的值會繼續生效。',
    })
  } catch (e) {
    toast.error('匯入失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    importing.value = false
  }
}

/** A pairing finished while this dialog is open: show the new owner unless the user is mid-edit. */
function onTelegramRefreshed(boundIds: number[]) {
  const shown = byKey.value.get('TELEGRAM_ALLOWED_USER_IDS')?.value
  if (!changeCount.value && !same(boundIds.map(String), shown)) refresh()
}

function onOpenChange(open: boolean) {
  if (!open && changeCount.value && !window.confirm('有尚未儲存的變更，確定要關閉嗎？')) return
  ui.showSettingsModal = open
}

watch(
  () => ui.showSettingsModal,
  (open) => {
    if (open) {
      for (const key of Object.keys(checks)) delete checks[key as CheckService]
      refresh()
    }
  },
)

const inputClass =
  'h-9 w-full rounded-lg border border-border bg-input px-3 text-xs text-foreground transition-all placeholder:text-subtle-foreground focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none disabled:opacity-50'
</script>

<template>
  <Dialog :open="ui.showSettingsModal" @update:open="onOpenChange">
    <DialogContent class="flex max-h-[90vh] max-w-2xl flex-col gap-0 overflow-hidden p-0">
      <div class="flex shrink-0 items-center gap-2.5 border-b border-border p-5 pb-4">
        <div class="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
          <Settings class="size-4.5" />
        </div>
        <DialogHeader>
          <DialogTitle>設定</DialogTitle>
          <DialogDescription class="text-xs">
            AI 服務商、Bot 與備份都在這裡設定。儲存後立即生效，不必修改 .env 或重新啟動。
          </DialogDescription>
        </DialogHeader>
      </div>

      <div class="flex shrink-0 items-center gap-1 overflow-x-auto border-b border-border px-5 text-xs" role="tablist">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          role="tab"
          :aria-selected="ui.settingsTab === tab.id"
          class="relative flex h-10 shrink-0 items-center px-3 font-medium transition-colors"
          :class="ui.settingsTab === tab.id ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="ui.settingsTab = tab.id"
        >
          {{ tab.label }}
          <span v-if="ui.settingsTab === tab.id" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
      </div>

      <div class="min-h-0 flex-1 space-y-4 overflow-y-auto p-5 text-sm">
        <p v-if="loadError" class="text-danger">無法讀取設定：{{ loadError }}</p>
        <p v-else-if="!snapshot" class="text-muted-foreground">讀取中…</p>

        <template v-else>
          <div
            v-if="snapshot.secret_key.undecryptable.length"
            role="alert"
            class="flex gap-2 rounded-lg border border-danger/30 bg-danger-soft p-3 text-xs text-danger"
          >
            <ShieldAlert class="mt-0.5 size-4 shrink-0" />
            <p>
              有 {{ snapshot.secret_key.undecryptable.length }} 個金鑰無法解密（{{ snapshot.secret_key.changed ? '主金鑰和當初加密時不同' : '找不到主金鑰' }}），目前改用 .env 的值。請重新輸入：{{ snapshot.secret_key.undecryptable.map((k) => byKey.get(k)?.label ?? k).join('、') }}。
            </p>
          </div>

          <!-- System: read-only bootstrap values, master key, import from .env -->
          <template v-if="ui.settingsTab === 'system'">
            <section class="space-y-2">
              <h3 class="text-xs font-semibold">啟動設定（唯讀）</h3>
              <p class="text-2xs text-muted-foreground">服務啟動、開資料庫之前就要用到，或負責保護這個設定頁的登入，所以仍放在 .env。</p>
              <dl class="divide-y divide-border rounded-lg border border-border text-xs">
                <div v-for="row in snapshot.bootstrap" :key="row.key" class="flex items-center justify-between gap-3 px-3 py-2">
                  <dt class="font-mono text-2xs text-muted-foreground">{{ row.key }}</dt>
                  <dd class="truncate text-right">{{ display(row.value) }}</dd>
                </div>
              </dl>
            </section>
            <section class="space-y-2">
              <h3 class="text-xs font-semibold">金鑰加密</h3>
              <p class="text-2xs text-muted-foreground">
                App 內輸入的金鑰會先加密才存進資料庫，備份檔裡只有加密後的內容。解密用的主金鑰
                {{ snapshot.secret_key.source === 'env' ? '來自環境變數 OMNIKEEP_SECRET_KEY' : '存在下面這個檔案，不會進入備份' }}。
                搬到新主機時，把這個檔案一起帶過去；遺失的話，只要重新輸入金鑰即可。
              </p>
              <p v-if="snapshot.secret_key.path" class="break-all rounded-lg border border-border px-3 py-2 font-mono text-2xs">
                {{ snapshot.secret_key.path }}{{ snapshot.secret_key.exists ? '' : '（第一次儲存金鑰時建立）' }}
              </p>
            </section>
            <section class="space-y-2">
              <h3 class="text-xs font-semibold">從 .env 匯入</h3>
              <template v-if="snapshot.env_importable.length">
                <p class="text-2xs text-muted-foreground">
                  這些設定目前來自 .env：{{ snapshot.env_importable.map((k) => byKey.get(k)?.label ?? k).join('、') }}。
                  匯入後改由 App 管理，之後可以把 .env 裡對應的行刪掉。
                </p>
                <Button variant="secondary" size="sm" :disabled="importing" @click="importEnv">
                  <Loader2 v-if="importing" class="size-3 animate-spin" />
                  匯入 {{ snapshot.env_importable.length }} 項設定
                </Button>
              </template>
              <p v-else class="text-2xs text-muted-foreground">沒有需要匯入的設定。</p>
            </section>
          </template>

          <template v-else>
            <div v-for="field in fields" :key="field.key" class="space-y-1.5">
              <div class="flex items-center justify-between gap-2">
                <label :for="`setting-${field.key}`" class="text-xs font-semibold">{{ field.label }}</label>
                <div class="flex shrink-0 items-center gap-1.5 text-2xs">
                  <span
                    class="rounded-full border px-1.5 py-px"
                    :class="resets.has(field.key) ? 'border-warning/40 text-warning' : field.source === 'app' ? 'border-primary/30 text-primary-soft-foreground' : 'border-border text-muted-foreground'"
                  >
                    {{ resets.has(field.key) ? (field.env_available ? '將改回 .env' : '將改回預設值') : SOURCE_LABEL[field.source] }}
                  </span>
                  <button
                    v-if="field.source === 'app' || resets.has(field.key)"
                    type="button"
                    class="cursor-pointer text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
                    @click="toggleReset(field)"
                  >
                    {{ resets.has(field.key) ? '取消' : field.env_available ? '改回 .env' : '改回預設值' }}
                  </button>
                </div>
              </div>

              <div v-if="field.kind === 'secret'" class="flex gap-2">
                <input
                  :id="`setting-${field.key}`"
                  v-model="secretDraft[field.key]"
                  type="password"
                  autocomplete="new-password"
                  spellcheck="false"
                  :placeholder="secretPlaceholder(field)"
                  :disabled="clears.has(field.key) || resets.has(field.key)"
                  :class="inputClass"
                >
                <Button
                  v-if="field.configured || clears.has(field.key)"
                  variant="ghost"
                  size="sm"
                  class="h-9 shrink-0"
                  :disabled="resets.has(field.key)"
                  @click="toggleClear(field.key)"
                >
                  {{ clears.has(field.key) ? '取消清除' : '清除' }}
                </Button>
              </div>

              <select
                v-else-if="field.kind === 'choice'"
                :id="`setting-${field.key}`"
                v-model="draft[field.key]"
                :disabled="resets.has(field.key)"
                :class="inputClass"
              >
                <option v-for="c in field.choices" :key="c.value" :value="c.value" class="bg-popover text-foreground">{{ c.label }}</option>
              </select>

              <input
                v-else-if="field.kind === 'int' || field.kind === 'float'"
                :id="`setting-${field.key}`"
                v-model.number="draft[field.key]"
                type="number"
                :min="field.min"
                :max="field.max"
                :step="field.kind === 'float' ? 0.05 : 1"
                :disabled="resets.has(field.key)"
                :class="inputClass"
              >

              <label v-else-if="field.kind === 'bool'" class="flex items-center gap-2 text-xs">
                <input :id="`setting-${field.key}`" v-model="draft[field.key]" type="checkbox" class="size-4 accent-primary" :disabled="resets.has(field.key)">
                {{ draft[field.key] ? '開' : '關' }}
              </label>

              <div v-else-if="field.kind === 'ids'" class="space-y-2">
                <div class="flex flex-wrap gap-1.5">
                  <span
                    v-for="id in (draft[field.key] as string[])"
                    :key="id"
                    class="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2 py-0.5 font-mono text-2xs"
                  >
                    {{ id }}
                    <button type="button" class="cursor-pointer text-muted-foreground hover:text-danger" :aria-label="`移除 ${id}`" :disabled="resets.has(field.key)" @click="removeId(field.key, id)">
                      <X class="size-3" />
                    </button>
                  </span>
                  <span v-if="!(draft[field.key] as string[])?.length" class="text-2xs text-muted-foreground">（沒有）</span>
                </div>
                <div class="flex gap-2">
                  <input
                    :id="`setting-${field.key}`"
                    v-model="idInput[field.key]"
                    type="text"
                    placeholder="輸入 ID 後按「加入」"
                    :disabled="resets.has(field.key)"
                    :class="inputClass"
                    @keyup.enter="addIds(field.key)"
                  >
                  <Button variant="secondary" size="sm" class="h-9 shrink-0" :disabled="!idInput[field.key]?.trim()" @click="addIds(field.key)">加入</Button>
                </div>
              </div>

              <input
                v-else
                :id="`setting-${field.key}`"
                v-model="draft[field.key]"
                :type="field.kind === 'url' ? 'url' : 'text'"
                spellcheck="false"
                :disabled="resets.has(field.key)"
                :class="inputClass"
              >

              <p v-if="errors[field.key]" class="text-2xs text-danger">{{ errors[field.key] }}</p>
              <p v-if="field.help" class="text-2xs text-muted-foreground">{{ field.help }}</p>
              <p v-if="field.source === 'app' && field.env_value !== undefined" class="text-2xs text-subtle-foreground">
                .env 的值：{{ display(field.env_value) }}
              </p>
            </div>

            <template v-if="ui.settingsTab === 'ai'">
              <p v-if="baseUrlNeedsKey" class="rounded-lg border border-warning/40 bg-warning/10 p-2.5 text-2xs text-warning">
                更換 API 位址時，請一併輸入新的 API 金鑰，舊金鑰不會被送到新位址。
              </p>
              <p v-if="embeddingChanged" class="rounded-lg border border-warning/40 bg-warning/10 p-2.5 text-2xs text-warning">
                更換向量模型後，既有收藏的向量要重建才查得到（伺服器執行 <code>scripts/rebuild_embeddings.py</code>）。
              </p>
            </template>

            <TelegramPairing v-if="ui.settingsTab === 'telegram'" ref="telegram" in-settings @refreshed="onTelegramRefreshed" />

            <section v-if="CHECKS_BY_GROUP[ui.settingsTab]" class="space-y-2 border-t border-border pt-3">
              <p class="text-2xs text-muted-foreground">測試會用你剛輸入（尚未儲存）的值；空白的欄位用目前生效的值。測試不會儲存任何東西。</p>
              <div class="flex flex-wrap gap-2">
                <Button
                  v-for="c in CHECKS_BY_GROUP[ui.settingsTab]"
                  :key="c.service"
                  variant="outline"
                  size="sm"
                  :disabled="checks[c.service] === 'running'"
                  @click="runCheck(c.service)"
                >
                  <Loader2 v-if="checks[c.service] === 'running'" class="size-3 animate-spin" />
                  <PlugZap v-else class="size-3" />
                  {{ c.label }}
                </Button>
              </div>
              <template v-for="c in CHECKS_BY_GROUP[ui.settingsTab]" :key="`r-${c.service}`">
                <div
                  v-if="checks[c.service] && checks[c.service] !== 'running'"
                  class="flex gap-2 rounded-lg border p-2.5 text-xs"
                  :class="(checks[c.service] as ConnectionCheck).ok ? 'border-success/30 text-success' : 'border-danger/30 text-danger'"
                >
                  <CircleCheck v-if="(checks[c.service] as ConnectionCheck).ok" class="mt-0.5 size-3.5 shrink-0" />
                  <CircleAlert v-else class="mt-0.5 size-3.5 shrink-0" />
                  <div class="min-w-0">
                    <p>
                      <span class="font-semibold">{{ c.label.replace('測試', '') }}：</span>{{ (checks[c.service] as ConnectionCheck).message }}
                    </p>
                    <p v-if="(checks[c.service] as ConnectionCheck).detail" class="mt-1 break-all font-mono text-2xs opacity-80">
                      {{ (checks[c.service] as ConnectionCheck).detail }}
                    </p>
                  </div>
                </div>
              </template>
            </section>
          </template>
        </template>
      </div>

      <div class="flex shrink-0 items-center justify-between gap-2 border-t border-border px-5 py-3">
        <span class="text-2xs text-muted-foreground">{{ changeCount ? `${changeCount} 項變更尚未儲存` : '沒有未儲存的變更' }}</span>
        <div class="flex gap-2">
          <Button variant="ghost" size="sm" :disabled="!changeCount || saving" @click="resetDrafts">還原</Button>
          <Button size="sm" :disabled="!changeCount || saving" @click="save">
            <Loader2 v-if="saving" class="size-3 animate-spin" />
            儲存
          </Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
