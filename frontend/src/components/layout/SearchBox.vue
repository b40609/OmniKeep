<script setup lang="ts">
import { computed, nextTick, ref, watch, type Component } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import {
  Search, Sparkles, Inbox, Star, Archive, Layers, Compass, Tag, FolderGit2, MessageSquare, Play, FileText,
  Plus, Settings, LayoutGrid, List, Keyboard, Bell, SunMoon, ListChecks, SlidersHorizontal, Eye, CalendarCheck, Check,
} from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { useItemsStore, type TriageView } from '@/stores/items'
import { useExperimentsStore } from '@/stores/experiments'
import { useRadarStore } from '@/stores/radar'
import { useTheme } from '@/composables/useTheme'
import { WATCH_CATEGORIES } from '@/lib/experiments'
import { KIND_LABELS, type ItemKind } from '@/lib/wall'
import { buildRows, groupRows, keyAction, type OmniEntry, type OmniMode, type OmniRow } from '@/lib/omnibox'

/**
 * The one box of the top bar. Typing searches as before; the panel under it adds
 * asking a question, the filters and the actions, so none of them needs an entry
 * of its own. The rules for its rows and keys are in lib/omnibox.ts.
 */
const emit = defineEmits<{ (e: 'dismiss'): void }>()

const ui = useUiStore()
const items = useItemsStore()
const experiments = useExperimentsStore()
const radar = useRadarStore()
const { mode: themeMode, labels: themeLabels, toggle: toggleTheme } = useTheme()

interface Entry extends OmniEntry {
  icon: Component
  /** A filter that is applied right now. */
  on?: boolean
  /** The key that does the same from the page; shown where there is a keyboard. */
  shortcut?: string
  run: () => void
}

const root = ref<HTMLElement | null>(null)
const input = ref<HTMLInputElement | null>(null)
const list = ref<HTMLElement | null>(null)
const text = ref(items.searchQuery ?? '')
const mode = ref<OmniMode>('search')
const open = ref(false)
const active = ref(0)

/* ---------------- Search: unchanged, live as you type ---------------- */

const debouncedSearch = useDebounceFn(() => items.loadItems(), 250)
// In search mode the box and the list's search are one value; a question is never searched for.
watch(text, (value) => {
  if (mode.value === 'search' && items.searchQuery !== value) {
    items.searchQuery = value
    void debouncedSearch()
  }
})
watch(() => items.searchQuery, (value) => {
  if (mode.value === 'search' && value !== text.value) text.value = value
})

/** Empty the box; the list goes back to everything if it was showing results. */
function clearText() {
  const searched = !!items.searchQuery.trim()
  text.value = ''
  items.searchQuery = ''
  if (searched) void items.loadItems()
}

function setMode(next: OmniMode) {
  if (mode.value === next) return
  mode.value = next
  active.value = 0
  if (next === 'ask') {
    // What was typed becomes the question, so the list stops being narrowed by it.
    if (items.searchQuery.trim()) {
      items.searchQuery = ''
      void items.loadItems()
    }
  } else if (text.value.trim()) {
    items.searchQuery = text.value
    void items.loadItems()
  }
}

/* ---------------- Filters and actions ---------------- */

function showView(view: TriageView) {
  items.triageView = view
  items.currentCategory = '全部'
  void items.loadItems()
}
function toggleKind(kind: ItemKind) {
  items.kindFilter = items.kindFilter === kind ? 'all' : kind
}
function toggleCategory(name: string) {
  items.currentCategory = items.currentCategory === name ? '全部' : name
  void items.loadItems()
}

/** Categories the empty box lists. */
const SHOWN_CATEGORIES = 3
const KIND_ICONS: Record<ItemKind, Component> = { project: FolderGit2, post: MessageSquare, video: Play, article: FileText }
const count = (n: number | undefined) => `${n ?? 0} 則`

