<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import {
  BrainCircuit, Send, BookOpen, ExternalLink,
  Bot, User, Loader2, Cpu,
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
const brainStatus = ref<BrainStatusResponse | null>(null)
const forceCloud = ref(false)

const sampleQuestions = [
  '推薦我知識庫中與 AI Agent 和架構設計相關的內容',
  'Andrej Karpathy 在知識庫中有哪些重點分析？',
  '整理知識庫中討論前後端架構或全端優化的項目',
]

async function loadStatus() {
  try {
    brainStatus.value = await getBrainStatus()
  } catch (err) {
    console.error('Failed to get brain status', err)
  }
}

watch(
  () => ui.showBrainModal,
  (open) => {
    if (open) {
      void loadStatus()
      if (!chatHistory.value.length) {
        // Initial welcome message
        chatHistory.value.push({
          role: 'assistant',
          content: '你好！我是你的 **OmniKeep 知識大腦**。\n我優先用本機 Ollama 模型回答（連不上時改用雲端服務商），並以全庫項目的 **MRL 向量混合檢索 (RRF)** 找出相關收藏。\n你可以問我任何關於你的收藏、筆記或專題研究的深層問題，我會為你整理附帶引用文獻的精確解答。',
        })
      }
      void scrollToBottom()
    }
  }
)

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

  try {
    const historyPayload = chatHistory.value
      .slice(-6, -1)
      .map((c) => ({ role: c.role, content: c.content }))

    const res = await askBrain(q, historyPayload, forceCloud.value)

    chatHistory.value.push({
      role: 'assistant',
      content: res.answer,
      citations: res.citations || [],
      model: res.model,
      provider: res.provider,
    })
  } catch (err) {
    console.error('Ask brain failed', err)
    chatHistory.value.push({
      role: 'assistant',
      content: '很抱歉，大腦問答處理時發生異常，請確認本機服務狀態或稍後重試。',
      provider: 'error',
    })
  } finally {
    loading.value = false
    void scrollToBottom()
  }
}

