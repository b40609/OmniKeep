<script setup lang="ts">
import { ref, watch } from 'vue'
import {
  Radar,
  Loader2,
  Plus,
  Trash2,
  Sparkles,
  Sliders,
  Check,
  X,
  RefreshCw,
  FlaskConical,
  ArrowRight,
  ShieldCheck,
  Tag,
  Folder,
  Star,
  Archive,
  VolumeX,
  Bell,
  BellOff,
  Clock,
  Save,
  Pause,
  Play,
} from 'lucide-vue-next'
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

type RadarTab = 'settings' | 'sources' | 'topics' | 'digests' | 'dreampass' | 'rules'
const tab = ref<RadarTab>('settings')

// ---------------- Radar Settings & Schedule ----------------
const isSavingSettings = ref(false)
const scheduleSettings = ref<api.RadarSettings>({
  enabled: true,
  interval_minutes: 180,
  max_analyze_per_cycle: 3,
  notification_mode: 'silent',
  daily_digest_hour: 8,
  vip_threshold: 4.0,
})

watch(
  () => radar.settings,
  (st) => {
    if (st) {
      scheduleSettings.value = { ...st }
    }
  },
  { immediate: true }
)

async function handleSaveSettings() {
  isSavingSettings.value = true
  try {
    await radar.updateSettings(scheduleSettings.value)
    toast.success('排程與推播設定已儲存更新')
  } catch (e) {
    toast.error('儲存設定失敗', { description: (e as Error).message })
  } finally {
    isSavingSettings.value = false
  }
}

async function handleToggleSource(src: api.RadarSource) {
  try {
    const nextActive = src.is_active === 0 ? true : false
    await radar.toggleSource(src.id, nextActive)
    toast.success(nextActive ? `已啟用來源「${src.name}」` : `已暫停來源「${src.name}」`)
  } catch (e) {
    toast.error('切換來源失敗', { description: (e as Error).message })
  }
}
const isScanning = ref(false)

// Sources
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

// ---------------- Dream Pass & Profile ----------------
const profileText = ref('')
const profileUpdatedAt = ref<string | null>(null)
const isProfileLoading = ref(false)
const isProfileSaving = ref(false)
const dreamPassProposal = ref<api.DreamPassProposal | null>(null)
const isDreamPassRunning = ref(false)
const isDreamPassApplying = ref(false)

async function loadProfileAndDreamPass() {
  isProfileLoading.value = true
  try {
    const [pRes, dpRes] = await Promise.all([
      api.getInterestProfile(),
      api.getLatestDreamPass(),
    ])
    profileText.value = pRes.profile || ''
    profileUpdatedAt.value = pRes.updated_at || null
    dreamPassProposal.value = dpRes.proposal
  } catch (e) {
    toast.error('載入畫像或提案失敗', { description: (e as Error).message })
  } finally {
    isProfileLoading.value = false
  }
}

async function saveProfile() {
  isProfileSaving.value = true
  try {
    const res = await api.updateInterestProfile(profileText.value)
    profileUpdatedAt.value = res.updated_at || null
    toast.success('品味畫像已儲存更新')
  } catch (e) {
    toast.error('儲存畫像失敗', { description: (e as Error).message })
  } finally {
    isProfileSaving.value = false
  }
}

async function triggerDreamPass() {
  isDreamPassRunning.value = true
  const t = toast.loading('正在深度聚合近 7 天品味訊號與啟發式自省…')
  try {
    const res = await api.runDreamPass(7)
    dreamPassProposal.value = res.proposal
    toast.success('Dream Pass 自省完成，已生成畫像修訂提案！', { id: t })
  } catch (e) {
    toast.error('自省執行失敗', { id: t, description: (e as Error).message })
  } finally {
    isDreamPassRunning.value = false
  }
}

async function handleApplyDreamPass(id: number) {
  isDreamPassApplying.value = true
  try {
    const res = await api.applyDreamPass(id)
    profileText.value = res.profile
    if (dreamPassProposal.value && dreamPassProposal.value.id === id) {
      dreamPassProposal.value.status = 'applied'
    }
    toast.success('已一鍵採用自省建議，畫像已同步更新')
  } catch (e) {
    toast.error('採用失敗', { description: (e as Error).message })
  } finally {
    isDreamPassApplying.value = false
  }
}

