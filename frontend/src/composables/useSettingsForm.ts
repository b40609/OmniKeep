import { computed, inject, provide, reactive, ref, type InjectionKey } from 'vue'
import { toast } from 'vue-sonner'
import {
  getSettings, saveSettings,
  type SettingField, type SettingValue, type SettingsSnapshot,
} from '@/lib/api'
import { LOCAL_LOGIN_KEY, turnsLocalLoginOff } from '@/lib/localLogin'
import { sectionOfGroup } from '@/lib/settingsSections'
import { settingLabel } from '@/lib/settingsText'
import { useExperimentsStore } from '@/stores/experiments'
import { useUiStore } from '@/stores/ui'

/**
 * State of the settings page, shared by its sections.
 *
 * Two ways of saving (DESIGN.md, 設定列): switches and selects save the moment they
 * change (`setNow`); text and credentials are drafts that a block saves together
 * (`saveKeys`). Credentials are write-only: the server never sends them back.
 */
export function createSettingsForm() {
  const ui = useUiStore()
  const experiments = useExperimentsStore()

  const snapshot = ref<SettingsSnapshot | null>(null)
  const loadError = ref('')
  const draft = reactive<Record<string, SettingValue>>({})
  const secretDraft = reactive<Record<string, string>>({})
  const clears = ref(new Set<string>())
  const resets = ref(new Set<string>())
  const errors = ref<Record<string, string>>({})
  /** Keys being saved right now. */
  const saving = ref(new Set<string>())
  /** Keys saved a moment ago: their row says 已儲存. */
  const saved = ref(new Set<string>())
  /** A change that switches 這台電腦免登入 off waits here until the owner confirms. */
  const localLoginPending = ref<{ values: Record<string, SettingValue>; reset: string[] } | null>(null)

  /** Unsaved work outside these drafts (the AI connection form and task lists). */
  const extraDirty = ref(false)

  const byKey = computed(() => {
    const map = new Map<string, SettingField>()
    snapshot.value?.groups.forEach((g) => g.fields.forEach((f) => map.set(f.key, f)))
    return map
  })

  function same(a: SettingValue | undefined, b: SettingValue | undefined) {
    return JSON.stringify(a) === JSON.stringify(b)
  }

  function copyOf(field: SettingField): SettingValue {
    return Array.isArray(field.value) ? [...field.value] : (field.value as SettingValue)
  }

  /** Forget the drafts of `keys` (every key when omitted) and show what the server has. */
  function resetDrafts(keys?: string[]) {
    const all = !keys
    for (const field of byKey.value.values()) {
      if (!all && !keys!.includes(field.key)) continue
      if (field.kind === 'secret') secretDraft[field.key] = ''
      else draft[field.key] = copyOf(field)
    }
    const drop = (set: Set<string>) => new Set(all ? [] : [...set].filter((k) => !keys!.includes(k)))
    clears.value = drop(clears.value)
    resets.value = drop(resets.value)
    errors.value = all ? {} : Object.fromEntries(Object.entries(errors.value).filter(([k]) => !keys!.includes(k)))
  }

  /** Take a new description from the server, keeping the drafts of other blocks. */
  function apply(next: SettingsSnapshot, touched?: string[]) {
    const known = new Set(byKey.value.keys())
    snapshot.value = next
    const fresh = [...byKey.value.keys()].filter((k) => !known.has(k))
    resetDrafts(touched ? [...touched, ...fresh] : undefined)
    experiments.apply(next.groups)
  }

  /** Re-read from the server, keeping the drafts of every setting but `keys`. */
  async function refreshKeys(keys: string[]) {
    try {
      apply(await getSettings(), keys)
    } catch {
      /* the next full refresh says what is wrong */
    }
  }

  async function refresh() {
    loadError.value = ''
    try {
      apply(await getSettings())
    } catch (e) {
      loadError.value = e instanceof Error ? e.message : String(e)
    }
  }

  /** What saving `keys` would send. */
  function pendingFor(keys: string[]) {
    const values: Record<string, SettingValue> = {}
    const reset: string[] = []
    for (const key of keys) {
      const field = byKey.value.get(key)
      if (!field) continue
      if (resets.value.has(key)) {
        reset.push(key)
      } else if (field.kind === 'secret') {
        const typed = (secretDraft[key] ?? '').trim()
        if (clears.value.has(key)) values[key] = ''
        else if (typed) values[key] = typed
      } else if (!same(draft[key], field.value)) {
        values[key] = draft[key]
      }
    }
    return { values, reset }
  }

  function changeCount(keys: string[]) {
    const { values, reset } = pendingFor(keys)
    return Object.keys(values).length + reset.length
  }

  /** Any draft anywhere that has not been saved. */
  const dirty = computed(() => changeCount([...byKey.value.keys()]) > 0)

  function mark(set: typeof saving, keys: string[], on: boolean) {
    const next = new Set(set.value)
    for (const key of keys) (on ? next.add(key) : next.delete(key))
    set.value = next
  }

  async function commit(values: Record<string, SettingValue>, reset: string[], quiet = false): Promise<boolean> {
    const keys = [...Object.keys(values), ...reset]
    if (!keys.length) return true
    mark(saving, keys, true)
    errors.value = Object.fromEntries(Object.entries(errors.value).filter(([k]) => !keys.includes(k)))
    try {
      apply(await saveSettings(values, reset), keys)
      ui.settingsVersion++
      mark(saved, keys, true)
      setTimeout(() => mark(saved, keys, false), 2500)
      if (!quiet) toast.success('已儲存')
      return true
    } catch (e) {
      const fieldErrors = (e as { fieldErrors?: Record<string, string> }).fieldErrors ?? {}
      errors.value = { ...errors.value, ...fieldErrors }
      // An error on a setting of another section: go there, so it is not missed.
      const group = snapshot.value?.groups.find((g) => g.fields.some((f) => f.key in fieldErrors))
      if (group && !keys.some((k) => k in fieldErrors)) ui.settingsTab = sectionOfGroup(group.id)
      // A switch that could not be saved goes back to what the server has.
      for (const key of keys) {
        const field = byKey.value.get(key)
        if (field && field.kind !== 'secret' && quiet) draft[key] = copyOf(field)
      }
      toast.error('儲存失敗', { description: e instanceof Error ? e.message : String(e) })
      return false
    } finally {
      mark(saving, keys, false)
    }
  }

  /** Save, unless it would lock this computer out: then ask first (see confirmLocalLogin). */
  async function guarded(values: Record<string, SettingValue>, reset: string[], quiet: boolean) {
    if (turnsLocalLoginOff(byKey.value.get(LOCAL_LOGIN_KEY), values, reset)) {
      localLoginPending.value = { values, reset }
      return false
    }
    return commit(values, reset, quiet)
  }

  /** A block's 儲存 button. */
  function saveKeys(keys: string[]) {
    const { values, reset } = pendingFor(keys)
    return guarded(values, reset, false)
  }

  /** A switch or a select: saved at once, confirmed in its own row. */
  function setNow(key: string, value: SettingValue) {
    if (saving.value.has(key)) return Promise.resolve(false)
    draft[key] = value
    return guarded({ [key]: value }, [], true)
  }

  /** 重設 on a row that saves at once. */
  function resetNow(key: string) {
    return guarded({}, [key], true)
  }

  async function confirmLocalLogin() {
    const change = localLoginPending.value
    if (!change) return
    if (await commit(change.values, change.reset, true)) localLoginPending.value = null
  }

  function cancelLocalLogin() {
    const change = localLoginPending.value
    localLoginPending.value = null
    if (change) resetDrafts([...Object.keys(change.values), ...change.reset])
  }

  function toggleIn(set: typeof clears, key: string) {
    const next = new Set(set.value)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    set.value = next
  }

  /** 重設 on a row of a block with a 儲存 button: takes effect when the block is saved. */
  function toggleReset(field: SettingField) {
    toggleIn(resets, field.key)
    if (field.kind === 'secret') secretDraft[field.key] = ''
    else draft[field.key] = copyOf(field)
    const next = new Set(clears.value)
    next.delete(field.key)
    clears.value = next
  }

  function toggleClear(key: string) {
    toggleIn(clears, key)
    secretDraft[key] = ''
  }

  /** Credentials that cannot be read with the current master key and have to be typed again. */
  const unreadable = computed(() =>
    (snapshot.value?.secret_key.undecryptable ?? []).filter((k) => !k.startsWith('VAPID_')).map((k) => settingLabel(k, byKey.value.get(k)?.label)))

  return {
    snapshot, loadError, draft, secretDraft, clears, resets, errors, saving, saved, localLoginPending,
    byKey, dirty, extraDirty, unreadable,
    refresh, refreshKeys, apply, resetDrafts, pendingFor, changeCount, saveKeys, setNow, resetNow,
    confirmLocalLogin, cancelLocalLogin, toggleReset, toggleClear,
  }
}

export type SettingsForm = ReturnType<typeof createSettingsForm>

const KEY: InjectionKey<SettingsForm> = Symbol('settings-form')

export function provideSettingsForm(): SettingsForm {
  const form = createSettingsForm()
  provide(KEY, form)
  return form
}

export function useSettingsForm(): SettingsForm {
  const form = inject(KEY)
  if (!form) throw new Error('useSettingsForm() needs a SettingsPage above it')
  return form
}