function clearChat() {
  chatHistory.value = []
  chatHistory.value.push({
    role: 'assistant',
    content: '對話記錄已清空。請輸入任何想向知識大腦提問的主題。',
  })
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
    '<span class="inline-flex items-center justify-center size-4 rounded-full bg-primary/15 text-primary text-3xs font-mono font-bold mx-0.5 align-text-top border border-primary/30 cursor-pointer" title="查看第 $1 筆引用文獻">[$1]</span>'
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
    <DialogContent class="flex h-[88vh] max-w-4xl flex-col overflow-hidden p-0 sm:rounded-2xl">
      <!-- Header -->
      <div class="flex items-center justify-between border-b border-border bg-card/80 px-5 py-3.5 backdrop-blur-md">
        <div class="flex items-center gap-2.5">
          <div class="flex size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
            <BrainCircuit class="size-4.5" />
          </div>
          <div>
            <DialogTitle class="text-sm font-bold tracking-tight text-foreground flex items-center gap-2">
              OmniKeep 對話大腦 (Ask Brain)
              <Badge variant="outline" class="font-mono text-3xs font-normal text-primary border-primary/30">
                GPU 向量檢索 + 深度問答
              </Badge>
            </DialogTitle>
            <DialogDescription class="text-2xs text-muted-foreground flex items-center gap-2 mt-0.5">
              <span>基於全庫項目之 Grounded Citations 引用式問答</span>
            </DialogDescription>
          </div>
        </div>

        <div class="flex items-center gap-2">
          <!-- Acceleration badge -->
          <div
            v-if="brainStatus"
            class="hidden sm:flex items-center gap-1.5 rounded-lg border border-border bg-muted/60 px-2.5 py-1 text-2xs font-medium text-foreground"
            :title="brainStatus.ollama_ready ? '本機推論已就緒' : '本機 Ollama 未連線，會改用雲端服務商'"
          >
            <Cpu class="size-3" :class="brainStatus.ollama_ready ? 'text-green-500' : 'text-muted-foreground'" />
            <span class="font-mono">{{ brainStatus.device_acceleration || brainStatus.configured_model }}</span>
          </div>

          <!-- Clear history -->
          <button
            class="item-action"
            title="清空對話"
            aria-label="清空對話"
            @click="clearChat"
          >
            <RotateCcw class="size-3.5" />
          </button>
        </div>
      </div>

      <!-- Messages Stream -->
      <div
        ref="scrollContainer"
        class="flex-1 space-y-4 overflow-y-auto p-4 sm:p-6 text-xs leading-relaxed"
      >
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
                class="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed"
                v-html="renderGroundedAnswer(msg.content)"
              />

              <!-- Citations Tray -->
              <div
                v-if="msg.citations && msg.citations.length"
                class="mt-4 rounded-xl border border-border/60 bg-muted/30 p-3"
              >
                <div class="mb-2 flex items-center justify-between text-2xs font-semibold text-muted-foreground">
                  <span class="flex items-center gap-1">
                    <BookOpen class="size-3 text-primary" />
                    引用文獻來源（{{ msg.citations.length }} 篇相關收藏）
                  </span>
                </div>

                <div class="space-y-2">
                  <div
                    v-for="cite in msg.citations"
                    :key="cite.citation_index"
                    class="rounded-lg border border-border/40 bg-card/60 p-2 text-2xs transition hover:border-primary/40 hover:bg-card"
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
                        {{ cite.category_name || 'Inbox' }}
                      </Badge>
                    </div>

                    <p v-if="cite.summary" class="mt-1 line-clamp-2 text-muted-foreground">
                      {{ cite.summary }}
                    </p>

                    <div class="mt-1.5 flex items-center justify-between text-3xs text-subtle-foreground font-mono">
                      <span>RRF 分數: {{ cite.rrf_score?.toFixed(4) }}</span>
                      <div class="flex items-center gap-2">
                        <button
                          type="button"
                          class="inline-flex items-center gap-1 text-primary hover:underline cursor-pointer"
                          @click="openItemInReader(cite.id)"
                        >
                          <BookOpen class="size-2.5" /> 檢視
                        </button>
                        <a
                          v-if="cite.url"
                          :href="cite.url"
                          target="_blank"
                          rel="noopener noreferrer"
                          class="inline-flex items-center gap-0.5 text-muted-foreground hover:text-foreground"
                        >
                          連結 <ExternalLink class="size-2.5" />
                        </a>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Meta Footer -->
              <div v-if="msg.provider" class="flex items-center gap-2 text-3xs text-muted-foreground pt-1 border-t border-border/40">
                <span>模型: {{ msg.model || '未知' }}</span>
                <span>•</span>
                <span>推論通道: {{ msg.provider === 'local_ollama_gpu' ? (brainStatus?.device_acceleration ? `本機（${brainStatus.device_acceleration}）` : '本機 Ollama') : '雲端高可用備援' }}</span>
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
            <div class="flex items-center gap-2 text-xs text-muted-foreground font-medium">
              <Loader2 class="size-3.5 animate-spin text-primary" />
              <span>正在透過向量 RRF 檢索全庫項目並深度思考中…</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Sample Prompt Chips (when conversation is fresh) -->
      <div v-if="chatHistory.length <= 1 && !loading" class="px-5 pb-2">
        <p class="text-3xs text-muted-foreground font-semibold mb-1.5">推薦問題：</p>
        <div class="flex flex-wrap gap-1.5">
          <button
            v-for="q in sampleQuestions"
            :key="q"
            class="rounded-lg border border-border bg-muted/40 px-2.5 py-1 text-2xs text-foreground transition hover:border-primary/40 hover:bg-card cursor-pointer"
            @click="sendQuery(q)"
          >
            {{ q }}
          </button>
        </div>
      </div>

      <!-- Input Area -->
      <div class="border-t border-border bg-card p-3 sm:p-4">
        <div class="relative flex items-center rounded-xl border border-border bg-input shadow-sm focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
          <input
            v-model="inputQuery"
            type="text"
            placeholder="向第二大腦提問… (支援全庫混合語意檢索，按 Enter 發送)"
            class="h-11 w-full bg-transparent px-4 pr-12 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none"
            :disabled="loading"
            @keydown="handleKeydown"
          />
          <button
            class="absolute right-2 flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground transition hover:bg-primary-hover disabled:opacity-40 cursor-pointer"
            :disabled="!inputQuery.trim() || loading"
            aria-label="發送問題"
            @click="sendQuery()"
          >
            <Send class="size-3.5" />
          </button>
        </div>

        <div class="mt-2 flex items-center justify-between text-3xs text-muted-foreground px-1">
          <span>支援 Shift + Enter 換行，Enter 發送提問</span>
          <span class="font-mono">EmbeddingGemma-2 (256維 MRL) + Qwen3 / Strata</span>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
