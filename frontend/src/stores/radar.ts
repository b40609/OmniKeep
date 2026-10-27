import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '@/lib/api'
import type { RadarSource, RadarTopic, RadarDigest, RadarSettings } from '@/lib/api'

export const useRadarStore = defineStore('radar', () => {
  const sources = ref<RadarSource[]>([])
  const topics = ref<RadarTopic[]>([])
  const digests = ref<RadarDigest[]>([])
  const settings = ref<RadarSettings | null>(null)
  const scanning = ref(false)
  const loaded = ref(false)

  async function load() {
    const [s, t, d, st] = await Promise.allSettled([
      api.getRadarSources(),
      api.getRadarTopics(),
      api.getRadarDigests(),
      api.getRadarSettings(),
    ])
    if (s.status === 'fulfilled') sources.value = s.value.sources ?? []
    if (t.status === 'fulfilled') topics.value = t.value.topics ?? []
    if (d.status === 'fulfilled') digests.value = d.value.digests ?? []
    if (st.status === 'fulfilled') settings.value = st.value.settings ?? null
    loaded.value = true
  }

  async function ensureLoaded() {
    if (!loaded.value) await load()
  }

  async function updateSettings(patch: Partial<RadarSettings>) {
    const res = await api.updateRadarSettings(patch)
    if (res.success && res.settings) {
      settings.value = res.settings
    }
    return res.settings
  }

  async function toggleSource(id: number | string, isActive?: boolean) {
    const res = await api.toggleRadarSourceActive(id, isActive)
    if (res.success && res.source) {
      const idx = sources.value.findIndex(s => String(s.id) === String(id))
      if (idx !== -1) {
        sources.value[idx] = { ...sources.value[idx], ...res.source }
      }
    }
    return res.source
  }

  return { sources, topics, digests, settings, scanning, loaded, load, ensureLoaded, updateSettings, toggleSource }
})
