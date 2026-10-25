<script setup lang="ts">
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()

const groups: { title: string; items: [string, string][] }[] = [
  {
    title: '巡航',
    items: [
      ['J / ↓', '下一個項目'],
      ['K / ↑', '上一個項目'],
      ['Enter', '開啟閱覽面板'],
      ['Esc', '關閉面板 / 對話框'],
    ],
  },
  {
    title: '分流',
    items: [
      ['E', '封存 / 移回待讀'],
      ['S', '星標 / 取消星標'],
      ['+ / -', '訊號增強 / 降低'],
    ],
  },
  {
    title: '輸入',
    items: [
      ['N', '聚焦快速存入框'],
      ['/', '聚焦全文搜尋'],
      ['R', '情報雷達面板'],
      ['?', '本快捷鍵指南'],
    ],
  },
]
</script>

<template>
  <Dialog :open="ui.showShortcutsModal" @update:open="(v) => (ui.showShortcutsModal = v)">
    <DialogContent class="max-w-md">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          鍵盤極速操控指南
          <span class="rounded border border-border bg-muted px-1.5 py-px font-mono text-2xs text-muted-foreground">VIM / LINEAR</span>
        </DialogTitle>
      </DialogHeader>

      <div class="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <div v-for="g in groups" :key="g.title">
          <p class="mb-2 font-mono text-2xs font-bold tracking-wider text-subtle-foreground uppercase">{{ g.title }}</p>
          <div class="space-y-1">
            <div v-for="[key, label] in g.items" :key="key" class="flex items-center justify-between gap-3 py-0.5 text-xs">
              <span class="text-muted-foreground">{{ label }}</span>
              <kbd class="rounded-md border border-border bg-muted px-2 py-1 font-mono text-2xs text-foreground shadow-sm">{{ key }}</kbd>
            </div>
          </div>
        </div>
      </div>

      <div class="flex justify-end border-t border-border pt-3">
        <Button variant="secondary" @click="ui.showShortcutsModal = false">我知道了</Button>
      </div>
    </DialogContent>
  </Dialog>
</template>
