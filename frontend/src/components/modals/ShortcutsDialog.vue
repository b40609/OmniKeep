<script setup lang="ts">
import { computed } from 'vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useUiStore } from '@/stores/ui'
import { useExperimentsStore } from '@/stores/experiments'
import type { ExperimentId } from '@/lib/experiments'

const ui = useUiStore()
const experiments = useExperimentsStore()

/** [keys, what it does, the experimental feature it belongs to]. */
type Shortcut = [string, string, ExperimentId?]
const GROUPS: { title: string; items: Shortcut[] }[] = [
  {
    title: '瀏覽',
    items: [
      ['J / ↓', '下一則'],
      ['K / ↑', '上一則'],
      ['Enter', '開啟選取的收藏'],
      ['Esc', '關閉面板或對話框'],
      ['/', '搜尋'],
      ['Ctrl/Cmd+K', '命令列'],
      ['Ctrl/Cmd+B', '展開或收合側邊欄'],
    ],
  },
  {
    title: '整理',
    items: [
      ['E', '封存／取消封存'],
      ['S', '加星／取消加星'],
      ['+ / -', '多推薦／少推薦這類內容'],
    ],
  },
  {
    title: '新增與開啟',
    items: [
      ['N', '貼上連結'],
      ['Shift+N', '新增筆記'],
      ['I', '匯入書籤'],
      ['B', '提問'],
      ['R', '探索設定', 'radar'],
      ['D', '逐則篩選', 'radar'],
      ['Shift+D', '每日回顧', 'daily'],
      ['?', '鍵盤快捷鍵'],
    ],
  },
]
// A feature that is switched off has no shortcut, so it is not listed either.
const groups = computed(() =>
  GROUPS.map((g) => ({ ...g, items: g.items.filter(([, , experiment]) => !experiment || experiments.flags[experiment]) })))
</script>

<template>
  <Dialog :open="ui.showShortcutsModal" @update:open="(v) => (ui.showShortcutsModal = v)">
    <DialogContent class="max-w-xl">
      <DialogHeader>
        <DialogTitle>鍵盤快捷鍵</DialogTitle>
      </DialogHeader>

      <div class="grid grid-cols-1 gap-x-8 gap-y-6 sm:grid-cols-2">
        <div v-for="g in groups" :key="g.title">
          <h3 class="mb-2 text-sm font-semibold">{{ g.title }}</h3>
          <dl>
            <div v-for="[key, label] in g.items" :key="key" class="flex min-h-9 items-center justify-between gap-3 text-sm">
              <dt class="text-muted-foreground">{{ label }}</dt>
              <dd><kbd class="rounded-md bg-surface-2 px-2 py-1 font-mono text-xs text-foreground">{{ key }}</kbd></dd>
            </div>
          </dl>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
