<script setup lang="ts">
import { ref } from 'vue'
import { Radar, Loader2, Plus, Trash2 } from 'lucide-vue-next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Badge from '@/components/ui/badge/Badge.vue'
import Button from '@/components/ui/button/Button.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import * as api from '@/lib/api'
import { sourceMeta, formatRelativeTime } from '@/lib/format'
import { renderMarkdown } from '@/lib/markdown'
import { useUiStore } from '@/stores/ui'
import { useRadarStore } from '@/stores/radar'
import { useSignal } from '@/composables/useSignal'
import { toast } from 'vue-sonner'

const ui = useUiStore()
const radar = useRadarStore()
const { tuneTopic } = useSignal()

type RadarTab = 'sources' | 'topics' | 'digests'
const tab = ref<RadarTab>('sources')
const isScanning = ref(false)

const newSource = ref({ name: '', source_type: 'youtube', url: '' })

async function addSource() {
  if (!newSource.value.name || !newSource.value.url) return
  try {
    await api.addRadarSource(newSource.value)
    toast.success(`已加入追蹤：${newSource.value.name}`)
    newSource.value = { name: '', source_type: 'youtube', url: '' }
    await radar.load()
  } catch (e) {
    toast.error('新增來源失敗', { description: (e as Error).message })
  }
}

async function removeSource(id: number) {
  try {
    await api.deleteRadarSource(id)
    toast.success('已移除情報來源')
    await radar.load()
  } catch (e) {
    toast.error('移除失敗', { description: (e as Error).message })
  }
}

async function scan() {
  isScanning.value = true
  const t = toast.loading('自適應巡檢啟動，時段感知採集中…')
  try {
    const data = await api.radarScan()
    const count = data.result?.new_items_count ?? 0
    toast.success(`巡檢完成，捕獲 ${count} 筆新情報`, { id: t })
    await radar.load()
  } catch (e) {
    toast.error('巡檢異常', { id: t, description: (e as Error).message })
  } finally {
    isScanning.value = false
  }
}
</script>

