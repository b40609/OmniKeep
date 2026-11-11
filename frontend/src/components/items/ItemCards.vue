<script setup lang="ts">
import { computed } from 'vue'
import { Star } from 'lucide-vue-next'
import ItemCover from './ItemCover.vue'
import KindIcon from './KindIcon.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime } from '@/lib/format'
import { itemKind } from '@/lib/wall'
import { useUiStore } from '@/stores/ui'
import { useMutations } from '@/composables/useMutations'

/** One cell of the cover wall: cover, a title of at most two lines, one line of meta. */
const props = defineProps<{ item: Item }>()
const ui = useUiStore()
const { toggleRead, toggleStar } = useMutations()

// The ring marks the open item, or where J/K currently is while nothing is open.
const selected = computed(() => (ui.activeItem ? ui.activeItem.id === props.item.id : ui.cursorId === props.item.id))

function open() {
  ui.cursorId = props.item.id
  ui.activeItem = props.item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <article
    class="cover-card cover-host"
    :class="{ 'is-read': !!item.is_read, 'is-cursor': selected }"
    :data-item-id="item.id"
  >
    <ItemCover :item="item" variant="card" />
    <h3 class="cover-card__title">
      <button type="button" class="cover-card__open" :aria-pressed="ui.activeItem?.id === item.id" @click="open">
        <span class="title-clamp">
          <span v-if="!item.is_read" class="unread-dot" aria-hidden="true" /><span v-if="!item.is_read" class="sr-only">未讀：</span>{{ item.title_l1 }}
        </span>
      </button>
    </h3>
    <div class="item-meta cover-card__meta">
      <KindIcon :kind="itemKind(item)" />
      <span class="item-meta__clip" :title="cleanHost(item.url)">{{ cleanHost(item.url) }}</span>
      <span class="item-meta__sep" aria-hidden="true" />
      <time>{{ formatRelativeTime(item.created_at) }}</time>
      <Star v-if="item.is_starred" class="fill-current" role="img" aria-label="已留著" />
      <span class="cover-card__acts" role="group" aria-label="處理這一則" @click.stop>
        <button type="button" class="wall-action wall-action--primary" :title="item.is_read ? '放回收件匣' : '封存：離開收件匣，之後仍搜尋得到（E）'" @click="toggleRead(item)">
          {{ item.is_read ? '移回待讀' : '知道了' }}
        </button>
        <button type="button" class="wall-action" :aria-pressed="!!item.is_starred" :title="item.is_starred ? '取消加星' : '加星保留（S）'" @click="toggleStar(item)">
          {{ item.is_starred ? '取消留著' : '留著' }}
        </button>
      </span>
    </div>
  </article>
</template>
