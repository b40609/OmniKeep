import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '@/lib/api'
import type { DecisionPayload, EvaluationCounts, EvaluationRecord } from '@/lib/api'

const EMPTY_COUNTS: EvaluationCounts = {
  needs_decision: 0,
  evaluating: 0,
  approved_l2: 0,
  on_demand: 0,
  adopted: 0,
  rejected: 0,
  failed: 0,
  total: 0,
}

export const useEvaluationsStore = defineStore('evaluations', () => {
  const evaluations = ref<EvaluationRecord[]>([])
  const counts = ref<EvaluationCounts>({ ...EMPTY_COUNTS })
  const activeEvaluation = ref<EvaluationRecord | null>(null)
  const statusFilter = ref<string>('needs_decision')
  const loading = ref(false)
  const loadingDetail = ref(false)
  const deciding = ref(false)
  const error = ref<string | null>(null)

  async function loadEvaluations(status = statusFilter.value) {
    statusFilter.value = status
    loading.value = true
    error.value = null
    try {
      const res = await api.listEvaluations(status)
      evaluations.value = res.evaluations
      counts.value = res.counts
    } catch (e) {
      error.value = e instanceof Error ? e.message : '無法讀取評估清單'
    } finally {
      loading.value = false
    }
  }

  async function openEvaluation(evalId: string) {
    loadingDetail.value = true
    error.value = null
    try {
      activeEvaluation.value = await api.getEvaluation(evalId)
    } catch (e) {
      error.value = e instanceof Error ? e.message : '找不到這筆評估報告'
    } finally {
      loadingDetail.value = false
    }
  }

  async function submitDecision(evalId: string, payload: DecisionPayload) {
    deciding.value = true
    error.value = null
    try {
      const res = await api.decideEvaluation(evalId, payload)
      activeEvaluation.value = res.evaluation
      await loadEvaluations(statusFilter.value)
      return res
    } catch (e) {
      error.value = e instanceof Error ? e.message : '送出決定失敗'
      throw e
    } finally {
      deciding.value = false
    }
  }

  async function requestEvaluation(itemId: string | number, userNote = '', sync = false) {
    const res = await api.triggerItemEvaluation(itemId, { user_note: userNote, sync })
    activeEvaluation.value = res.evaluation
    await loadEvaluations(statusFilter.value)
    return res.evaluation
  }

  function clearActive() {
    activeEvaluation.value = null
  }

  return {
    evaluations,
    counts,
    activeEvaluation,
    statusFilter,
    loading,
    loadingDetail,
    deciding,
    error,
    loadEvaluations,
    openEvaluation,
    submitDecision,
    requestEvaluation,
    clearActive,
  }
})