const entries = computed<Entry[]>(() => {
  const view = items.triageView
  const list: Entry[] = [
    { id: 'view-inbox', group: 'filter', label: '收件匣', hint: count(items.stats.inbox), keywords: ['未封存', '還沒看', '待讀'], icon: Inbox, on: view === 'inbox', run: () => showView('inbox') },
    { id: 'view-starred', group: 'filter', label: '加星', hint: count(items.stats.starred), icon: Star, on: view === 'starred', run: () => showView('starred') },
    { id: 'view-archived', group: 'filter', label: '封存', hint: count(items.stats.archived), icon: Archive, on: view === 'archived', run: () => showView('archived') },
    { id: 'view-all', group: 'filter', label: '全部', hint: count(items.stats.total), keywords: ['所有收藏'], icon: Layers, on: view === 'all', run: () => showView('all') },
  ]
  // Experimental features are listed only while they are switched on (設定 › 實驗功能).
  if (experiments.flags.radar) {
    list.push({ id: 'view-radar', group: 'filter', label: '探索', hint: count(items.stats.radar), icon: Compass, on: view === 'radar', run: () => showView('radar') })
  }
  for (const kind of Object.keys(KIND_LABELS) as ItemKind[]) {
    list.push({ id: `kind-${kind}`, group: 'filter', label: KIND_LABELS[kind], hint: '類型', icon: KIND_ICONS[kind], on: items.kindFilter === kind, run: () => toggleKind(kind) })
  }
  // Every category can be found by typing; the empty box lists the ones in use, fullest first.
  const categories = items.categories.filter((c) => c.name !== 'Inbox' && (experiments.flags.watch || !WATCH_CATEGORIES.includes(c.name)))
  const shown = new Set(categories.filter((c) => c.item_count).sort((a, b) => (b.item_count ?? 0) - (a.item_count ?? 0)).slice(0, SHOWN_CATEGORIES).map((c) => c.id))
  for (const c of categories) {
    const on = items.currentCategory === c.name
    list.push({ id: `cat-${c.id}`, group: 'filter', label: c.name, hint: `分類　${count(c.item_count)}`, icon: Tag, on, quiet: !on && !shown.has(c.id), run: () => toggleCategory(c.name) })
  }

  const wall = items.viewMode === 'cards'
  list.push(
    { id: 'add', group: 'action', label: '新增', shortcut: 'N', keywords: ['連結', '筆記', '匯入', '書籤', '檔案', '收藏'], icon: Plus, run: () => ui.openAdd() },
    { id: 'settings', group: 'action', label: '設定', keywords: ['外觀', '收錄管道', 'AI 連線', '備份'], icon: Settings, run: () => ui.openSettings() },
    { id: 'view-mode', group: 'action', label: wall ? '切換到清單檢視' : '切換到格狀檢視', keywords: ['封面牆', '清單', '格狀', '檢視'], icon: wall ? List : LayoutGrid, run: () => (items.viewMode = wall ? 'list' : 'cards') },
    { id: 'shortcuts', group: 'action', label: '鍵盤快捷鍵', shortcut: '?', icon: Keyboard, run: () => (ui.showShortcutsModal = true) },
    { id: 'notifications', group: 'action', label: '通知設定', quiet: true, icon: Bell, run: () => ui.openSettings('notifications') },
    { id: 'theme', group: 'action', label: '切換主題', hint: `目前：${themeLabels[themeMode.value]}`, keywords: ['深色', '淺色', '外觀'], quiet: true, icon: SunMoon, run: () => toggleTheme() },
  )
  if (experiments.flags.radar) {
    list.push(
      { id: 'radar-deck', group: 'action', label: '逐則篩選', shortcut: 'D', keywords: ['探索'], icon: ListChecks, run: () => (ui.showDeckModal = true) },
      { id: 'radar-settings', group: 'action', label: '探索設定', shortcut: 'R', keywords: ['探索來源', '排程'], icon: SlidersHorizontal, run: () => { ui.showRadarModal = true; void radar.ensureLoaded() } },
    )
  }
  if (experiments.flags.watch) {
    list.push({ id: 'watch', group: 'action', label: '專案監看', keywords: ['建議'], icon: Eye, run: () => (ui.showWatchModal = true) })
  }
  if (experiments.flags.daily) {
    list.push({ id: 'daily', group: 'action', label: '每日回顧', shortcut: 'Shift+D', icon: CalendarCheck, run: () => (ui.showDailyDeckModal = true) })
  }
  return list
})

const rows = computed(() => buildRows(text.value, mode.value, entries.value))
const sections = computed(() => groupRows(rows.value))
const optionId = (row: OmniRow) => `omni-option-${row.id}`
const activeId = computed(() => (open.value && rows.value[active.value] ? optionId(rows.value[active.value]) : undefined))

// Typing starts again from the first row, which is the search (or, in ask mode, the question).
watch([text, mode], () => (active.value = 0))
watch(rows, (now) => {
  if (active.value >= now.length) active.value = 0
})

/* ---------------- Running a row ---------------- */

function close() {
  open.value = false
  active.value = 0
}
function leave() {
  close()
  input.value?.blur()
}

function runSearch() {
  if (mode.value !== 'search') setMode('search')
  else void items.loadItems()
  leave()
}

function submitAsk() {
  const question = text.value.trim()
  if (!question) return
  mode.value = 'search'
  clearText()
  leave()
  ui.ask(question)
}

function run(row: OmniRow<Entry>) {
  if (row.kind === 'search') return runSearch()
  if (row.kind === 'ask') return submitAsk()
  // Words typed to find a filter or an action are not a search to keep.
  if (text.value) clearText()
  leave()
  row.entry.run()
}

