import { toast } from 'vue-sonner'
import * as api from '@/lib/api'
import type { SignalAction } from '@/lib/api'
import { useRadarStore } from '@/stores/radar'

const actionNames: Record<SignalAction, string> = {
  boost: '已加深關注',
  dampen: '已降低頻率',
  mute: '已徹底靜音',
  reset: '已重設',
}

/** Topic-signal tuning (radar feedback) with toast feedback. */
export function useSignal() {
  const radar = useRadarStore()

  async function tuneTopic(tag: string, action: SignalAction) {
    try {
      const data = await api.radarFeedback({ topic_tag: tag, action })
      toast.success(`#${tag} ${actionNames[action]}`, { description: `當前權重 ${data.result?.weight?.toFixed(1) ?? '—'}` })
      radar.load()
    } catch (e) {
      toast.error('調諧失敗', { description: (e as Error).message })
    }
  }

  async function tuneItem(payload: { item: { id: number }; action: SignalAction }) {
    try {
      await api.radarFeedback({ item_id: payload.item.id, action: payload.action })
      toast.success(actionNames[payload.action])
      radar.load()
    } catch (e) {
      toast.error('調諧失敗', { description: (e as Error).message })
    }
  }

  return { tuneTopic, tuneItem }
}
