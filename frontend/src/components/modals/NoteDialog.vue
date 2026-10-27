<script setup lang="ts">
import { ref, watch } from 'vue'
import { FileText, Loader2 } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { useMutations } from '@/composables/useMutations'

const ui = useUiStore()
const itemsStore = useItemsStore()
const { noteIngest } = useMutations()

const noteContent = ref('')
const noteCategory = ref('')

watch(
  () => ui.showNoteModal,
  (open) => {
    if (open) noteContent.value = ''
  },
)

async function submit() {
  const content = noteContent.value.trim()
  if (!content) return
  const ok = await noteIngest(content, noteCategory.value || null)
  if (ok) ui.showNoteModal = false
}
</script>

<template>
  <Dialog :open="ui.showNoteModal" @update:open="(v) => (ui.showNoteModal = v)">
    <DialogContent class="max-w-2xl">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <FileText class="size-4 text-primary-soft-foreground" />
          存入長篇段落 / 技術筆記
        </DialogTitle>
        <DialogDescription>支援 Markdown、程式碼片段、技術論述或內含網址之長文</DialogDescription>
      </DialogHeader>

      <textarea
        ref="textareaRef"
        v-model="noteContent"
        rows="9"
        placeholder="在此貼上任何長篇段落、GitHub 專案心得、架構解說或零碎思考…"
        class="w-full resize-none rounded-xl border border-white/60 bg-white/55 p-3.5 shadow-sm dark:border-white/10 dark:bg-white/[0.06] font-mono text-xs leading-relaxed text-foreground transition-all placeholder:text-subtle-foreground focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
        autofocus
      />

      <div class="flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 text-xs">
          <span class="text-subtle-foreground">指定分類</span>
          <select v-model="noteCategory" class="h-8 cursor-pointer rounded-lg border border-border bg-input px-3 text-xs font-medium text-foreground shadow-sm focus:border-primary focus:outline-none">
            <option value="" class="bg-popover text-foreground">AI 自動分類</option>
            <option v-for="c in itemsStore.categories" :key="c.id" :value="c.name" class="bg-popover text-foreground">{{ c.name }}</option>
          </select>
        </div>
        <div class="flex items-center gap-2">
          <Button variant="ghost" @click="ui.showNoteModal = false">取消</Button>
          <Button :disabled="!noteContent.trim() || ui.isIngesting" @click="submit">
            <Loader2 v-if="ui.isIngesting" class="size-3.5 animate-spin" />
            {{ ui.isIngesting ? '建立中…' : '儲存筆記' }}
          </Button>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
