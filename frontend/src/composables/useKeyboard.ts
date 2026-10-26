import { onMounted, onUnmounted } from 'vue'
import { useItemsStore } from '@/stores/items'
import { useUiStore } from '@/stores/ui'
import { useRadarStore } from '@/stores/radar'
import { useMutations } from './useMutations'
import { useSignal } from './useSignal'

type AppHeaderExposed = { focusQuickInput: () => void; focusSearchInput: () => void }

/** Global keyboard shortcuts — parity with the legacy single-file UI. */
export function useKeyboard(header: () => AppHeaderExposed | null, enabled: () => boolean = () => true) {
  const items = useItemsStore()
  const ui = useUiStore()
  const radar = useRadarStore()
  const { toggleStar, toggleRead } = useMutations()

  function isAnyModalOpen() {
    return (
      ui.showNoteModal ||
      ui.showCategoryModal ||
      ui.showShortcutsModal ||
      ui.showRadarModal ||
      ui.showSessionModal ||
      ui.showWatchModal ||
      ui.showImportModal
    )
  }

  function handleKeyDown(e: KeyboardEvent) {
    if (!enabled()) return
    const el = document.activeElement
    const tag = el?.tagName?.toLowerCase() ?? ''
    const typing =
      tag === 'input' || tag === 'textarea' || tag === 'select' ||
      (el instanceof HTMLElement && el.isContentEditable)

    if (typing) {
      if (e.key === 'Escape') (el as HTMLElement).blur()
      return
    }

    // Modal-level Esc handling is done by Reka Dialog; block list shortcuts while open.
    if (isAnyModalOpen()) {
      if (e.key === 'Escape') {
        ui.showNoteModal = false
        ui.showCategoryModal = false
        ui.showShortcutsModal = false
        ui.showRadarModal = false
        ui.showSessionModal = false
        ui.showWatchModal = false
        ui.showImportModal = false
      }
      return
    }

    switch (e.key) {
      case '?':
        e.preventDefault()
        ui.showShortcutsModal = !ui.showShortcutsModal
        return
      case 'r':
      case 'R':
        e.preventDefault()
        ui.showRadarModal = !ui.showRadarModal
        if (ui.showRadarModal) radar.ensureLoaded()
        return
      case 'i':
      case 'I':
        e.preventDefault()
        ui.showImportModal = !ui.showImportModal
        return

      case '+':
      case '=':
        if (ui.activeItem) {
          e.preventDefault()
          useSignal().tuneItem({ item: ui.activeItem, action: 'boost' })
        }
        return
      case '-':
      case '_':
        if (ui.activeItem) {
          e.preventDefault()
          useSignal().tuneItem({ item: ui.activeItem, action: 'dampen' })
        }
        return
      case 'Escape':
        if (ui.focusMode) {
          ui.focusMode = false
        } else if (ui.activeItem) {
          ui.activeItem = null
        }
        return
      case '/':
        e.preventDefault()
        header()?.focusSearchInput()
        return
      case 'N':
        e.preventDefault()
        header()?.focusQuickInput()
        return
    }

    if (items.items.length === 0) return
    const currentIndex = ui.activeItem ? items.items.findIndex((i) => i.id === ui.activeItem!.id) : -1

    if (e.key === 'j' || e.key === 'ArrowDown') {
      e.preventDefault()
      const next = Math.min(items.items.length - 1, currentIndex + 1)
      ui.activeItem = items.items[next]
    } else if (e.key === 'k' || e.key === 'ArrowUp') {
      e.preventDefault()
      const prev = Math.max(0, currentIndex - 1)
      ui.activeItem = items.items[prev]
    } else if (e.key === 'e' || e.key === 'E') {
      if (ui.activeItem) {
        e.preventDefault()
        toggleRead(ui.activeItem)
      }
    } else if (e.key === 's' || e.key === 'S') {
      if (ui.activeItem) {
        e.preventDefault()
        toggleStar(ui.activeItem)
      }
    } else if (e.key === 'Enter') {
      if (currentIndex === -1 && items.items.length > 0) {
        ui.activeItem = items.items[0]
      }
    }
  }

  onMounted(() => window.addEventListener('keydown', handleKeyDown))
  onUnmounted(() => window.removeEventListener('keydown', handleKeyDown))
}
