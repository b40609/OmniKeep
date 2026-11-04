<script setup lang="ts">
import { Star, Archive, MoreHorizontal, Copy, ExternalLink, Camera, ChevronUp, ChevronDown, Ban, Trash2 } from 'lucide-vue-next'
import { DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from 'reka-ui'
import { toast } from 'vue-sonner'
import type { Item } from '@/lib/api'
import { useMutations } from '@/composables/useMutations'
import { useSignal } from '@/composables/useSignal'

const props = defineProps<{ item: Item; allowDelete?: boolean }>()
const { toggleStar, toggleRead, openSnapshot, removeItem } = useMutations()
const { tuneItem } = useSignal()

async function copyTakeaway() {
  try {
    await navigator.clipboard.writeText(`${props.item.title_l1}\n\n${props.item.summary_l1}\n\n原始連結：${props.item.url}`)
    toast.success('已複製重點')
  } catch {
    toast.error('無法複製，請允許剪貼簿存取後重試。')
  }
}
</script>

<template>
  <div class="flex shrink-0 items-center" role="group" aria-label="項目操作" @click.stop>
    <button class="item-action" :aria-label="item.is_starred ? '取消星標' : '加入星標'" :aria-pressed="!!item.is_starred" :title="item.is_starred ? '取消星標' : '加入星標'" @click="toggleStar(item)">
      <Star class="size-4" :class="item.is_starred ? 'fill-warning text-warning' : ''" />
    </button>
    <button class="item-action" :aria-label="item.is_read ? '移回待讀' : '封存項目'" :aria-pressed="!!item.is_read" :title="item.is_read ? '移回待讀' : '封存項目'" @click="toggleRead(item)">
      <Archive class="size-4" :class="item.is_read ? 'text-primary-soft-foreground' : ''" />
    </button>
    <DropdownMenuRoot>
      <DropdownMenuTrigger class="item-action" aria-label="更多項目操作" title="更多操作"><MoreHorizontal class="size-4" /></DropdownMenuTrigger>
      <DropdownMenuPortal>
        <DropdownMenuContent class="item-menu" align="end" :side-offset="4" :collision-padding="12" @click.stop @keydown.stop>
          <DropdownMenuItem class="item-menu-entry" @select="copyTakeaway"><Copy class="size-4" />複製重點</DropdownMenuItem>
          <DropdownMenuItem class="item-menu-entry" @select="openSnapshot(item)"><Camera class="size-4" />開啟離線快照</DropdownMenuItem>
          <DropdownMenuItem as-child><a :href="item.url" target="_blank" rel="noopener noreferrer" class="item-menu-entry"><ExternalLink class="size-4" />開啟原始連結</a></DropdownMenuItem>
          <DropdownMenuSeparator class="my-1 h-px bg-border" />
          <DropdownMenuItem class="item-menu-entry" @select="tuneItem({ item, action: 'boost' })"><ChevronUp class="size-4" />增加這類推薦</DropdownMenuItem>
          <DropdownMenuItem class="item-menu-entry" @select="tuneItem({ item, action: 'dampen' })"><ChevronDown class="size-4" />減少這類推薦</DropdownMenuItem>
          <DropdownMenuItem class="item-menu-entry" @select="tuneItem({ item, action: 'mute' })"><Ban class="size-4" />停止推薦這類內容</DropdownMenuItem>
          <template v-if="allowDelete">
            <DropdownMenuSeparator class="my-1 h-px bg-border" />
            <DropdownMenuItem class="item-menu-entry text-danger" @select="removeItem(item)"><Trash2 class="size-4" />刪除項目</DropdownMenuItem>
          </template>
        </DropdownMenuContent>
      </DropdownMenuPortal>
    </DropdownMenuRoot>
  </div>
</template>
