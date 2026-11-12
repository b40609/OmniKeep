<script setup lang="ts">
import { computed, ref } from 'vue'
import { X } from 'lucide-vue-next'
import Switch from '@/components/ui/switch/Switch.vue'
import Select from '@/components/ui/select/Select.vue'
import SettingRow from './SettingRow.vue'
import { useSettingsForm } from '@/composables/useSettingsForm'
import { SETTING_TEXT } from '@/lib/settingsText'
import type { SettingValue } from '@/lib/api'

/**
 * A setting the server describes, drawn as a row. `auto` rows (switches, selects)
 * save as they change; the others are drafts their block saves with one button.
 * Draws nothing when the server does not have the setting.
 */
const props = defineProps<{
  fieldKey: string
  auto?: boolean
  /** Put the control under the name (long option labels). Typed text always is. */
  stacked?: boolean
  placeholder?: string
  /** For 帳號編號 lists: hide the box for typing one in by hand. */
  noManualIds?: boolean
}>()

const form = useSettingsForm()
const field = computed(() => form.byKey.value.get(props.fieldKey))
const text = computed(() => SETTING_TEXT[props.fieldKey])
const id = computed(() => `setting-${props.fieldKey}`)
const resetting = computed(() => form.resets.value.has(props.fieldKey))
const clearing = computed(() => form.clears.value.has(props.fieldKey))
const busy = computed(() => form.saving.value.has(props.fieldKey))
const long = computed(() => props.stacked || ['text', 'url', 'secret', 'ids'].includes(field.value?.kind ?? ''))

// 重設 only on a setting that was changed in the app. A credential or a list of accounts
// is emptied with its own controls instead, unless the server's own configuration
// holds another value to go back to.
const canReset = computed(() => {
  const f = field.value
  if (!f) return false
  if (resetting.value) return true
  if (f.source !== 'app') return false
  return (f.kind !== 'secret' && f.kind !== 'ids') || f.env_available
})

function change(value: SettingValue) {
  if (props.auto) void form.setNow(props.fieldKey, value)
  else form.draft[props.fieldKey] = value
}

function reset() {
  if (!field.value) return
  if (props.auto) void form.resetNow(props.fieldKey)
  else form.toggleReset(field.value)
}

const secretPlaceholder = computed(() => {
  const f = field.value
  if (!f) return ''
  if (clearing.value) return '儲存後移除'
  if (f.undecryptable) return '無法解密，請重新輸入'
  if (f.configured) return `已設定${f.hint ? ` ${f.hint}` : ''}，留空表示不變`
  return props.placeholder ?? '尚未設定'
})

/* A list of ids: chips that can be removed, and a box to add one by hand. */
const idInput = ref('')
const ids = computed(() => (form.draft[props.fieldKey] as string[] | undefined) ?? [])
function addIds() {
  const added = idInput.value.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean)
  form.draft[props.fieldKey] = [...new Set([...ids.value, ...added])]
  idInput.value = ''
}
function removeId(value: string) {
  form.draft[props.fieldKey] = ids.value.filter((x) => x !== value)
}
</script>

<template>
  <SettingRow
    v-if="field"
    :name="text?.label ?? field.label"
    :help="text?.help ?? field.help"
    :stacked="long"
    :for="field.kind === 'ids' && noManualIds ? undefined : id"
  >
    <template #mark>
      <span v-if="busy" class="set-note" role="status">儲存中…</span>
      <span v-else-if="form.saved.value.has(fieldKey)" class="set-note set-note--ok" role="status">已儲存</span>
      <span v-if="resetting" class="set-note">儲存後回到預設值</span>
      <slot name="mark" />
    </template>
    <template #below>
      <p v-if="form.errors.value[fieldKey]" class="set-error" role="alert">{{ form.errors.value[fieldKey] }}</p>
      <slot name="below" />
    </template>

    <template v-if="field.kind === 'bool'">
      <button v-if="canReset" type="button" class="set-button set-button--text" :disabled="busy" @click="reset">{{ resetting ? '取消重設' : '重設' }}</button>
      <Switch :id="id" :model-value="form.draft[fieldKey] === true" :disabled="busy || resetting" @update:model-value="change($event)" />
    </template>

    <template v-else-if="field.kind === 'choice'">
      <Select
        :id="id"
        :model-value="String(form.draft[fieldKey] ?? '')"
        :options="field.choices ?? []"
        :disabled="busy || resetting"
        :block="long"
        @update:model-value="change($event)"
      />
      <button v-if="canReset" type="button" class="set-button set-button--text" :disabled="busy" @click="reset">{{ resetting ? '取消重設' : '重設' }}</button>
    </template>

    <template v-else-if="field.kind === 'int' || field.kind === 'float'">
      <button v-if="canReset" type="button" class="set-button set-button--text" @click="reset">{{ resetting ? '取消重設' : '重設' }}</button>
      <input
        :id="id"
        v-model.number="form.draft[fieldKey]"
        type="number"
        class="set-input set-input--number"
        :min="field.min"
        :max="field.max"
        :step="field.kind === 'float' ? 0.05 : 1"
        :disabled="resetting"
      >
    </template>

    <template v-else-if="field.kind === 'secret'">
      <input
        :id="id"
        v-model="form.secretDraft[fieldKey]"
        type="password"
        class="set-input min-w-0 flex-1"
        autocomplete="new-password"
        spellcheck="false"
        :placeholder="secretPlaceholder"
        :disabled="clearing || resetting"
      >
      <button v-if="field.configured || clearing" type="button" class="set-button set-button--text" :disabled="resetting" @click="form.toggleClear(fieldKey)">
        {{ clearing ? '取消移除' : '移除' }}
      </button>
      <button v-if="canReset" type="button" class="set-button set-button--text" @click="reset">{{ resetting ? '取消重設' : '重設' }}</button>
    </template>

    <template v-else-if="field.kind === 'ids'">
      <div class="flex w-full flex-wrap items-center gap-2">
        <span v-for="value in ids" :key="value" class="set-chip">
          {{ value }}
          <button type="button" :aria-label="`移除 ${value}`" :title="`移除 ${value}`" :disabled="resetting" @click="removeId(value)"><X aria-hidden="true" /></button>
        </span>
        <span v-if="!ids.length" class="set-text">還沒有。</span>
      </div>
      <div v-if="$slots.ids" class="w-full"><slot name="ids" /></div>
      <template v-if="!noManualIds">
        <input
          :id="id"
          v-model="idInput"
          type="text"
          class="set-input min-w-0 flex-1"
          :placeholder="placeholder ?? '輸入帳號編號'"
          :disabled="resetting"
          @keyup.enter="addIds"
        >
        <button type="button" class="set-button" :disabled="!idInput.trim()" @click="addIds">加入</button>
      </template>
      <button v-if="canReset" type="button" class="set-button set-button--text" @click="reset">{{ resetting ? '取消重設' : '重設' }}</button>
    </template>

    <template v-else>
      <input
        :id="id"
        v-model="form.draft[fieldKey]"
        :type="field.kind === 'url' ? 'url' : 'text'"
        class="set-input min-w-0 flex-1"
        spellcheck="false"
        :placeholder="placeholder"
        :disabled="resetting"
      >
      <button v-if="canReset" type="button" class="set-button set-button--text" @click="reset">{{ resetting ? '取消重設' : '重設' }}</button>
    </template>
  </SettingRow>
</template>
