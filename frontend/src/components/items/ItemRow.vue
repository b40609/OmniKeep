<script setup lang="ts">
import { computed } from 'vue'
import ItemActions from './ItemActions.vue'
import ItemCover from './ItemCover.vue'
import KindIcon from './KindIcon.vue'
import type { Item } from '@/lib/api'
import { cleanHost, formatRelativeTime } from '@/lib/format'
import { isNotAnalysed, itemKind, plainSummary, splitTitle } from '@/lib/wall'
import { useUiStore } from '@/stores/ui'

/** One row of the list: a large thumbnail, then name, what it is, meta and a two-line summary. */
const props = defineProps<{ item: Item; active: boolean }>()
const ui = useUiStore()
const title = computed(() => splitTitle(props.item.title_l1))

function select() {
  ui.cursorId = props.item.id
  ui.activeItem = props.item
  ui.detailTab = 'analysis'
}
</script>

<template>
  <article
    class="list-row cover-host"
    :class="{ 'is-read': !!item.is_read, 'is-active': active }"
    @click="select"
  >
    <ItemCover :item="item" variant="thumb" class="list-row__thumb" />
    <div class="min-w-0 flex-1">
      <h3 class="list-row__title">
        <button type="button" class="block w-full text-left" :aria-pressed="active" @click.stop="select">
          <span class="title-clamp">
            <span v-if="!item.is_read" class="unread-dot" aria-hidden="true" /><span v-if="!item.is_read" class="sr-only">未封存：</span>{{ title.name }}
          </span>
        </button>
      </h3>
      <p v-if="title.detail" class="list-row__detail">{{ title.detail }}</p>
      <div class="item-meta list-row__meta">
        <KindIcon :kind="itemKind(item)" />
        <span class="item-meta__clip" :title="cleanHost(item.url)">{{ cleanHost(item.url) }}</span>
        <span class="item-meta__sep" aria-hidden="true" />
        <time>{{ formatRelativeTime(item.created_at) }}</time>
        <template v-if="item.category_name">
          <span class="item-meta__sep" aria-hidden="true" />
          <span class="item-meta__clip">{{ item.category_name === 'Inbox' ? '收件匣' : item.category_name }}</span>
        </template>
        <template v-if="isNotAnalysed(item)">
          <span class="item-meta__sep" aria-hidden="true" />
          <span class="item-meta__state">尚未分析</span>
        </template>
      </div>
      <p v-if="plainSummary(item.summary_l1)" class="list-row__summary">{{ plainSummary(item.summary_l1) }}</p>
    </div>
    <ItemActions :item="item" class="list-row__acts" />
  </article>
</template>
