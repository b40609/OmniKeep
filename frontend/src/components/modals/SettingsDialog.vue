<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Settings, PlugZap, ShieldAlert, X, Loader2, CircleCheck, CircleAlert, BellRing } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import {
  checkConnection, getSettings, getSettingsAudit, importEnvSettings, regeneratePushKeys, saveSettings,
  type CheckService, type ConnectionCheck, type SettingField, type SettingValue, type SettingsAuditEntry,
  type SettingsSnapshot,
} from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import TelegramPairing from './TelegramPairing.vue'
import AiProvidersPanel from './AiProvidersPanel.vue'

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

// The AI tab is AiProvidersPanel (connections and task slots), tested per connection there.
const CHECKS_BY_GROUP: Record<string, { service: CheckService; label: string }[]> = {
  brain: [{ service: 'brain', label: '測試 Ollama 模型' }],
  telegram: [{ service: 'telegram', label: '測試 Bot' }],
  line: [{ service: 'line', label: '測試 LINE Bot' }],
  github: [{ service: 'github', label: '測試 Token' }],
}
const SOURCE_LABEL = { app: 'App 設定', env: '.env', default: '預設值' } as const
/** Settings OmniKeep creates itself: never a form field, but named in lists. */
const GENERATED_LABEL: Record<string, string> = { VAPID_PUBLIC_KEY: '推播公鑰', VAPID_PRIVATE_KEY: '推播私鑰' }
const ACTION_LABEL: Record<string, string> = {
  set: '修改', clear: '清除', reset: '改回 .env／預設值', import: '從 .env 匯入', pair: 'Telegram 配對',
  generate: '自動產生', regenerate: '重新產生', rotate: '輪替', sync: '由 AI 連線同步', delete: '刪除',
}

const audit = ref<SettingsAuditEntry[]>([])
const auditMore = ref(false)
const auditLoading = ref(false)
const auditError = ref('')
const auditLoaded = ref(false)
const regenerating = ref(false)

const tabs = computed(() => [
  ...(snapshot.value?.groups.map((g) => ({ id: g.id, label: g.label })) ?? []),
  { id: 'system', label: '系統' },
])
// The flat AI fields (OPENAI_*, GEMINI_*, …) are replaced by AiProvidersPanel; the API still accepts them.
const fields = computed<SettingField[]>(() =>
  ui.settingsTab === 'ai' ? [] : snapshot.value?.groups.find((g) => g.id === ui.settingsTab)?.fields ?? [])
const byKey = computed(() => {
  const map = new Map<string, SettingField>()
  snapshot.value?.groups.forEach((g) => g.fields.forEach((f) => map.set(f.key, f)))
  return map
})

function labelOf(key: string) {
  return byKey.value.get(key)?.label ?? GENERATED_LABEL[key] ?? key
}

/** Unreadable keys the owner can type again; an unreadable push key is regenerated instead. */
const retypeable = computed(() => snapshot.value?.secret_key.undecryptable.filter((k) => !(k in GENERATED_LABEL)) ?? [])

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
    if (auditLoaded.value) loadAudit()
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

async function loadAudit(more = false) {
  auditLoading.value = true
  auditError.value = ''
  try {
    const before = more ? audit.value[audit.value.length - 1]?.id : undefined
    const page = await getSettingsAudit(before)
    audit.value = more ? [...audit.value, ...page.entries] : page.entries
    auditMore.value = page.has_more
    auditLoaded.value = true
  } catch (e) {
    auditError.value = e instanceof Error ? e.message : String(e)
  } finally {
    auditLoading.value = false
  }
}

