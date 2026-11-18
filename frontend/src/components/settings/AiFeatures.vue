<script setup lang="ts">
import { onMounted, ref } from 'vue'
import SettingBlock from './SettingBlock.vue'
import { getAiFeatures, type AiFeature } from '@/lib/api'

/**
 * What this install can do now, feature by feature. A new install works with no account; this is
 * where the owner sees what is basic and the one step that makes it better (app/capabilities.py).
 */
const emit = defineEmits<{ upgrade: [card: string, slot: 'analysis' | 'video'] }>()

const features = ref<AiFeature[]>([])
const summary = ref<string | null>(null)
const failed = ref(false)

const LEVEL = { good: '能用', basic: '基本', off: '沒開' } as const

async function reload() {
  try {
    const res = await getAiFeatures()
    features.value = res.features
    summary.value = res.summary
    failed.value = false
  } catch {
    failed.value = true
  }
}

onMounted(reload)
defineExpose({ reload })
</script>

<template>
  <SettingBlock
    v-if="features.length"
    id="features"
    title="目前能用的功能"
    :description="summary ?? '每一項都已經用上目前最好的方式。'"
  >
    <div v-for="f in features" :key="f.id" class="set-row" data-feature-row>
      <div class="set-row__text">
        <p class="set-row__name">{{ f.name }}</p>
        <p class="set-row__help">{{ f.now }}</p>
        <p v-if="f.level !== 'good' && f.step" class="set-row__help">
          想更好：{{ f.step }}
          <button v-if="f.card" type="button" class="set-link" @click="emit('upgrade', f.card, f.id === 'video' ? 'video' : 'analysis')">新增這條連線</button>
        </p>
      </div>
      <div class="set-row__control">
        <span class="set-status" :class="{ 'set-status--ok': f.level === 'good' }">{{ LEVEL[f.level] }}</span>
      </div>
    </div>
  </SettingBlock>
</template>