async function handleDismissDreamPass(id: number) {
  try {
    await api.dismissDreamPass(id)
    if (dreamPassProposal.value && dreamPassProposal.value.id === id) {
      dreamPassProposal.value.status = 'dismissed'
    }
    toast.info('已忽略此自省提案')
  } catch (e) {
    toast.error('操作失敗', { description: (e as Error).message })
  }
}

// ---------------- Hard Rules Engine ----------------
const rules = ref<api.HardRule[]>([])
const isRulesLoading = ref(false)
const newRule = ref<Partial<api.HardRule>>({
  name: '',
  field: 'domain',
  operator: 'contains',
  value: '',
  action_type: 'add_tag',
  action_value: '',
  priority: 0,
  is_active: 1,
})
const isCreatingRule = ref(false)

const showRuleSandbox = ref(false)
const testSample = ref({
  title: 'GitHub release of rust-lang/rust v1.85',
  url: 'https://github.com/rust-lang/rust/releases',
  source_type: 'github',
  content: 'New features and stabilization notes...',
})
const testResult = ref<{
  matched_rules: string[]
  changes: Record<string, { before: unknown; after: unknown }>
  result_item: Record<string, unknown>
} | null>(null)
const isTestingRule = ref(false)

async function loadRules() {
  isRulesLoading.value = true
  try {
    rules.value = await api.getRules()
  } catch (e) {
    toast.error('載入硬規則失敗', { description: (e as Error).message })
  } finally {
    isRulesLoading.value = false
  }
}

async function handleCreateRule() {
  if (!newRule.value.name || !newRule.value.value) {
    toast.error('請填寫規則名稱與比對值')
    return
  }
  isCreatingRule.value = true
  try {
    const res = await api.createRule(newRule.value)
    toast.success(`規則「${res.rule.name}」已建立`)
    newRule.value = {
      name: '',
      field: 'domain',
      operator: 'contains',
      value: '',
      action_type: 'add_tag',
      action_value: '',
      priority: 0,
      is_active: 1,
    }
    await loadRules()
  } catch (e) {
    toast.error('建立規則失敗', { description: (e as Error).message })
  } finally {
    isCreatingRule.value = false
  }
}

async function handleToggleRule(rule: api.HardRule) {
  const nextActive = rule.is_active ? 0 : 1
  try {
    await api.updateRule(rule.id, { is_active: nextActive })
    rule.is_active = nextActive
    toast.success(nextActive ? `已啟用「${rule.name}」` : `已停用「${rule.name}」`)
  } catch (e) {
    toast.error('更新規則狀態失敗', { description: (e as Error).message })
  }
}

async function handleDeleteRule(id: number, name: string) {
  try {
    await api.deleteRule(id)
    rules.value = rules.value.filter(r => r.id !== id)
    toast.success(`已刪除規則「${name}」`)
  } catch (e) {
    toast.error('刪除規則失敗', { description: (e as Error).message })
  }
}

async function runRuleTest() {
  isTestingRule.value = true
  try {
    const res = await api.testRule(testSample.value)
    testResult.value = res
    if (res.matched_rules.length === 0) {
      toast.info('測試樣本未匹配任何有效硬規則')
    } else {
      toast.success(`命中 ${res.matched_rules.length} 條規則！`)
    }
  } catch (e) {
    toast.error('測試失敗', { description: (e as Error).message })
  } finally {
    isTestingRule.value = false
  }
}

function actionIcon(action: string) {
  switch (action) {
    case 'add_tag': return Tag
    case 'set_category': return Folder
    case 'star': return Star
    case 'archive': return Archive
    case 'mute': return VolumeX
    default: return ShieldCheck
  }
}

// Watch tab switches to load data on-demand
watch(tab, (t) => {
  if (t === 'dreampass' && !profileText.value && !isProfileLoading.value) {
    loadProfileAndDreamPass()
  } else if (t === 'rules' && rules.value.length === 0 && !isRulesLoading.value) {
    loadRules()
  }
})
</script>