function auditTime(iso: string) {
  const date = new Date(iso)
  return Number.isNaN(date.getTime())
    ? iso
    : date.toLocaleString('zh-TW', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

async function regeneratePush() {
  const devices = snapshot.value?.push.subscriptions ?? 0
  const warning = devices
    ? `重新產生後，目前已開啟推播的 ${devices} 台裝置都會停止收到通知，要在每台裝置重新開啟。確定嗎？`
    : '要產生新的推播金鑰嗎？'
  if (!window.confirm(warning)) return
  regenerating.value = true
  try {
    const result = await regeneratePushKeys()
    snapshot.value = result
    resetDrafts()
    ui.settingsVersion++
    if (auditLoaded.value) loadAudit()
    toast.success('已產生新的推播金鑰', {
      description: result.removed_subscriptions ? `已移除 ${result.removed_subscriptions} 個舊裝置訂閱，請在各裝置重新開啟推播。` : undefined,
    })
  } catch (e) {
    toast.error('產生推播金鑰失敗', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    regenerating.value = false
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
      audit.value = []
      auditLoaded.value = false
      refresh()
      if (ui.settingsTab === 'system') loadAudit()
    }
  },
  // A settings link (#settings=ai) opens the dialog before this component mounts.
  { immediate: true },
)

watch(
  () => ui.settingsTab,
  (tab) => {
    if (tab === 'system' && ui.showSettingsModal && !auditLoaded.value && !auditLoading.value) loadAudit()
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
            v-if="retypeable.length"
            role="alert"
            class="flex gap-2 rounded-lg border border-danger/30 bg-danger-soft p-3 text-xs text-danger"
          >
            <ShieldAlert class="mt-0.5 size-4 shrink-0" />
            <p>
              有 {{ retypeable.length }} 個金鑰無法解密（{{ snapshot.secret_key.exists ? '主金鑰和當初加密時不同' : '找不到主金鑰' }}），目前改用 .env 的值。請重新輸入：{{ retypeable.map(labelOf).join('、') }}。
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
              <ul class="list-disc space-y-1 pl-5 text-2xs text-muted-foreground">
                <li>搬機：停止舊主機的服務，把資料庫和這個檔案一起複製到新主機的同一個資料夾（或用 OMNIKEEP_SECRET_KEY_FILE 指到它的位置）。</li>
                <li>
                  更換主金鑰：在伺服器專案資料夾執行 <code>python scripts/rotate_secret_key.py</code>。所有金鑰會改用新的主金鑰重新加密，不必停止服務；
                  舊主金鑰另存成同資料夾的 <code>.bak</code> 檔，還原更換前的資料庫備份時會用到。
                </li>
              </ul>
            </section>
            <section class="space-y-2">
              <h3 class="text-xs font-semibold">從 .env 匯入</h3>
              <template v-if="snapshot.env_importable.length">
                <p class="text-2xs text-muted-foreground">
                  這些設定目前來自 .env：{{ snapshot.env_importable.map(labelOf).join('、') }}。
                  匯入後改由 App 管理，之後可以把 .env 裡對應的行刪掉。
                </p>
                <Button variant="secondary" size="sm" :disabled="importing" @click="importEnv">
                  <Loader2 v-if="importing" class="size-3 animate-spin" />
                  匯入 {{ snapshot.env_importable.length }} 項設定
                </Button>
              </template>
              <p v-else class="text-2xs text-muted-foreground">沒有需要匯入的設定。</p>
            </section>
            <section class="space-y-2">
              <h3 class="text-xs font-semibold">變更紀錄</h3>
              <p class="text-2xs text-muted-foreground">哪個設定在什麼時候被修改、清除或匯入。只記欄位名稱和動作，不記錄任何值。</p>
              <p v-if="auditError" class="text-2xs text-danger">無法讀取變更紀錄：{{ auditError }}</p>
              <p v-else-if="auditLoaded && !audit.length" class="text-2xs text-muted-foreground">還沒有任何變更。</p>
              <div v-if="audit.length" class="overflow-hidden rounded-lg border border-border">
                <table class="w-full text-left text-xs">
                  <thead class="bg-muted text-2xs text-muted-foreground">
                    <tr>
                      <th scope="col" class="px-3 py-1.5 font-medium">時間</th>
                      <th scope="col" class="px-3 py-1.5 font-medium">設定</th>
                      <th scope="col" class="px-3 py-1.5 font-medium">動作</th>
                    </tr>
                  </thead>
                  <tbody class="divide-y divide-border">
                    <tr v-for="entry in audit" :key="entry.id">
                      <td class="whitespace-nowrap px-3 py-1.5 font-mono text-2xs text-muted-foreground">{{ auditTime(entry.created_at) }}</td>
                      <td class="px-3 py-1.5">
                        {{ entry.label }}
                        <span v-if="entry.group" class="text-2xs text-subtle-foreground">· {{ entry.group }}</span>
                      </td>
                      <td class="whitespace-nowrap px-3 py-1.5">{{ ACTION_LABEL[entry.action] ?? entry.action }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <Button v-if="auditMore" variant="ghost" size="sm" :disabled="auditLoading" @click="loadAudit(true)">
                <Loader2 v-if="auditLoading" class="size-3 animate-spin" />
                載入更早的紀錄
              </Button>
              <p v-else-if="auditLoading && !audit.length" class="text-2xs text-muted-foreground">讀取中…</p>
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

            <AiProvidersPanel v-if="ui.settingsTab === 'ai'" />

            <section v-if="ui.settingsTab === 'push'" class="space-y-2 border-t border-border pt-3">
              <h3 class="flex items-center gap-1.5 text-xs font-semibold"><BellRing class="size-3.5" /> 推播金鑰</h3>
              <p v-if="snapshot.push.undecryptable" class="rounded-lg border border-danger/30 bg-danger-soft p-2.5 text-2xs text-danger">
                推播金鑰無法解密：主金鑰和當初加密時不同，推播暫停中。把原本的主金鑰檔放回去就會恢復；找不回來的話，重新產生一組，各裝置再重新開啟推播。
              </p>
              <p v-else-if="snapshot.push.ready" class="text-2xs text-muted-foreground">
                已就緒（{{ snapshot.push.source === 'env' ? '來自 .env' : 'OmniKeep 自動產生，加密存放' }}）。目前 {{ snapshot.push.subscriptions }} 台裝置開啟推播，各裝置在「推播通知」開關。
              </p>
              <p v-else class="text-2xs text-muted-foreground">
                還沒有推播金鑰。伺服器啟動時會自動產生；也可以現在產生。
              </p>
              <p v-if="snapshot.push.source === 'env'" class="text-2xs text-subtle-foreground">
                想把 .env 裡的推播金鑰移進 App：到「系統」按「從 .env 匯入」，已開啟推播的裝置不受影響。
              </p>
              <Button
                v-if="!snapshot.push.ready"
                variant="secondary"
                size="sm"
                :disabled="regenerating"
                @click="regeneratePush"
              >
                <Loader2 v-if="regenerating" class="size-3 animate-spin" />
                {{ snapshot.push.undecryptable ? '重新產生推播金鑰' : '產生推播金鑰' }}
              </Button>
            </section>

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

      <!-- The AI tab saves each connection and the task lists itself. -->
      <div v-if="ui.settingsTab !== 'ai'" class="flex shrink-0 items-center justify-between gap-2 border-t border-border px-5 py-3">
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
