import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'
import { useLocalStorage } from '@vueuse/core'
import type { Item } from '@/lib/api'
import { DEFAULT_SECTION, resolveSettingsTarget, type SettingsSectionId } from '@/lib/settingsSections'

export type ReaderTab = 'analysis' | 'reader'
export type WatchTab = 'targets' | 'proposals' | 'backup'
export type ImportTab = 'file' | 'text' | 'bookmarklet' | 'export'

export const useUiStore = defineStore('ui', () => {
  // Navigation & Layout
  const sidebarOpen = useLocalStorage('omnikeep-sidebar', true)
  const sidebarMobileOpen = ref(false)
  /** Bumped to ask the header to open and focus its search box (the mobile bottom bar does this). */
  const searchFocusRequests = ref(0)
  /** A question picked in the search box, waiting for the answer dialog to send it. */
  const pendingQuestion = ref('')

  // Reader pane — deep reactive: the same item exists as separate objects in
  // the list and here, so mutations are synced into both copies by id.
  const activeItem = ref<Item | null>(null)
  /** Item the keyboard is on in the cover wall (J/K) without opening it; null until first used. */
  const cursorId = ref<number | null>(null)
  const detailTab = ref<ReaderTab>('analysis')
  const readerFontSize = useLocalStorage('omnikeep-reader-font', 16)
  const readerLineHeight = useLocalStorage('omnikeep-reader-lineh', 1.8)
  const readerWidth = useLocalStorage('omnikeep-reader-width', 720)
  const focusMode = ref(false)

  // Modals
  /** 新增: one panel for links, notes and bookmark files (components/modals/AddDialog.vue). */
  const showAddModal = ref(false)
  /** Text the 新增 panel opens with (an address pasted on the page). */
  const addDraft = ref('')
  const showCategoryModal = ref(false)
  const showShortcutsModal = ref(false)
  const showRadarModal = ref(false)
  const showWatchModal = ref(false)
  const watchTab = ref<WatchTab>('targets')
  const showImportModal = ref(false)
  /** Tab the import dialog opens on. */
  const importTab = ref<ImportTab>('file')
  /** A bookmark file handed over by the 新增 panel; the import dialog takes it and clears this. */
  const importFile = shallowRef<File | null>(null)
  const showDeckModal = ref(false)
  const showDailyDeckModal = ref(false)
  const showBrainModal = ref(false)

  // Settings: a full page over the workspace (components/settings/SettingsPage.vue).
  const showSettingsModal = ref(false)
  const settingsTab = ref<SettingsSectionId>(DEFAULT_SECTION)
  /** Block inside the section to bring into view once it is drawn; cleared by the page. */
  const settingsBlock = ref('')
  /** On a phone: the list of groups, or one group's settings. */
  const settingsLevel = ref<'list' | 'detail'>('detail')
  /** Bumped to ask the settings page to close (Esc); it may ask about unsaved changes first. */
  const settingsCloseRequests = ref(0)
  /** Bumped after settings are saved, so the service-status banner re-checks. */
  const settingsVersion = ref(0)
  /** First-run guide shown while no AI provider is usable. */
  const showSetupWizard = ref(false)

  /** AI service card an agent's settings link asked to focus (`#settings=ai&card=agnes`). */
  const settingsCard = ref('')

  /**
   * `tab` is a section of the settings page, or one of the older tab ids that
   * settings links still carry (`telegram`, `push`, `system`…).
   */
  function openSettings(tab?: string, card = '', block = '') {
    const target = resolveSettingsTarget(tab ?? DEFAULT_SECTION, block)
    // Asked for nothing in particular: a phone starts at the list of groups.
    settingsLevel.value = tab === undefined ? 'list' : 'detail'
    settingsTab.value = target.section
    settingsBlock.value = target.block
    settingsCard.value = card
    showSettingsModal.value = true
    sidebarMobileOpen.value = false
  }

  function openImport(tab: ImportTab = 'file', file: File | null = null) {
    importTab.value = tab
    importFile.value = file
    showImportModal.value = true
  }

  function openAdd(text = '') {
    addDraft.value = text
    showAddModal.value = true
    sidebarMobileOpen.value = false
  }

  /** Answer a question from the saved items: the answer dialog opens and sends it. */
  function ask(question: string) {
    const q = question.trim()
    if (!q) return
    pendingQuestion.value = q
    showBrainModal.value = true
  }

  /** Saved page shown in SnapshotDialog; null while closed. */
  const snapshotView = ref<{ title: string; url: string; html: string } | null>(null)

  // Ingest
  const isIngesting = ref(false)

  return {
    sidebarOpen, sidebarMobileOpen, searchFocusRequests, pendingQuestion, ask,
    activeItem, cursorId, detailTab, readerFontSize, readerLineHeight, readerWidth, focusMode,
    showAddModal, addDraft, openAdd, showCategoryModal, showShortcutsModal, showRadarModal, showWatchModal, showImportModal, importTab, importFile, openImport, showDeckModal,
    showDailyDeckModal, showBrainModal,
    showSettingsModal, settingsTab, settingsBlock, settingsLevel, settingsCloseRequests, settingsCard, settingsVersion, openSettings, showSetupWizard,
    watchTab, snapshotView,
    isIngesting,
  }
})
