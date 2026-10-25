import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '@/lib/api'
import type { RadarSource, RadarTopic, RadarDigest } from '@/lib/api'

export const useRadarStore = defineStore('radar', () => {
  const sources = ref<RadarSource[]>([])
  const topics = ref<RadarTopic[]>([])
  const digests = ref<RadarDigest[]>([])
  const scanning = ref(false)
  const loaded = ref(false)

  async function load() {
    const [s, t, d] = await Promise.allSettled([
      api.getRadarSources(),
      api.getRadarTopics(),
      api.getRadarDigests(),
    ])
    if (s.status === 'fulfilled') sources.value = s.value.sources ?? []
    if (t.status === 'fulfilled') topics.value = t.value.topics ?? []
    if (d.status === 'fulfilled') digests.value = d.value.digests ?? []
    loaded.value = true
  }

  async function ensureLoaded() {
    if (!loaded.value) await load()
  }

  return { sources, topics, digests, scanning, loaded, load, ensureLoaded }
})
