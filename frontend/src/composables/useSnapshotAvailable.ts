import { ref, watch } from 'vue'
import { getSnapshotStatus } from '@/lib/api'
import { originLink } from '@/lib/originLink'
import { useUiStore } from '@/stores/ui'

/**
 * Whether the open item has a saved offline page. false for notes and while unknown, so the
 * snapshot buttons only show when opening one will work (instead of failing with a 404 toast).
 */
export function useSnapshotAvailable() {
  const ui = useUiStore()
  const available = ref(false)
  let request = 0
  watch(() => ui.activeItem?.id, async (id) => {
    const mine = ++request
    available.value = false
    if (id == null || !originLink(ui.activeItem?.url)) return
    try {
      const status = await getSnapshotStatus(id)
      if (mine === request) available.value = !!status.has_snapshot
    } catch {
      if (mine === request) available.value = false
    }
  }, { immediate: true })
  return available
}
