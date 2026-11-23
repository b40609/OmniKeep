<script setup lang="ts">
import { computed, ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import {
  ArrowLeft, Send, BookOpen, ExternalLink,
  Bot, User, Loader2,
  RotateCcw, TriangleAlert
} from 'lucide-vue-next'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Badge from '@/components/ui/badge/Badge.vue'
import { useUiStore } from '@/stores/ui'
import { renderMarkdown } from '@/lib/markdown'
import { displayCategory } from '@/lib/format'
import { isWebUrl } from '@/lib/originLink'
import { askBrain, getBrainStatus, type BrainCitation, type BrainStatusResponse } from '@/lib/api'

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  citations?: BrainCitation[]
  model?: string
  provider?: string
  /** Set when semantic search took no part in finding the citations. */
  notice?: string
}

const ui = useUiStore()

const inputQuery = ref('')
const loading = ref(false)
const chatHistory = ref<ChatEntry[]>([])
const scrollContainer = ref<HTMLDivElement | null>(null)
const followUp = ref<HTMLInputElement | null>(null)
const brainStatus = ref<BrainStatusResponse | null>(null)
const forceCloud = ref(false)

/** Goes up when a new conversation starts, so an answer to the old one is dropped. */
let conversation = 0

/** The dialog is named after the question it is answering, not after a feature. */
const title = computed(() => chatHistory.value.find((entry) => entry.role === 'user')?.content ?? '')

async function loadStatus() {
  try {
    brainStatus.value = await getBrainStatus()
  } catch (err) {
    console.error('Failed to get brain status', err)
  }
}

// A question picked in the search box arrives through the store: it starts a new
// conversation and is sent at once. Follow-up questions are typed in the dialog.
watch(
  () => [ui.showBrainModal, ui.pendingQuestion] as const,
  ([open, question]) => {
    if (!open) return
    void loadStatus()
    if (question) {
      ui.pendingQuestion = ''
      startOver()
      void sendQuery(question)
    }
    void scrollToBottom()
  },
  { immediate: true },
)

let inHistory = false
function closeDialog() {
  ui.showBrainModal = false
}
function onPopState() {
  if (!inHistory) return
  inHistory = false
  ui.showBrainModal = false
}
onMounted(() => {
  if (typeof window !== 'undefined' && typeof window.history?.pushState === 'function') {
    window.history.pushState({ ...(window.history.state || {}), omnikeepBrain: true }, '')
    inHistory = true
    window.addEventListener?.('popstate', onPopState)
  }
})
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener?.('popstate', onPopState)
    if (inHistory && window.history?.state?.omnikeepBrain) {
      inHistory = false
      window.history.back()
    }
  }
})

function startOver() {
  conversation++
  chatHistory.value = []
  loading.value = false
}

async function scrollToBottom() {
  await nextTick()
  if (scrollContainer.value) {
    scrollContainer.value.scrollTop = scrollContainer.value.scrollHeight
  }
}

async function sendQuery(text?: string) {
  const q = (text || inputQuery.value).trim()
  if (!q || loading.value) return

  inputQuery.value = ''
  // Push user turn
  chatHistory.value.push({
    role: 'user',
    content: q,
  })
  loading.value = true
  void scrollToBottom()
  const asked = conversation

  try {
    const historyPayload = chatHistory.value
      .slice(-6, -1)
      .map((c) => ({ role: c.role, content: c.content }))

    const res = await askBrain(q, historyPayload, forceCloud.value)
    if (asked !== conversation) return

    chatHistory.value.push({
      role: 'assistant',
      content: res.answer,
      citations: res.citations || [],
      model: res.model,
      provider: res.provider,
      notice: res.notice || '',
    })
  } catch (err) {
    console.error('Ask brain failed', err)
    if (asked !== conversation) return
    chatHistory.value.push({
      role: 'assistant',
      content: '這次沒有回答成功。請確認 AI 連線正常後再試一次。',
      provider: 'error',
    })
  } finally {
    if (asked === conversation) {
      loading.value = false
      void scrollToBottom()
      // The field is disabled while waiting, so it could not take the focus when the dialog opened.
      void nextTick(() => ui.showBrainModal && followUp.value?.focus())
    }
  }
}

function openItemInReader(itemId: string | number) {
  ui.showBrainModal = false
  // Set active item via ID (trigger fetch or lookup)
  window.dispatchEvent(new CustomEvent('open-item', { detail: { itemId: String(itemId) } }))
}