<template>
  <Dialog :open="ui.showRadarModal" @update:open="(v) => (ui.showRadarModal = v)">
    <DialogContent class="flex max-h-[90vh] max-w-3xl flex-col gap-0 p-0 overflow-hidden">
      <!-- Header -->
      <div class="flex shrink-0 items-center justify-between border-b border-border p-5 pb-4">
        <div class="flex items-center gap-2.5">
          <div class="flex size-9 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Radar class="size-4.5" />
          </div>
          <DialogHeader>
            <DialogTitle class="flex items-center gap-2">
              自動訂閱排程與監控中心 (Radar Engine)
              <span class="rounded border border-primary/30 bg-primary-soft px-1.5 py-px font-mono text-2xs text-primary-soft-foreground">ADAPTIVE RADAR</span>
            </DialogTitle>
            <DialogDescription>自適應排程 · Google News · 網頁監控 · Dream Pass 自省 · 0 Token 確定性規則</DialogDescription>
          </DialogHeader>
        </div>
        <Button :disabled="isScanning" @click="scan">
          <Loader2 v-if="isScanning" class="size-3.5 animate-spin" />
          {{ isScanning ? '巡檢中…' : '立即巡檢' }}
        </Button>
      </div>

      <!-- Tabs -->
      <div class="flex shrink-0 items-center gap-1 border-b border-border px-5 text-xs overflow-x-auto" role="tablist">
        <button
          v-for="t in [
            { id: 'settings', label: '排程與推播' },
            { id: 'sources', label: `訂閱來源 (${radar.sources.length})` },
            { id: 'topics', label: `主題偏好 (${radar.topics.length})` },
            { id: 'digests', label: `戰報彙整 (${radar.digests.length})` },
            { id: 'dreampass', label: '興趣畫像' },
            { id: 'rules', label: `自動化規則 (${rules.length || '•'})` },
          ]"
          :key="t.id" 
          role="tab"
          :aria-selected="tab === t.id"
          class="relative flex h-10 shrink-0 items-center px-3 font-medium transition-colors"
          :class="tab === t.id ? 'text-primary-soft-foreground' : 'text-muted-foreground hover:text-foreground'"
          @click="tab = t.id as RadarTab"
        >
          {{ t.label }}
          <span v-if="tab === t.id" class="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-primary" />
        </button>
      </div>

      <!-- Panels -->
      <div class="min-h-0 flex-1 overflow-y-auto p-5">
        <!-- Settings Panel -->
        <div v-if="tab === 'settings'" class="space-y-4">
          <!-- Background Polling Switch Card -->
          <div class="glass-tint rounded-xl p-4 flex items-center justify-between gap-4">
            <div class="space-y-0.5">
              <div class="flex items-center gap-2">
                <Clock class="size-4 text-primary" />
                <span class="text-sm font-semibold text-foreground">背景自動巡檢排程</span>
              </div>
              <p class="text-2xs text-muted-foreground">
                開啟後系統將在背景依照設定間隔週期自動探測來源更新。關閉時僅在點擊「立即巡檢」時觸發。
              </p>
            </div>
            <button
              type="button"
              role="switch"
              :aria-checked="scheduleSettings.enabled"
              class="relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none"
              :class="scheduleSettings.enabled ? 'bg-primary' : 'bg-muted-foreground/30'"
              @click="scheduleSettings.enabled = !scheduleSettings.enabled"
            >
              <span
                class="pointer-events-none inline-block size-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out"
                :class="scheduleSettings.enabled ? 'translate-x-5' : 'translate-x-0'"
              />
            </button>
          </div>

          <!-- Interval & Budget -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <!-- Interval -->
            <div class="glass-tint rounded-xl p-3.5 space-y-2">
              <label class="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <RefreshCw class="size-3.5 text-muted-foreground" />
                巡檢週期頻率
              </label>
              <select
                v-model.number="scheduleSettings.interval_minutes"
                :disabled="!scheduleSettings.enabled"
                class="w-full h-8.5 rounded-md border border-border bg-input px-2.5 text-xs text-foreground focus:border-primary focus:outline-none disabled:opacity-50"
              >
                <option :value="0">手動巡檢（不排程）</option>
                <option :value="60">每 1 小時</option>
                <option :value="180">每 3 小時（預設推薦）</option>
                <option :value="360">每 6 小時</option>
                <option :value="720">每 12 小時</option>
                <option :value="1440">每 24 小時（每日一次）</option>
              </select>
              <p class="text-3xs text-subtle-foreground">
                自適應演算法會在非熱門更新時段主動退避，兼顧及時性與系統節能。
              </p>
            </div>

            <!-- Budget Cap -->
            <div class="glass-tint rounded-xl p-3.5 space-y-2">
              <div class="flex items-center justify-between">
                <label class="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <Sliders class="size-3.5 text-muted-foreground" />
                  單輪 AI 分析上限
                </label>
                <span class="font-mono text-xs font-bold text-primary">{{ scheduleSettings.max_analyze_per_cycle }} 篇</span>
              </div>
              <input
                v-model.number="scheduleSettings.max_analyze_per_cycle"
                type="range"
                min="1"
                max="10"
                step="1"
                class="w-full accent-primary h-2 bg-muted rounded-lg cursor-pointer mt-1"
              >
              <p class="text-3xs text-subtle-foreground">
                超額候選文章將延後暫存為待分析 stub，分攤至後續輪次，避免消耗過多額度。
              </p>
            </div>
          </div>

          <!-- Telegram Notification Policy -->
          <div class="glass-tint rounded-xl p-3.5 space-y-3">
            <div class="flex items-center justify-between">
              <label class="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Bell class="size-3.5 text-muted-foreground" />
                Telegram 推播策略
              </label>
              <span class="text-3xs text-muted-foreground font-mono">
                當前模式：{{ scheduleSettings.notification_mode === 'silent' ? '完全靜音' : scheduleSettings.notification_mode === 'daily_digest' ? '每日戰報' : 'VIP警戒' }}
              </span>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
              <!-- Silent Option -->
              <div
                class="cursor-pointer rounded-lg border p-3 transition-all"
                :class="scheduleSettings.notification_mode === 'silent' ? 'border-primary bg-primary/5 text-foreground shadow-sm' : 'border-border/60 hover:border-border text-muted-foreground'"
                @click="scheduleSettings.notification_mode = 'silent'"
              >
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-xs font-semibold flex items-center gap-1.5 text-foreground">
                    <BellOff class="size-3.5 text-muted-foreground" />
                    完全靜音入庫
                  </span>
                  <span class="text-3xs rounded px-1.5 py-0.5 bg-primary/10 text-primary font-mono">推薦</span>
                </div>
                <p class="text-3xs leading-relaxed">
                  巡檢與 AI 分析正常入庫，完全不推播 Telegram 訊息，消除通知疲勞。
                </p>
              </div>

              <!-- Daily Digest Option -->
              <div
                class="cursor-pointer rounded-lg border p-3 transition-all"
                :class="scheduleSettings.notification_mode === 'daily_digest' ? 'border-primary bg-primary/5 text-foreground shadow-sm' : 'border-border/60 hover:border-border text-muted-foreground'"
                @click="scheduleSettings.notification_mode = 'daily_digest'"
              >
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-xs font-semibold flex items-center gap-1.5 text-foreground">
                    <Clock class="size-3.5 text-muted-foreground" />
                    每日定時戰報
                  </span>
                </div>
                <p class="text-3xs leading-relaxed">
                  每天於指定時段彙整當日精華，發送單則彙整，不零散干擾。
                </p>
              </div>

              <!-- VIP Alert Option -->
              <div
                class="cursor-pointer rounded-lg border p-3 transition-all"
                :class="scheduleSettings.notification_mode === 'vip_alert' ? 'border-primary bg-primary/5 text-foreground shadow-sm' : 'border-border/60 hover:border-border text-muted-foreground'"
                @click="scheduleSettings.notification_mode = 'vip_alert'"
              >
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-xs font-semibold flex items-center gap-1.5 text-foreground">
                    <Star class="size-3.5 text-amber-500" />
                    重大警戒推播
                  </span>
                </div>
                <p class="text-3xs leading-relaxed">
                  平時完全靜默，僅在命中高分星標情報時立即推播。
                </p>
              </div>
            </div>

            <!-- Conditional sub-settings for daily_digest -->
            <div v-if="scheduleSettings.notification_mode === 'daily_digest'" class="pt-2 border-t border-border/50 flex items-center justify-between text-xs">
              <span class="text-muted-foreground text-2xs">每日戰報發送時段：</span>
              <select
                v-model.number="scheduleSettings.daily_digest_hour"
                class="h-7 rounded border border-border bg-input px-2 text-2xs text-foreground focus:border-primary focus:outline-none"
              >
                <option v-for="h in 24" :key="h-1" :value="h-1">
                  {{ String(h-1).padStart(2, '0') }}:00（{{ h-1 < 12 ? '上午' : '下午' }}）
                </option>
              </select>
            </div>

            <!-- Conditional sub-settings for vip_alert -->
            <div v-if="scheduleSettings.notification_mode === 'vip_alert'" class="pt-2 border-t border-border/50 flex items-center justify-between text-xs">
              <span class="text-muted-foreground text-2xs">推播評分門檻：</span>
              <div class="flex items-center gap-2">
                <input
                  v-model.number="scheduleSettings.vip_threshold"
                  type="range"
                  min="3.0"
                  max="5.0"
                  step="0.5"
                  class="w-24 accent-primary h-1.5 bg-muted rounded cursor-pointer"
                >
                <span class="font-mono text-xs font-semibold text-primary">>= {{ scheduleSettings.vip_threshold.toFixed(1) }}</span>
              </div>
            </div>
          </div>

          <!-- Save Button Bar -->
          <div class="flex items-center justify-between pt-1">
            <span v-if="scheduleSettings.updated_at" class="text-3xs text-subtle-foreground font-mono">
              上次更新：{{ scheduleSettings.updated_at.slice(0, 19).replace('T', ' ') }}
            </span>
            <span v-else />
            <Button size="sm" :disabled="isSavingSettings" @click="handleSaveSettings">
              <Loader2 v-if="isSavingSettings" class="size-3.5 animate-spin" />
              <Save v-else class="size-3.5" />
              儲存排程設定
            </Button>
          </div>
        </div>

        <!-- Sources -->
        <div v-if="tab === 'sources'" class="space-y-4">
          <div class="glass-tint rounded-xl p-3.5">
            <p class="mb-2.5 text-xs font-semibold text-foreground">新增自動追蹤來源</p>
            <div class="grid grid-cols-1 gap-2 text-xs sm:grid-cols-4">
              <input v-model="newSource.name" type="text" placeholder="名稱（如：Anthropic Claude Blog）" class="h-8 rounded-md border border-border bg-input px-2.5 text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none">
              <select v-model="newSource.source_type" class="h-8 rounded-md border border-border bg-input px-2 text-xs text-foreground focus:border-primary focus:outline-none">
                <option value="youtube">YouTube 頻道</option>
                <option value="github">GitHub 倉庫/Trending</option>
                <option value="rss">技術 Blog / RSS</option>
                <option value="google_news">Google 新聞 (關鍵字)</option>
                <option value="web_change">網頁異動監控 (Changelog)</option>
              </select>
              <input
                v-model="newSource.url"
                type="text"
                :placeholder="newSource.source_type === 'google_news' ? '關鍵字（如：DeepSeek R1 或 URL）' : newSource.source_type === 'web_change' ? '要監控的網址（如：https://...）' : 'URL 網址或頻道連結'"
                class="h-8 rounded-md border border-border bg-input px-2.5 text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none sm:col-span-2"
              >
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
              class="flex items-center justify-between gap-3 rounded-xl border-0 p-3 text-xs shadow-sm transition-all"
              :class="src.is_active === 0
                ? 'bg-muted/30 opacity-60 dark:bg-white/[0.02]'
                : 'bg-white/45 hover:bg-white/70 dark:bg-white/[0.06] dark:hover:bg-white/[0.1]'"
            >
              <div class="min-w-0 flex-1">
                <div class="mb-1 flex items-center gap-2">
                  <Badge :class="sourceMeta(src.source_type).badgeClass">{{ sourceMeta(src.source_type).label }}</Badge>
                  <span class="truncate font-semibold text-foreground">{{ src.name }}</span>
                  <span v-if="src.is_active === 0" class="rounded bg-muted px-1.5 py-px text-2xs text-muted-foreground font-mono">已暫停</span>
                  <span v-else class="rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-1.5 py-px text-2xs font-mono">運行中</span>
                  <span class="font-mono text-2xs text-subtle-foreground">Tier {{ src.tier ?? '—' }}</span>
                </div>
                <div class="flex items-center gap-3 truncate font-mono text-2xs text-subtle-foreground">
                  <span class="max-w-xs truncate">{{ src.url }}</span>
                  <span v-if="(src.hot_hours ?? []).length" class="shrink-0 rounded bg-primary-soft px-1.5 py-px text-primary-soft-foreground">
                    學習時段 {{ (src.hot_hours ?? []).map((h) => h + ':00').join('、') }}
                  </span>
                  <span v-else class="shrink-0">時段學習中</span>
                </div>
              </div>
              <div class="flex items-center gap-1 shrink-0">
                <button
                  class="rounded-md p-2 transition-colors"
                  :class="src.is_active === 0
                    ? 'text-primary hover:bg-primary-soft'
                    : 'text-subtle-foreground hover:bg-muted hover:text-foreground'"
                  :title="src.is_active === 0 ? '恢復自動巡檢' : '暫停此來源'"
                  :aria-label="src.is_active === 0 ? '恢復' : '暫停'"
                  @click="handleToggleSource(src)"
                >
                  <Play v-if="src.is_active === 0" class="size-3.5" />
                  <Pause v-else class="size-3.5" />
                </button>
                <button
                  class="rounded-md p-2 text-subtle-foreground transition-colors hover:bg-danger-soft hover:text-danger"
                  title="刪除來源"
                  aria-label="刪除來源"
                  @click="removeSource(src.id)"
                >
                  <Trash2 class="size-3.5" />
                </button>
              </div>
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
        <div v-else-if="tab === 'digests'" class="space-y-4">
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

        <!-- Dream Pass: 品味自省畫像 -->
        <div v-else-if="tab === 'dreampass'" class="space-y-4">
          <!-- 當前品味畫像卡片 -->
          <div class="glass-tint rounded-xl border border-border/50 p-4">
            <div class="mb-2 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Sparkles class="size-4 text-primary" />
                <span class="text-xs font-semibold text-foreground">目前品味畫像 (User Interest Profile)</span>
                <span v-if="profileUpdatedAt" class="font-mono text-2xs text-subtle-foreground">
                  最後更新：{{ formatRelativeTime(profileUpdatedAt) }}
                </span>
              </div>
              <div class="flex items-center gap-2">
                <Button size="sm" variant="outline" :disabled="isProfileSaving" @click="saveProfile">
                  <Loader2 v-if="isProfileSaving" class="size-3 animate-spin" />
                  儲存畫像
                </Button>
                <Button size="sm" :disabled="isDreamPassRunning" @click="triggerDreamPass">
                  <RefreshCw v-if="!isDreamPassRunning" class="size-3" />
                  <Loader2 v-else class="size-3 animate-spin" />
                  {{ isDreamPassRunning ? '自省中…' : '執行 7 天自省' }}
                </Button>
              </div>
            </div>
            <p class="mb-2 text-2xs text-muted-foreground">
              前移 AI 成本閘門依據此段品味定義計算相關度；當情報價值 >= 2.5 即自動精選入庫。
            </p>
            <textarea
              v-model="profileText"
              rows="3"
              placeholder="例如：專注 Rust / AI Agent / 金融高頻量化架構 / 工業自動化；排除娛樂炒作..."
              class="w-full rounded-lg border border-border bg-input p-2.5 font-mono text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
            />
          </div>

          <!-- Dream Pass 最新自省卡 -->
          <div v-if="dreamPassProposal" class="rounded-xl border border-primary/20 bg-primary-soft/10 p-4">
            <div class="mb-3 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Sliders class="size-4 text-primary" />
                <span class="text-xs font-bold text-foreground">Dream Pass 品味自省建議提案</span>
                <Badge
                  :class="dreamPassProposal.status === 'applied' ? 'bg-success-soft text-success' : dreamPassProposal.status === 'dismissed' ? 'bg-muted text-muted-foreground' : 'bg-warning-soft text-warning'"
                >
                  {{ dreamPassProposal.status === 'applied' ? '已採用' : dreamPassProposal.status === 'dismissed' ? '已忽略' : '待審查' }}
                </Badge>
              </div>
              <span class="font-mono text-2xs text-subtle-foreground">
                {{ formatRelativeTime(dreamPassProposal.created_at) }}
              </span>
            </div>

            <!-- 觀察理由 -->
            <div class="mb-3 rounded-lg bg-background/60 p-3 text-xs">
              <div class="mb-1 font-semibold text-foreground">品味行為觀察分析：</div>
              <div class="text-muted-foreground leading-relaxed">{{ dreamPassProposal.observations }}</div>
            </div>

            <!-- 建議演進差異對比 -->
            <div class="mb-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
              <div class="rounded-lg border border-border/50 bg-background/40 p-2.5">
                <div class="mb-1 font-semibold text-subtle-foreground">目前畫像基準：</div>
                <div class="font-mono text-2xs text-muted-foreground line-clamp-4">{{ dreamPassProposal.current_profile }}</div>
              </div>
              <div class="rounded-lg border border-primary/30 bg-primary-soft/20 p-2.5">
                <div class="mb-1 font-semibold text-primary-soft-foreground">建議修訂後畫像：</div>
                <div class="font-mono text-2xs text-foreground line-clamp-4">{{ dreamPassProposal.suggested_profile }}</div>
              </div>
            </div>

            <!-- 差異摘要 -->
            <div v-if="dreamPassProposal.diff_summary" class="mb-3 text-2xs text-muted-foreground">
              <span class="font-semibold text-foreground">演進摘要：</span> {{ dreamPassProposal.diff_summary }}
            </div>

            <!-- 操作按鈕 -->
            <div v-if="dreamPassProposal.status === 'pending'" class="flex items-center justify-end gap-2">
              <Button size="sm" variant="ghost" @click="handleDismissDreamPass(dreamPassProposal.id)">
                <X class="size-3.5" /> 忽略
              </Button>
              <Button size="sm" :disabled="isDreamPassApplying" @click="handleApplyDreamPass(dreamPassProposal.id)">
                <Check class="size-3.5" />
                <Loader2 v-if="isDreamPassApplying" class="size-3.5 animate-spin" />
                一鍵採用
              </Button>
            </div>
          </div>
          <div v-else class="rounded-xl border border-dashed border-border p-8 text-center text-xs text-muted-foreground">
            <Sparkles class="mx-auto mb-2 size-6 text-muted-foreground/60" />
            <p>目前尚無自省提案。點擊上方「執行 7 天自省」將自動深度分析最近的加權、標籤與閱讀動向。</p>
          </div>
        </div>

        <!-- Rules: 確定性硬規則引擎 -->
        <div v-else-if="tab === 'rules'" class="space-y-4">
          <!-- 新增規則表單 -->
          <div class="glass-tint rounded-xl p-3.5">
            <div class="mb-2 flex items-center justify-between">
              <span class="text-xs font-semibold text-foreground">新增確定性硬規則（0 Token 即時管線）</span>
              <button
                class="flex items-center gap-1 font-mono text-2xs text-primary transition-colors hover:underline"
                @click="showRuleSandbox = !showRuleSandbox"
              >
                <FlaskConical class="size-3" />
                {{ showRuleSandbox ? '隱藏測試沙盒' : '開啟測試沙盒' }}
              </button>
            </div>

            <div class="grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
              <input
                v-model="newRule.name"
                type="text"
                placeholder="規則名稱（如：GitHub 自動打標）"
                class="h-8 rounded-md border border-border bg-input px-2.5 text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
              >
              <div class="flex gap-1.5 sm:col-span-2">
                <select v-model="newRule.field" class="h-8 w-28 rounded-md border border-border bg-input px-2 text-xs text-foreground focus:border-primary focus:outline-none">
                  <option value="domain">Domain (網域)</option>
                  <option value="url">URL (網址)</option>
                  <option value="title">Title (標題)</option>
                  <option value="source_type">來源類型</option>
                  <option value="content">Content (全文)</option>
                </select>
                <select v-model="newRule.operator" class="h-8 w-24 rounded-md border border-border bg-input px-2 text-xs text-foreground focus:border-primary focus:outline-none">
                  <option value="contains">包含</option>
                  <option value="equals">等於</option>
                  <option value="startswith">開頭是</option>
                  <option value="endswith">結尾是</option>
                  <option value="regex">正規表示式</option>
                </select>
                <input
                  v-model="newRule.value"
                  type="text"
                  placeholder="比對關鍵字或值（如：github.com）"
                  class="h-8 flex-1 rounded-md border border-border bg-input px-2.5 text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
                >
              </div>
            </div>

            <div class="mt-2 grid grid-cols-1 gap-2 text-xs sm:grid-cols-3">
              <div class="flex gap-1.5 sm:col-span-2">
                <select v-model="newRule.action_type" class="h-8 w-32 rounded-md border border-border bg-input px-2 text-xs text-foreground focus:border-primary focus:outline-none">
                  <option value="add_tag">新增標籤 (Add Tag)</option>
                  <option value="set_category">設定分類 (Category)</option>
                  <option value="star">標記星標 (Star)</option>
                  <option value="archive">直接封存 (Archive)</option>
                  <option value="mute">靜音攔截 (Mute)</option>
                </select>
                <input
                  v-if="['add_tag', 'set_category'].includes(newRule.action_type || '')"
                  v-model="newRule.action_value"
                  type="text"
                  :placeholder="newRule.action_type === 'add_tag' ? '標籤名（如：dev）' : '分類名（如：工程架構）'"
                  class="h-8 flex-1 rounded-md border border-border bg-input px-2.5 text-xs text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
                >
                <div v-else class="flex h-8 flex-1 items-center px-2 text-2xs text-muted-foreground">
                  無需額外參數
                </div>
              </div>
              <div class="flex items-center justify-end gap-2">
                <div class="flex items-center gap-1 font-mono text-2xs text-subtle-foreground">
                  <span>優先級</span>
                  <input
                    v-model.number="newRule.priority"
                    type="number"
                    class="h-8 w-14 rounded-md border border-border bg-input px-1.5 text-center text-xs text-foreground focus:border-primary focus:outline-none"
                  >
                </div>
                <Button size="sm" :disabled="!newRule.name || !newRule.value || isCreatingRule" @click="handleCreateRule">
                  <Plus class="size-3.5" /> 加入規則
                </Button>
              </div>
            </div>
          </div>

          <!-- 測試沙盒 -->
          <div v-if="showRuleSandbox" class="rounded-xl border border-primary/30 bg-primary-soft/5 p-3.5 text-xs">
            <div class="mb-2 flex items-center justify-between">
              <span class="font-semibold text-foreground">規則即時預覽沙盒 (Dry-run Simulation)</span>
              <Button size="sm" variant="outline" :disabled="isTestingRule" @click="runRuleTest">
                <FlaskConical class="size-3" />
                {{ isTestingRule ? '測試中…' : '執行比對' }}
              </Button>
            </div>
            <div class="grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
              <div>
                <label class="font-mono text-2xs text-subtle-foreground">測試標題</label>
                <input v-model="testSample.title" class="h-7 w-full rounded border border-border bg-input px-2 text-xs text-foreground">
              </div>
              <div>
                <label class="font-mono text-2xs text-subtle-foreground">測試 URL</label>
                <input v-model="testSample.url" class="h-7 w-full rounded border border-border bg-input px-2 text-xs text-foreground">
              </div>
            </div>
            <div v-if="testResult" class="mt-2.5 rounded bg-background/80 p-2 font-mono text-2xs">
              <div class="font-bold text-foreground">命中規則：{{ testResult.matched_rules.length ? testResult.matched_rules.join(', ') : '無' }}</div>
              <div v-if="Object.keys(testResult.changes).length" class="mt-1 text-primary-soft-foreground">
                <div v-for="(v, k) in testResult.changes" :key="k">
                  {{ k }}: {{ JSON.stringify(v.before) }} <ArrowRight class="inline size-2.5" /> {{ JSON.stringify(v.after) }}
                </div>
              </div>
            </div>
          </div>

          <!-- 規則清單 -->
          <div v-if="isRulesLoading" class="space-y-2">
            <Skeleton v-for="i in 3" :key="i" class="h-14 w-full rounded-xl" />
          </div>
          <div v-else-if="rules.length === 0" class="py-10 text-center text-xs text-muted-foreground">
            尚無硬規則。設定條件可自動在情報入庫前加上自訂標籤、分類或星標。
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="r in rules"
              :key="r.id"
              class="flex items-center justify-between gap-3 rounded-xl border border-border/40 bg-white/45 p-3 text-xs shadow-sm transition-colors hover:bg-white/70 dark:bg-white/[0.06] dark:hover:bg-white/[0.1]"
            >
              <div class="min-w-0 flex-1">
                <div class="mb-1 flex items-center gap-2">
                  <span class="font-semibold text-foreground">{{ r.name }}</span>
                  <span class="font-mono text-2xs text-subtle-foreground">優先級 {{ r.priority }}</span>
                  <Badge :class="r.is_active ? 'bg-success-soft text-success' : 'bg-muted text-muted-foreground'">
                    {{ r.is_active ? '啟用' : '停用' }}
                  </Badge>
                </div>
                <div class="flex flex-wrap items-center gap-2 font-mono text-2xs text-muted-foreground">
                  <span class="rounded bg-muted px-1.5 py-0.5 text-foreground">IF {{ r.field }} {{ r.operator }} "{{ r.value }}"</span>
                  <ArrowRight class="size-2.5 text-subtle-foreground" />
                  <span class="flex items-center gap-1 rounded bg-primary-soft px-1.5 py-0.5 text-primary-soft-foreground">
                    <component :is="actionIcon(r.action_type)" class="size-2.5" />
                    THEN {{ r.action_type }} {{ r.action_value ? `"${r.action_value}"` : '' }}
                  </span>
                </div>
              </div>
              <div class="flex items-center gap-1">
                <Button size="sm" variant="ghost" class="h-7 px-2 text-2xs" @click="handleToggleRule(r)">
                  {{ r.is_active ? '停用' : '啟用' }}
                </Button>
                <button
                  class="rounded-md p-1.5 text-subtle-foreground transition-colors hover:bg-danger-soft hover:text-danger"
                  title="刪除規則"
                  aria-label="刪除規則"
                  @click="handleDeleteRule(r.id, r.name)"
                >
                  <Trash2 class="size-3.5" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>
