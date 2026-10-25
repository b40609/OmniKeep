<script setup lang="ts">
import { ref, watch } from 'vue'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import Button from '@/components/ui/button/Button.vue'
import * as api from '@/lib/api'
import { useUiStore } from '@/stores/ui'
import { useItemsStore } from '@/stores/items'
import { toast } from 'vue-sonner'

const ui = useUiStore()
const itemsStore = useItemsStore()
const name = ref('')

watch(
  () => ui.showCategoryModal,
  (open) => {
    if (open) name.value = ''
  },
)

async function submit() {
  const trimmed = name.value.trim()
  if (!trimmed) return
  try {
    await api.createCategory(trimmed)
    toast.success(`已新增分類「${trimmed}」`)
    ui.showCategoryModal = false
    itemsStore.loadCategories()
  } catch (e) {
    toast.error('新增分類失敗', { description: (e as Error).message })
  }
}
</script>

<template>
  <Dialog :open="ui.showCategoryModal" @update:open="(v) => (ui.showCategoryModal = v)">
    <DialogContent class="max-w-xs">
      <DialogHeader>
        <DialogTitle>新增分類字典</DialogTitle>
      </DialogHeader>
      <input
        v-model="name"
        type="text"
        placeholder="例如：量化交易、機器學習…"
        class="h-9 w-full rounded-lg border border-border bg-input px-3 text-xs text-foreground transition-all placeholder:text-subtle-foreground focus:border-primary focus:ring-2 focus:ring-primary/25 focus:outline-none"
        autofocus
        @keyup.enter="submit"
      >
      <div class="flex justify-end gap-2">
        <Button variant="ghost" @click="ui.showCategoryModal = false">取消</Button>
        <Button :disabled="!name.trim()" @click="submit">新增</Button>
      </div>
    </DialogContent>
  </Dialog>
</template>