function renderGroundedAnswer(markdown: string) {
  // Convert [1], [2] citation markers into styled badges
  let parsed = renderMarkdown(markdown)
  parsed = parsed.replace(
    /\[(\d+)\]/g,
    '<span class="inline-flex items-center justify-center size-4 rounded-full bg-primary/15 text-primary text-3xs font-mono font-bold mx-0.5 align-text-top border border-primary/30 cursor-pointer" title="第 $1 則引用">[$1]</span>'
  )
  return parsed
}

function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    void sendQuery()
  }
}
</script>

<template>
  <Dialog :open="ui.showBrainModal" @update:open="(v) => (ui.showBrainModal = v)">
    <DialogContent
      class="flex h-[100dvh] max-h-[100dvh] w-screen max-w-none flex-col overflow-hidden rounded-none border-0 p-0 sm:h-[88dvh] sm:max-h-[88dvh] sm:w-full sm:max-w-4xl sm:rounded-2xl sm:border"
      show-close
      @open-auto-focus="(e: Event) => { e.preventDefault(); followUp?.focus() }"
    >
      <!-- Header: the question being answered (mobile gets an explicit back arrow in safe-top) -->
      <div class="safe-top flex min-h-14 shrink-0 items-center gap-2 border-b border-hairline px-2 py-2 sm:pl-5 sm:pr-14">
        <button
          type="button"
          class="item-action sm:hidden"
          aria-label="返回清單"
          title="返回"
          @click="closeDialog"
        ><ArrowLeft class="size-5" /></button>
        <DialogTitle :class="title ? 'min-w-0 flex-1 truncate pr-10 text-base font-semibold leading-[22px] tracking-normal sm:pr-0 sm:text-lg sm:leading-[26px]' : 'min-w-0 flex-1 text-base font-semibold sm:sr-only'">{{ title || '提問' }}</DialogTitle>
        <DialogDescription class="sr-only">用你收藏的內容回答，並附上引用的收藏。</DialogDescription>
        <button
          v-if="chatHistory.length"
          type="button"
          class="set-button set-button--text ml-auto mr-10 sm:mr-0"
          @click="startOver"
        ><RotateCcw aria-hidden="true" /><span class="max-sm:hidden">清空對話</span></button>
      </div>

      <!-- Messages Stream -->
      <div
        ref="scrollContainer"
        class="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6 text-sm leading-relaxed"
      >
        <!-- Nothing asked yet (the conversation was cleared) -->
        <p v-if="!chatHistory.length && !loading" class="px-1 py-8 text-center text-sm text-muted-foreground">
          在下面輸入問題，會用你收藏的內容回答，並附上引用的收藏。
        </p>
        <div
          v-for="(msg, idx) in chatHistory"
          :key="idx"
          class="flex gap-3"
          :class="msg.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <!-- Assistant Avatar -->
          <div
            v-if="msg.role === 'assistant'"
            class="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary mt-0.5"
          >
            <Bot class="size-4" />
          </div>

          <!-- Content Bubble -->
          <div
            class="max-w-[85%] rounded-2xl p-4 sm:max-w-[78%]"
            :class="[
              msg.role === 'user'
                ? 'bg-primary text-primary-foreground font-medium rounded-tr-sm ml-10'
                : 'border border-border/70 bg-card text-foreground shadow-sm rounded-tl-sm mr-6',
            ]"
          >
            <!-- User text -->
            <div v-if="msg.role === 'user'" class="whitespace-pre-wrap leading-relaxed text-sm">
              {{ msg.content }}
            </div>

            <!-- Assistant Markdown & Grounded Citations -->
            <div v-else class="space-y-3">
              <!-- Semantic search was left out: said before the answer, which rests on keywords only -->
              <div
                v-if="msg.notice"
                role="status"
                class="flex items-start gap-2 rounded-lg border border-warning/30 bg-warning/10 px-3 py-2 text-xs leading-relaxed text-foreground"
              >
                <TriangleAlert class="mt-0.5 size-4 shrink-0 text-warning" />
                <span>{{ msg.notice }}</span>
              </div>
              <div
                class="prose prose-sm dark:prose-invert max-w-none text-sm leading-relaxed"
                v-html="renderGroundedAnswer(msg.content)"
              />

              <!-- Citations Tray -->
              <div
                v-if="msg.citations && msg.citations.length"
                class="mt-4 rounded-xl border border-border/60 bg-muted/30 p-3"
              >
                <div class="mb-2 flex items-center justify-between text-sm font-semibold text-muted-foreground">
                  <span class="flex items-center gap-1">
                    <BookOpen class="size-3 text-primary" />
                    引用的收藏（{{ msg.citations.length }} 則）
                  </span>
                </div>

                <div class="space-y-2">
                  <div
                    v-for="cite in msg.citations"
                    :key="cite.citation_index"
                    class="rounded-lg border border-border/40 bg-card/60 p-2 text-sm transition hover:border-primary/40 hover:bg-card"
                  >
                    <div class="flex items-start justify-between gap-2">
                      <div class="flex items-center gap-1.5 min-w-0">
                        <span class="flex size-4 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground font-mono text-3xs font-bold">
                          {{ cite.citation_index }}
                        </span>
                        <span class="truncate font-bold text-foreground">
                          {{ cite.title }}
                        </span>
                      </div>
                      <Badge variant="outline" class="shrink-0 text-3xs font-mono">
                        {{ displayCategory(cite.category_name) }}
                      </Badge>
                    </div>

                    <p v-if="cite.summary" class="mt-1 line-clamp-2 text-muted-foreground">
                      {{ cite.summary }}
                    </p>

                    <div class="mt-1.5 flex items-center justify-between text-3xs text-subtle-foreground font-mono">
                      <span>相關分數 {{ cite.rrf_score?.toFixed(4) }}</span>
                      <div class="flex items-center gap-2">
                        <button
                          type="button"
                          class="inline-flex items-center gap-1 text-primary hover:underline cursor-pointer"
                          @click="openItemInReader(cite.id)"
                        >
                          <BookOpen class="size-2.5" /> 開啟
                        </button>
                        <a
                          v-if="isWebUrl(cite.url)"
                          :href="cite.url"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="inline-flex items-center gap-0.5 text-muted-foreground hover:text-foreground"
                        >
                          原文 <ExternalLink class="size-2.5" />
                        </a>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Meta Footer -->
              <div v-if="msg.provider && msg.provider !== 'retrieval_only' && msg.provider !== 'error'" class="flex items-center gap-2 text-3xs text-muted-foreground pt-1 border-t border-border/40">
                <span>模型：{{ msg.model || '未知' }}</span>
                <span>·</span>
                <span>來源：{{ msg.provider === 'local_ollama_gpu' ? (brainStatus?.device_acceleration ? `本機（${brainStatus.device_acceleration}）` : '本機 Ollama') : '雲端 AI 連線' }}</span>
              </div>
            </div>
          </div>

          <!-- User Avatar -->
          <div
            v-if="msg.role === 'user'"
            class="flex size-7 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground mt-0.5"
          >
            <User class="size-4" />
          </div>
        </div>

        <!-- Loading indicator -->
        <div v-if="loading" class="flex gap-3 justify-start">
          <div class="flex size-7 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary mt-0.5">
            <Bot class="size-4" />
          </div>
          <div class="rounded-2xl rounded-tl-sm border border-border/70 bg-card p-4 text-foreground shadow-sm">
            <div class="flex items-center gap-2 text-sm text-muted-foreground font-medium">
              <Loader2 class="size-3.5 animate-spin text-primary" />
              <span>正在找相關的收藏並整理回答…</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Input Area -->
      <div class="safe-bottom shrink-0 border-t border-border bg-card p-3 sm:p-4">
        <div class="relative flex items-center rounded-xl border border-border bg-input shadow-sm focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
          <input
            ref="followUp"
            v-model="inputQuery"
            type="text"
            :placeholder="chatHistory.length ? '接著問' : '問一個和收藏有關的問題'"
            aria-label="問題"
            class="h-11 w-full bg-transparent px-4 pr-12 text-base text-foreground placeholder:text-muted-foreground focus:outline-none sm:text-sm"
            :disabled="loading"
            @keydown="handleKeydown"
          />
          <button
            class="absolute right-2 flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground transition hover:bg-primary-hover disabled:opacity-40 cursor-pointer sm:size-8"
            :disabled="!inputQuery.trim() || loading"
            aria-label="送出問題"
            @click="sendQuery()"
          >
            <Send class="size-4 sm:size-3.5" />
          </button>
        </div>

        <div class="mt-2 hidden items-center justify-between px-1 text-3xs text-muted-foreground sm:flex">
          <span>按 Enter 送出</span>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
