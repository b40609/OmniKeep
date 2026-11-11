<script setup lang="ts">
import ItemActions from './ItemActions.vue'
import ItemCover from './ItemCover.vue'
import KindIcon from './KindIcon.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime } from '@/lib/format'
import { itemKind } from '@/lib/wall'
import { useUiStore } from '@/stores/ui'

const props = defineProps<{ item: Item; active: boolean }>()
const ui = useUiStore()

function select() {
  ui.cursorId = props.item.id
  ui.activeItem = props.item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <article
    class="cover-host group relative flex items-center gap-3 border-b border-hairline px-4 py-3 transition-colors sm:px-6"
    :class="[active ? 'bg-primary-soft' : 'bg-shell hover:bg-surface-1', { 'is-read': !!item.is_read }]"
    @click="select"
  >
    <ItemCover :item="item" variant="thumb" class="w-24 shrink-0 @min-[26rem]:w-[120px]" />
    <div class="min-w-0 flex-1">
      <h3 class="item-row__title text-sm font-semibold leading-5 text-foreground">
        <button class="block w-full text-left" :aria-pressed="active" @click.stop="select">
          <span class="title-clamp">
            <span v-if="!item.is_read" class="unread-dot" aria-hidden="true" /><span v-if="!item.is_read" class="sr-only">未讀：</span>{{ item.title_l1 }}
          </span>
        </button>
      </h3>
      <div class="item-meta mt-1.5">
        <KindIcon :kind="itemKind(item)" />
        <span class="item-meta__clip" :title="cleanHost(item.url)">{{ cleanHost(item.url) }}</span>
        <span class="item-meta__sep" aria-hidden="true" />
        <time>{{ formatRelativeTime(item.created_at) }}</time>
        <template v-if="item.category_name">
          <span class="item-meta__sep" aria-hidden="true" />
          <span class="item-meta__clip">{{ item.category_name === 'Inbox' ? '收件匣' : item.category_name }}</span>
        </template>
        <template v-if="item.origin === 'radar'">
          <span class="item-meta__sep @max-[40rem]:hidden" aria-hidden="true" />
          <span class="@max-[40rem]:hidden">自動收錄</span>
        </template>
      </div>
    </div>
    <ItemActions :item="item" class="@max-[26rem]:hidden" />
  </article>
</template>
