<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import {
  Send, BookOpen, ExternalLink,
  Bot, User, Loader2,
  RotateCcw
} from 'lucide-vue-next'
import { Dialog, DialogContent, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Badge from '@/components/ui/badge/Badge.vue'
import { useUiStore } from '@/stores/ui'
import { renderMarkdown } from '@/lib/markdown'
import { askBrain, getBrainStatus, type BrainCitation, type BrainStatusResponse } from '@/lib/api'

interface ChatEntry {
  role: 'user' | 'assistant'
  content: string
  citations?: BrainCitation[]
  model?: string
  provider?: string
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
)

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
      class="flex h-[88vh] max-w-4xl flex-col overflow-hidden p-0 sm:rounded-2xl"
      show-close
      @open-auto-focus="(e: Event) => { e.preventDefault(); followUp?.focus() }"
    >
      <!-- Header: the question being answered -->
      <div class="flex min-h-14 items-center gap-2 border-b border-hairline py-2 pl-5 pr-14">
        <DialogTitle :class="title ? 'min-w-0 flex-1 truncate text-lg font-semibold leading-[26px] tracking-normal' : 'sr-only'">{{ title || '回答' }}</DialogTitle>
        <DialogDescription class="sr-only">用你收藏的內容回答，並附上引用的收藏。</DialogDescription>
        <button
          v-if="chatHistory.length"
          type="button"
          class="set-button set-button--text ml-auto"
          @click="startOver"
        ><RotateCcw aria-hidden="true" />清空對話</button>
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
                        {{ cite.category_name || '收件匣' }}
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
                          v-if="cite.url"
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
      <div class="border-t border-border bg-card p-3 sm:p-4">
        <div class="relative flex items-center rounded-xl border border-border bg-input shadow-sm focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
          <input
            ref="followUp"
            v-model="inputQuery"
            type="text"
            :placeholder="chatHistory.length ? '接著問' : '問一個和收藏有關的問題'"
            aria-label="問題"
            class="h-11 w-full bg-transparent px-4 pr-12 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            :disabled="loading"
            @keydown="handleKeydown"
          />
          <button
            class="absolute right-2 flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground transition hover:bg-primary-hover disabled:opacity-40 cursor-pointer"
            :disabled="!inputQuery.trim() || loading"
            aria-label="送出問題"
            @click="sendQuery()"
          >
            <Send class="size-3.5" />
          </button>
        </div>

        <div class="mt-2 flex items-center justify-between text-3xs text-muted-foreground px-1">
          <span>按 Enter 送出</span>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