function onKeydown(event: KeyboardEvent) {
  if (event.isComposing) return
  const action = keyAction(event, { rows: rows.value, index: active.value, mode: mode.value, text: text.value })
  if (!action) return
  if (action.type === 'close') {
    // Esc also leaves ask mode: an unsent question is dropped, a search stays.
    if (mode.value === 'ask') {
      mode.value = 'search'
      text.value = ''
    }
    leave()
    return
  }
  event.preventDefault()
  if (!open.value) open.value = true
  if (action.type === 'move') {
    active.value = action.index
    void nextTick(() => list.value?.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' }))
  } else if (action.type === 'run') run(rows.value[action.index])
  else if (action.type === 'ask') submitAsk()
  else setMode('search')
}

function onFocusOut(event: FocusEvent) {
  const next = event.relatedTarget as Node | null
  if (next && root.value?.contains(next)) return
  close()
  if (!text.value && mode.value === 'search') emit('dismiss')
}

/* ---------------- Opened from outside: `/`, Ctrl/Cmd+K, B, the mobile bar ---------------- */

async function focus(next: OmniMode = mode.value) {
  setMode(next)
  open.value = true
  await nextTick()
  input.value?.focus()
}
function toggleAsk() {
  void focus(mode.value === 'ask' ? 'search' : 'ask')
}

defineExpose({ focus })
</script>

<template>
  <div ref="root" class="search" @focusout="onFocusOut">
    <div class="search-box flex" :class="{ 'search-box--ask': mode === 'ask' }">
      <Sparkles v-if="mode === 'ask'" aria-hidden="true" />
      <Search v-else aria-hidden="true" />
      <span v-if="mode === 'ask'" class="search-box__mode">提問</span>
      <input
        ref="input"
        v-model="text"
        type="text"
        inputmode="search"
        enterkeyhint="search"
        role="combobox"
        aria-autocomplete="list"
        aria-haspopup="listbox"
        :aria-controls="open ? 'omni-list' : undefined"
        :aria-expanded="open && rows.length > 0"
        :aria-activedescendant="activeId"
        :aria-label="mode === 'ask' ? '提問' : '搜尋或提問'"
        :placeholder="mode === 'ask' ? '問一個和收藏有關的問題' : '搜尋或提問'"
        autocomplete="off"
        autocapitalize="off"
        spellcheck="false"
        @focus="open = true"
        @click="open = true"
        @keydown="onKeydown"
      />
      <button
        v-if="mode === 'search'"
        type="button"
        class="search-box__toggle"
        title="切換關鍵字搜尋與語意搜尋"
        :aria-pressed="items.searchMode === 'semantic'"
        @mousedown.prevent
        @click="items.toggleSearchMode()"
      >{{ items.searchMode === 'semantic' ? '語意' : '關鍵字' }}</button>
      <button
        type="button"
        class="search-box__ask"
        aria-label="提問"
        :title="mode === 'ask' ? '改回搜尋' : '提問：用收藏的內容回答　B'"
        :aria-pressed="mode === 'ask'"
        @mousedown.prevent
        @click="toggleAsk"
      ><Sparkles aria-hidden="true" /></button>
      <kbd class="key-hint max-lg:hidden" title="按 / 或 Ctrl/Cmd+K 開始搜尋">/</kbd>
    </div>

    <div v-if="open" class="omni-panel" @mousedown.prevent>
      <div v-if="rows.length" id="omni-list" ref="list" role="listbox" aria-label="搜尋、提問、篩選與動作" class="omni-panel__list">
        <div v-for="section in sections" :key="section.label" role="group" :aria-label="section.label || '搜尋或提問'">
          <div v-if="section.label" class="omni-panel__label" aria-hidden="true">{{ section.label }}</div>
          <div
            v-for="{ row, index } in section.rows"
            :id="optionId(row)"
            :key="row.id"
            role="option"
            class="omni-row"
            :aria-selected="index === active"
            @mousemove="active = index"
            @click="run(row)"
          >
            <template v-if="row.kind === 'search'">
              <Search aria-hidden="true" />
              <span class="omni-row__label">搜尋「{{ row.text }}」</span>
              <span class="omni-row__end"><kbd v-if="index === active" class="key-hint">Enter</kbd></span>
            </template>
            <template v-else-if="row.kind === 'ask'">
              <Sparkles aria-hidden="true" />
              <span class="omni-row__label">提問「{{ row.text }}」</span>
              <span class="omni-row__end"><kbd v-if="index === active || mode === 'search'" class="key-hint">{{ index === active ? 'Enter' : 'Tab' }}</kbd></span>
            </template>
            <template v-else>
              <component :is="row.entry.icon" aria-hidden="true" />
              <span class="omni-row__label">{{ row.entry.label }}</span>
              <span class="omni-row__end">
                <span v-if="row.entry.hint">{{ row.entry.hint }}</span>
                <kbd v-if="row.entry.shortcut" class="key-hint max-lg:hidden">{{ row.entry.shortcut }}</kbd>
                <Check v-if="row.entry.on" aria-label="已套用" />
              </span>
            </template>
          </div>
        </div>
      </div>
      <!-- Ask mode with nothing typed yet: say what will happen instead of listing things -->
      <p v-else id="omni-list" class="omni-panel__hint">輸入問題後按 Enter，會用你收藏的內容回答，並附上引用的收藏。按 Esc 改回搜尋。</p>
    </div>
  </div>
</template>
