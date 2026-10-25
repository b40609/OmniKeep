import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import type { Item } from '@/lib/api'

export type ReaderTab = 'analysis' | 'reader'

export const useUiStore = defineStore('ui', () => {
  // Reader pane — deep reactive: the same item exists as separate objects in
  // the list and here, so mutations are synced into both copies by id.
  const activeItem = ref<Item | null>(null)
  const detailTab = ref<ReaderTab>('analysis')
  const readerFontSize = useLocalStorage('omnikeep-reader-font', 15)
  const readerLineHeight = useLocalStorage('omnikeep-reader-lineh', 1.8)
  const readerWidth = useLocalStorage('omnikeep-reader-width', 720)
  const focusMode = ref(false)

  // Modals
  const showNoteModal = ref(false)
  const showCategoryModal = ref(false)
  const showShortcutsModal = ref(false)
  const showRadarModal = ref(false)
  const showSessionModal = ref(false)
  const showWatchModal = ref(false)

  // Ingest
  const isIngesting = ref(false)

  return {
    activeItem, detailTab, readerFontSize, readerLineHeight, readerWidth, focusMode,
    showNoteModal, showCategoryModal, showShortcutsModal, showRadarModal, showSessionModal, showWatchModal,
    isIngesting,
  }
})
