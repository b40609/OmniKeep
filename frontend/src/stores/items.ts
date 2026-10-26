import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '@/lib/api'
import type { Item, Category, Stats } from '@/lib/api'

export type TriageView = 'inbox' | 'starred' | 'archived' | 'all'
export type ViewMode = 'list' | 'cards'
export type SearchMode = 'keyword' | 'semantic'

export const useItemsStore = defineStore('items', () => {
  const items = ref<Item[]>([])
  const categories = ref<Category[]>([])
  const stats = ref<Stats>({ inbox: 0, starred: 0, archived: 0, total: 0 })
  const loading = ref(false)

  // Filters
  const triageView = ref<TriageView>('inbox')
  const currentCategory = ref('全部')
  const searchQuery = ref('')
  const searchMode = ref<SearchMode>('keyword')
  const viewMode = ref<ViewMode>('list')

  async function loadItems() {
    loading.value = true
    try {
      const q = searchQuery.value.trim()
      if (q && searchMode.value === 'semantic') {
        const results = await api.searchSemantic(q, 30)
        items.value = results.filter((item) => {
          if (currentCategory.value !== '全部' && item.category_name !== currentCategory.value) {
            return false
          }
          if (triageView.value === 'inbox' && item.is_read) return false
          if (triageView.value === 'archived' && !item.is_read) return false
          if (triageView.value === 'starred' && !item.is_starred) return false
          return true
        })
      } else {
        items.value = await api.getItems({
          category: currentCategory.value !== '全部' ? currentCategory.value : undefined,
          q: q || undefined,
          read: triageView.value === 'inbox' ? 'false' : triageView.value === 'archived' ? 'true' : undefined,
          starred: triageView.value === 'starred' ? 'true' : undefined,
        })
      }
    } finally {
      loading.value = false
    }
  }

  function toggleSearchMode() {
    searchMode.value = searchMode.value === 'keyword' ? 'semantic' : 'keyword'
    if (searchQuery.value.trim()) {
      void loadItems()
    }
  }

  async function loadStats() {
    try {
      stats.value = await api.getStats()
    } catch {
      /* stats are non-critical */
    }
  }

  async function loadCategories() {
    try {
      categories.value = await api.getCategories()
    } catch {
      /* keep stale categories */
    }
  }

  function refreshAll() {
    return Promise.all([loadStats(), loadCategories(), loadItems()])
  }

  return {
    items, categories, stats, loading,
    triageView, currentCategory, searchQuery, searchMode, viewMode,
    toggleSearchMode,
    loadItems, loadStats, loadCategories, refreshAll,
  }
})
