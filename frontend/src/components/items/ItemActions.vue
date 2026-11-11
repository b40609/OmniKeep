<script setup lang="ts">
import { Star, Archive, ArchiveRestore, MoreHorizontal, Copy, ExternalLink, Camera, ChevronUp, ChevronDown, Ban, Trash2 } from 'lucide-vue-next'
import { DropdownMenuRoot, DropdownMenuTrigger, DropdownMenuPortal, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator } from 'reka-ui'
import { toast } from 'vue-sonner'
import type { Item } from '@/lib/api'
import { useMutations } from '@/composables/useMutations'
import { useSignal } from '@/composables/useSignal'

/**
 * The actions on one item, as icon buttons: star, archive, and a menu for the rest.
 * The wall, the list and the reader all use this one set, so an icon always means
 * the same thing. `compact` is the wall's version: star and archive only.
 */
const props = defineProps<{ item: Item; allowDelete?: boolean; compact?: boolean }>()
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
  <div class="item-actions" role="group" aria-label="項目操作" @click.stop>
    <button
      type="button"
      class="item-action"
      :class="{ 'item-action--on': !!item.is_starred }"
      :aria-label="item.is_starred ? '取消加星' : '加星'"
      :aria-pressed="!!item.is_starred"
      :title="item.is_starred ? '取消加星　S' : '加星　S'"
      @click="toggleStar(item)"
    >
      <Star :class="item.is_starred ? 'fill-current' : ''" />
    </button>
    <button
      type="button"
      class="item-action"
      :aria-label="item.is_read ? '取消封存' : '封存'"
      :title="item.is_read ? '取消封存　E' : '封存　E'"
      @click="toggleRead(item)"
    >
      <ArchiveRestore v-if="item.is_read" />
      <Archive v-else />
    </button>
    <DropdownMenuRoot v-if="!compact">
      <DropdownMenuTrigger class="item-action" aria-label="更多操作" title="更多操作"><MoreHorizontal /></DropdownMenuTrigger>
      <DropdownMenuPortal>
        <DropdownMenuContent class="app-menu" align="end" :side-offset="4" :collision-padding="12" @click.stop @keydown.stop>
          <DropdownMenuItem class="app-menu__item" @select="copyTakeaway"><Copy />複製重點</DropdownMenuItem>
          <DropdownMenuItem class="app-menu__item" @select="openSnapshot(item)"><Camera />開啟離線快照</DropdownMenuItem>
          <DropdownMenuItem as-child><a :href="item.url" target="_blank" rel="noopener noreferrer" class="app-menu__item"><ExternalLink />開啟原始連結</a></DropdownMenuItem>
          <DropdownMenuSeparator class="app-menu__rule" />
          <DropdownMenuItem class="app-menu__item" @select="tuneItem({ item, action: 'boost' })"><ChevronUp />多推薦這類內容</DropdownMenuItem>
          <DropdownMenuItem class="app-menu__item" @select="tuneItem({ item, action: 'dampen' })"><ChevronDown />少推薦這類內容</DropdownMenuItem>
          <DropdownMenuItem class="app-menu__item" @select="tuneItem({ item, action: 'mute' })"><Ban />不再推薦這類內容</DropdownMenuItem>
          <template v-if="allowDelete">
            <DropdownMenuSeparator class="app-menu__rule" />
            <DropdownMenuItem class="app-menu__item text-danger" @select="removeItem(item)"><Trash2 />刪除</DropdownMenuItem>
          </template>
        </DropdownMenuContent>
      </DropdownMenuPortal>
    </DropdownMenuRoot>
  </div>
</template>