<template>
  <Dialog :open="ui.showRadarModal" @update:open="(v) => (ui.showRadarModal = v)">
    <DialogContent class="flex max-h-[88vh] max-w-3xl flex-col gap-0 p-0 overflow-hidden">
      <!-- Header -->
      <div class="flex shrink-0 items-center justify-between border-b border-border p-5 pb-4">
        <div class="flex items-center gap-2.5">
          <div class="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Radar class="size-4.5" />
          </div>
          <DialogHeader>
            <DialogTitle class="flex items-center gap-2">
              情報雷達與自適應調度引擎
              <span class="rounded border border-primary/30 bg-primary-soft px-1.5 py-px font-mono text-2xs text-primary-soft-foreground">ADAPTIVE RADAR</span>
            </DialogTitle>
            <DialogDescription>YouTube 晚間高峰學習 · GitHub ETag · RSS · 信號調諧庫</DialogDescription>
          </DialogHeader>
        </div>
        <Button :disabled="isScanning" @click="scan">
          <Loader2 v-if="isScanning" class="size-3.5 animate-spin" />
          {{ isScanning ? '巡檢中…' : '立即巡檢' }}
        </Button>
      </div>

      <!-- Tabs -->
      <div class="flex shrink-0 items-center gap-1 border-b border-border px-5 text-xs" role="tablist">
        <button
          v-for="t in [
            { id: 'sources', label: `訂閱來源 (${radar.sources.length})` },
            { id: 'topics', label: `話題信號調諧庫 (${radar.topics.length})` },
            { id: 'digests', label: `自動焦點戰報 (${radar.digests.length})` },
          ]"
          :key="t.id"
          role="tab"
          :aria-selected="tab === t.id"
          class="relative flex h-10 items-center px-3 font-medium transition-colors"
          :class="tab === t.id ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="tab = t.id as RadarTab"
        >
          {{ t.label }}
          <span v-if="tab === t.id" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
      </div>

      <!-- Panels -->
      <div class="min-h-0 flex-1 overflow-y-auto p-5">
        <!-- Sources -->
        <div v-if="tab === 'sources'" class="space-y-4">
          <div class="glass-tint rounded-xl p-3.5">
            <p class="mb-2.5 text-xs font-semibold text-foreground">新增自動追蹤來源</p>
            <div class="grid grid-cols-1 gap-2 text-xs sm:grid-cols-4">
              <input v-model="newSource.name" type="text" placeholder="名稱（如：3Blue1Brown）" class="h-8 rounded-md border border-border bg-input px-2.5 text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none">
              <select v-model="newSource.source_type" class="h-8 rounded-md border border-border bg-input px-2 text-xs text-foreground focus:border-primary focus:outline-none">
                <option value="youtube">YouTube 頻道</option>
                <option value="github">GitHub 倉庫/Trending</option>
                <option value="rss">技術 Blog / RSS</option>
              </select>
              <input v-model="newSource.url" type="text" placeholder="URL 網址或頻道連結" class="h-8 rounded-md border border-border bg-input px-2.5 text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none sm:col-span-2">
            </div>
            <div class="mt-2.5 flex justify-end">
              <Button size="sm" :disabled="!newSource.name || !newSource.url" @click="addSource">
                <Plus class="size-3.5" /> 加入追蹤
              </Button>
            </div>
          </div>

          <div v-if="!radar.loaded" class="space-y-2">
            <Skeleton v-for="i in 3" :key="i" class="h-16 w-full rounded-xl" />
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="src in radar.sources"
              :key="src.id"
              class="flex items-center justify-between gap-3 rounded-xl border-0 bg-white/45 p-3 text-xs shadow-sm transition-colors hover:bg-white/70 dark:bg-white/[0.06] dark:hover:bg-white/[0.1]"
            >
              <div class="min-w-0 flex-1">
                <div class="mb-1 flex items-center gap-2">
                  <Badge :class="sourceMeta(src.source_type).badgeClass">{{ src.source_type }}</Badge>
                  <span class="truncate font-semibold text-foreground">{{ src.name }}</span>
                  <span class="font-mono text-2xs text-subtle-foreground">Tier {{ src.tier ?? '—' }}</span>
                </div>
                <div class="flex items-center gap-3 truncate font-mono text-2xs text-subtle-foreground">
                  <span class="max-w-xs truncate">{{ src.url }}</span>
                  <span v-if="(src.hot_hours ?? []).length" class="shrink-0 rounded bg-primary-soft px-1.5 py-px text-primary-soft-foreground">
                    學習時段 {{ (src.hot_hours ?? []).map((h) => h + ':00').join('、') }}
                  </span>
                  <span v-else class="shrink-0">時段分析中…</span>
                </div>
              </div>
              <button
                class="shrink-0 rounded-md p-2 text-subtle-foreground transition-colors hover:bg-danger-soft hover:text-danger"
                title="移除追蹤"
                aria-label="移除追蹤"
                @click="removeSource(src.id)"
              >
                <Trash2 class="size-3.5" />
              </button>
            </div>
          </div>
        </div>

        <!-- Topics -->
        <div v-else-if="tab === 'topics'" class="space-y-1">
          <p class="glass-tint mb-3 rounded-lg p-2.5 text-2xs text-muted-foreground">
            點擊清單項目或閱讀器旁的 ↗ / ↘ 進行信號調諧；被屏蔽之標籤將自動攔截。
          </p>
          <div
            v-for="tp in radar.topics"
            :key="tp.topic_tag"
            class="flex items-center justify-between gap-2 rounded-lg px-2 py-2 font-mono text-xs transition-colors hover:bg-accent/50"
          >
            <div class="flex items-center gap-2.5">
              <span class="font-semibold" :class="tp.is_blocked ? 'text-subtle-foreground line-through' : 'text-foreground'">#{{ tp.topic_tag }}</span>
              <span v-if="tp.is_blocked" class="rounded border border-danger/30 bg-danger-soft px-1.5 py-px text-2xs text-danger">MUTED</span>
              <span v-else-if="tp.weight > 1" class="rounded border border-primary/30 bg-primary-soft px-1.5 py-px text-2xs text-primary-soft-foreground">+{{ (tp.weight - 1).toFixed(1) }}</span>
              <span v-else-if="tp.weight < 1" class="rounded border border-warning/30 bg-warning-soft px-1.5 py-px text-2xs text-warning">{{ (tp.weight - 1).toFixed(1) }}</span>
            </div>
            <div class="flex items-center gap-1">
              <button class="h-6 rounded-md bg-muted px-2 text-2xs text-primary-soft-foreground transition-colors hover:bg-accent" title="增益 +0.5" @click="tuneTopic(tp.topic_tag, 'boost')">↗ 加深</button>
              <button class="h-6 rounded-md bg-muted px-2 text-2xs text-danger transition-colors hover:bg-accent" title="降頻 -1.0" @click="tuneTopic(tp.topic_tag, 'dampen')">↘ 降頻</button>
              <button class="h-6 rounded-md bg-muted px-2 text-2xs text-muted-foreground transition-colors hover:bg-accent" @click="tuneTopic(tp.topic_tag, tp.is_blocked ? 'reset' : 'mute')">
                {{ tp.is_blocked ? '解除' : '靜音' }}
              </button>
            </div>
          </div>
          <p v-if="radar.topics.length === 0" class="py-10 text-center text-xs text-muted-foreground">
            尚無調諧記錄。可於主介面卡片點擊 ↗ / ↘ 或對特定標籤加權。
          </p>
        </div>

        <!-- Digests -->
        <div v-else class="space-y-4">
          <article v-for="dig in radar.digests" :key="dig.id" class="rounded-xl border border-border bg-background-subtle p-4">
            <div class="flex items-center justify-between border-b border-hairline pb-2.5 text-xs">
              <span class="font-bold text-foreground">{{ dig.title }}</span>
              <span class="font-mono text-2xs text-subtle-foreground">{{ formatRelativeTime(dig.created_at) }}</span>
            </div>
            <div class="prose-reader mt-3 max-h-60 overflow-y-auto text-xs" v-html="renderMarkdown(dig.markdown_content)" />
          </article>
          <p v-if="radar.digests.length === 0" class="py-12 text-center text-xs text-muted-foreground">
            尚無焦點戰報。雷達偵測到同一波峰多篇高價值情報時，將自動聚合推播。
          </p>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
