<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import Switch from '@/components/ui/switch/Switch.vue'
import SettingBlock from './SettingBlock.vue'
import SettingRow from './SettingRow.vue'
import { getRadarSettings, updateRadarSettings } from '@/lib/api'
import { EXPERIMENTS } from '@/lib/experiments'
import { useSettingsForm } from '@/composables/useSettingsForm'
import { useExperimentsStore } from '@/stores/experiments'

/**
 * 設定 › 實驗功能: one switch per feature that is still being worked on. A switch only
 * decides whether the feature shows in the app; what keeps running in the background
 * is said in each row, and the radar's own schedule can be stopped from here.
 */
const form = useSettingsForm()
const experiments = useExperimentsStore()

/** Whether the radar's scheduled scans are on (its own setting, not the switch here); null while unknown. */
const radarScanning = ref<boolean | null>(null)
const stopping = ref(false)

async function loadRadar() {
  try {
    radarScanning.value = (await getRadarSettings()).settings.enabled === true
  } catch {
    radarScanning.value = null
  }
}

async function stopRadar() {
  stopping.value = true
  try {
    radarScanning.value = (await updateRadarSettings({ enabled: false })).settings.enabled === true
    toast.success('已停止探索的背景檢查')
  } catch (e) {
    toast.error('無法停止背景檢查', { description: e instanceof Error ? e.message : String(e) })
  } finally {
    stopping.value = false
  }
}

onMounted(loadRadar)
</script>

<template>
  <p v-if="form.snapshot.value && !experiments.supported" class="set-notice mt-6">
    這台伺服器的版本還沒有這些開關。更新 OmniKeep 之後才能開啟。
  </p>

  <SettingBlock id="features" title="功能">
    <SettingRow v-for="e in EXPERIMENTS" :key="e.id" :name="e.label" :help="e.description" :for="`setting-${e.key}`">
      <template #mark>
        <span v-if="form.saving.value.has(e.key)" class="set-note" role="status">儲存中…</span>
        <span v-else-if="form.saved.value.has(e.key)" class="set-note set-note--ok" role="status">已儲存</span>
      </template>
      <template #below>
        <p class="set-row__help">{{ e.background }}</p>
        <p v-if="e.id === 'radar' && radarScanning" class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          <span class="set-status set-status--warn">背景檢查執行中</span>
          <button type="button" class="set-button set-button--small" :disabled="stopping" @click="stopRadar">停止背景檢查</button>
        </p>
        <p v-else-if="e.id === 'radar' && radarScanning === false" class="mt-2"><span class="set-status">背景檢查已停止</span></p>
        <p v-if="form.errors.value[e.key]" class="set-error" role="alert">{{ form.errors.value[e.key] }}</p>
      </template>
      <Switch
        :id="`setting-${e.key}`"
        :model-value="experiments.flags[e.id]"
        :disabled="!form.byKey.value.has(e.key) || form.saving.value.has(e.key)"
        @update:model-value="form.setNow(e.key, $event)"
      />
    </SettingRow>
  </SettingBlock>
</template>
