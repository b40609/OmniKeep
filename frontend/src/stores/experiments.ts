import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import { getSettings } from '@/lib/api'
import { NO_EXPERIMENTS, experimentsSupported, readExperiments, type ExperimentFlags } from '@/lib/experiments'

/**
 * Which experimental features are switched on (設定 › 實驗功能). The server holds the
 * switches; the last answer is kept in this browser so the sidebar does not flicker
 * on the next visit before the server has replied.
 */
export const useExperimentsStore = defineStore('experiments', () => {
  const flags = useLocalStorage<ExperimentFlags>('omnikeep-experiments', { ...NO_EXPERIMENTS }, { mergeDefaults: true })
  /** False when the server is from before the switches existed. */
  const supported = ref(true)

  function apply(groups: Parameters<typeof readExperiments>[0]) {
    flags.value = readExperiments(groups)
    supported.value = experimentsSupported(groups)
  }

  async function load() {
    try {
      apply((await getSettings()).groups)
    } catch {
      /* offline or signed out: keep the last known state */
    }
  }

  return { flags, supported, apply, load }
})
