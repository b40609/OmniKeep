<script setup lang="ts">
import { computed } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import { useSettingsForm } from '@/composables/useSettingsForm'

/** The 儲存 button of a block whose settings are typed: lit only while something changed. */
const props = defineProps<{ keys: string[] }>()
const emit = defineEmits<{ (e: 'saved'): void }>()
const form = useSettingsForm()
const count = computed(() => form.changeCount(props.keys))
const busy = computed(() => props.keys.some((k) => form.saving.value.has(k)))
async function save() {
  if (await form.saveKeys(props.keys)) emit('saved')
}
const done = computed(() => !count.value && props.keys.some((k) => form.saved.value.has(k)))
</script>

<template>
  <button type="button" class="set-button set-button--primary" :disabled="!count || busy" @click="save">
    <Loader2 v-if="busy" class="animate-spin" aria-hidden="true" />
    儲存
  </button>
  <button v-if="count" type="button" class="set-button set-button--text" :disabled="busy" @click="form.resetDrafts(keys)">還原</button>
  <span v-if="done" class="set-note set-note--ok" role="status">已儲存</span>
  <slot />
</template>
