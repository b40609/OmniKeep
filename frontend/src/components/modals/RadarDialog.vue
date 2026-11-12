<script setup lang="ts">
import { computed, ref, watch } from 'vue'
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
  TrendingUp,
  TrendingDown,
} from 'lucide-vue-next'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import Badge from '@/components/ui/badge/Badge.vue'
import Button from '@/components/ui/button/Button.vue'
import Skeleton from '@/components/ui/skeleton/Skeleton.vue'
import * as api from '@/lib/api'
import { sourceMeta, formatRelativeTime } from '@/lib/format'
import { renderMarkdown } from '@/lib/markdown'
import { radarScheduleNote } from '@/lib/radarSchedule'
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
  enabled: false,
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

const scheduleNote = computed(() => radarScheduleNote(radar.settings, radar.sources))
const NOTE_TONE = {
  ok: 'text-emerald-600 dark:text-emerald-400',
  off: 'text-muted-foreground',
  warn: 'text-amber-600 dark:text-amber-400',
} as const
const scheduleUnsaved = computed(() => !!radar.settings && scheduleSettings.value.enabled !== radar.settings.enabled)

async function handleSaveSettings() {
  isSavingSettings.value = true
  try {
    await radar.updateSettings(scheduleSettings.value)
    toast.success('排程與通知設定已儲存')
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
    toast.success(`已加入探索來源：${newSource.value.name}`)
    newSource.value = { name: '', source_type: 'youtube', url: '' }
    await radar.load()
  } catch (e) {
    toast.error('新增來源失敗', { description: (e as Error).message })
  }
}

async function removeSource(id: number) {
  try {
    await api.deleteRadarSource(id)
    toast.success('已移除探索來源')
    await radar.load()
  } catch (e) {
    toast.error('移除失敗', { description: (e as Error).message })
  }
}

async function scan() {
  isScanning.value = true
  const t = toast.loading('正在檢查探索來源…')
  try {
    const data = await api.radarScan()
    const count = data.result?.new_items_count ?? 0
    toast.success(`檢查完成，找到 ${count} 則新內容`, { id: t })
    await radar.load()
  } catch (e) {
    toast.error('檢查失敗', { id: t, description: (e as Error).message })
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
    toast.error('無法載入興趣描述或建議', { description: (e as Error).message })
  } finally {
    isProfileLoading.value = false
  }
}

async function saveProfile() {
  isProfileSaving.value = true
  try {
    const res = await api.updateInterestProfile(profileText.value)
    profileUpdatedAt.value = res.updated_at || null
    toast.success('興趣描述已儲存')
  } catch (e) {
    toast.error('儲存興趣描述失敗', { description: (e as Error).message })
  } finally {
    isProfileSaving.value = false
  }
}

async function triggerDreamPass() {
  isDreamPassRunning.value = true
  const t = toast.loading('正在整理最近 7 天的使用紀錄…')
  try {
    const res = await api.runDreamPass(7)
    dreamPassProposal.value = res.proposal
    toast.success('整理完成，有一份修訂建議', { id: t })
  } catch (e) {
    toast.error('整理失敗', { id: t, description: (e as Error).message })
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
    toast.success('已採用建議，興趣描述已更新')
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
    toast.info('已忽略這份建議')
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
    toast.error('無法載入規則', { description: (e as Error).message })
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
      toast.info('測試內容沒有符合任何規則')
    } else {
      toast.success(`符合 ${res.matched_rules.length} 條規則`)
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
            <DialogTitle>探索</DialogTitle>
            <DialogDescription>自動到你指定的來源找新內容，依你的興趣挑出值得看的。</DialogDescription>
          </DialogHeader>
        </div>
        <Button :disabled="isScanning" @click="scan">
          <Loader2 v-if="isScanning" class="size-3.5 animate-spin" />
          {{ isScanning ? '檢查中…' : '立即檢查' }}
        </Button>
      </div>

      <!-- Tabs -->
      <div class="flex shrink-0 items-center gap-1 border-b border-border px-5 text-sm overflow-x-auto" role="tablist">
        <button
          v-for="t in [
            { id: 'settings', label: '排程與通知' },
            { id: 'sources', label: `探索來源（${radar.sources.length}）` },
            { id: 'topics', label: `主題偏好（${radar.topics.length}）` },
            { id: 'digests', label: `精選（${radar.digests.length}）` },
            { id: 'dreampass', label: '興趣描述' },
            { id: 'rules', label: rules.length ? `自動規則（${rules.length}）` : '自動規則' },
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
                <span class="text-sm font-semibold text-foreground">自動檢查</span>
              </div>
              <p class="text-sm text-muted-foreground">
                開啟後會依下面的間隔在背景檢查探索來源。關閉時只有按「立即檢查」才會檢查。
              </p>
              <p v-if="scheduleNote" class="text-sm font-medium" :class="NOTE_TONE[scheduleNote.tone]">
                {{ scheduleNote.text }}
              </p>
              <p v-if="scheduleUnsaved" class="text-sm font-medium text-amber-600 dark:text-amber-400">
                尚未儲存：按下方「儲存排程設定」後才會生效。
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
              <label class="text-sm font-semibold text-foreground flex items-center gap-1.5">
                <RefreshCw class="size-3.5 text-muted-foreground" />
                檢查間隔
              </label>
              <select
                v-model.number="scheduleSettings.interval_minutes"
                :disabled="!scheduleSettings.enabled"
                class="w-full h-8.5 rounded-md border border-border bg-input px-2.5 text-sm text-foreground focus:border-primary focus:outline-none disabled:opacity-50"
              >
                <option :value="0">只手動檢查</option>
                <option :value="60">每 1 小時</option>
                <option :value="180">每 3 小時（預設）</option>
                <option :value="360">每 6 小時</option>
                <option :value="720">每 12 小時</option>
                <option :value="1440">每 24 小時</option>
              </select>
              <p class="text-sm text-subtle-foreground">
                來源很少更新的時段會自動少檢查幾次。
              </p>
            </div>

            <!-- Budget Cap -->
            <div class="glass-tint rounded-xl p-3.5 space-y-2">
              <div class="flex items-center justify-between">
                <label class="text-sm font-semibold text-foreground flex items-center gap-1.5">
                  <Sliders class="size-3.5 text-muted-foreground" />
                  每次最多分析幾則
                </label>
                <span class="font-mono text-sm font-bold text-primary">{{ scheduleSettings.max_analyze_per_cycle }} 則</span>
              </div>
              <input
                v-model.number="scheduleSettings.max_analyze_per_cycle"
                type="range"
                min="1"
                max="10"
                step="1"
                class="w-full accent-primary h-2 bg-muted rounded-lg cursor-pointer mt-1"
              >
              <p class="text-sm text-subtle-foreground">
                超過的會留到之後幾次再分析，避免一次用掉太多 AI 額度。
              </p>
            </div>
          </div>

          <!-- Telegram Notification Policy -->
          <div class="glass-tint rounded-xl p-3.5 space-y-3">
            <div class="flex items-center justify-between">
              <label class="text-sm font-semibold text-foreground flex items-center gap-1.5">
                <Bell class="size-3.5 text-muted-foreground" />
                Telegram 通知
              </label>
              <span class="text-3xs text-muted-foreground font-mono">
                目前：{{ scheduleSettings.notification_mode === 'silent' ? '不通知' : scheduleSettings.notification_mode === 'daily_digest' ? '每日精選' : '只通知高分內容' }}
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
                  <span class="text-sm font-semibold flex items-center gap-1.5 text-foreground">
                    <BellOff class="size-3.5 text-muted-foreground" />
                    不通知
                  </span>
                  <span class="text-3xs rounded px-1.5 py-0.5 bg-primary/10 text-primary">預設</span>
                </div>
                <p class="text-sm leading-relaxed">
                  照常收錄與分析，不傳 Telegram 訊息。
                </p>
              </div>

              <!-- Daily Digest Option -->
              <div
                class="cursor-pointer rounded-lg border p-3 transition-all"
                :class="scheduleSettings.notification_mode === 'daily_digest' ? 'border-primary bg-primary/5 text-foreground shadow-sm' : 'border-border/60 hover:border-border text-muted-foreground'"
                @click="scheduleSettings.notification_mode = 'daily_digest'"
              >
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-sm font-semibold flex items-center gap-1.5 text-foreground">
                    <Clock class="size-3.5 text-muted-foreground" />
                    每日精選
                  </span>
                </div>
                <p class="text-sm leading-relaxed">
                  每天在指定時間傳一則當日摘要。
                </p>
              </div>

              <!-- VIP Alert Option -->
              <div
                class="cursor-pointer rounded-lg border p-3 transition-all"
                :class="scheduleSettings.notification_mode === 'vip_alert' ? 'border-primary bg-primary/5 text-foreground shadow-sm' : 'border-border/60 hover:border-border text-muted-foreground'"
                @click="scheduleSettings.notification_mode = 'vip_alert'"
              >
                <div class="flex items-center justify-between mb-1.5">
                  <span class="text-sm font-semibold flex items-center gap-1.5 text-foreground">
                    <Star class="size-3.5 text-amber-500" />
                    只通知高分內容
                  </span>
                </div>
                <p class="text-sm leading-relaxed">
                  平常不通知，出現高分內容時立刻通知。
                </p>
              </div>
            </div>

            <!-- Conditional sub-settings for daily_digest -->
            <div v-if="scheduleSettings.notification_mode === 'daily_digest'" class="pt-2 border-t border-border/50 flex items-center justify-between text-sm">
              <span class="text-muted-foreground text-sm">精選傳送時間</span>
              <select
                v-model.number="scheduleSettings.daily_digest_hour"
                class="h-7 rounded border border-border bg-input px-2 text-sm text-foreground focus:border-primary focus:outline-none"
              >
                <option v-for="h in 24" :key="h-1" :value="h-1">
                  {{ String(h-1).padStart(2, '0') }}:00（{{ h-1 < 12 ? '上午' : '下午' }}）
                </option>
              </select>
            </div>

            <!-- Conditional sub-settings for vip_alert -->
            <div v-if="scheduleSettings.notification_mode === 'vip_alert'" class="pt-2 border-t border-border/50 flex items-center justify-between text-sm">
              <span class="text-muted-foreground text-sm">通知的分數門檻</span>
              <div class="flex items-center gap-2">
                <input
                  v-model.number="scheduleSettings.vip_threshold"
                  type="range"
                  min="3.0"
                  max="5.0"
                  step="0.5"
                  class="w-24 accent-primary h-1.5 bg-muted rounded cursor-pointer"
                >
                <span class="font-mono text-sm font-semibold text-primary">>= {{ scheduleSettings.vip_threshold.toFixed(1) }}</span>
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
            <p class="mb-2.5 text-sm font-semibold text-foreground">新增探索來源</p>
            <div class="grid grid-cols-1 gap-2 text-sm sm:grid-cols-4">
              <input v-model="newSource.name" type="text" placeholder="名稱（例如：某某部落格）" class="h-8 rounded-md border border-border bg-input px-2.5 text-sm text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none">
              <select v-model="newSource.source_type" class="h-8 rounded-md border border-border bg-input px-2 text-sm text-foreground focus:border-primary focus:outline-none">
                <option value="youtube">YouTube 頻道</option>
                <option value="github">GitHub 專案或 Trending</option>
                <option value="rss">部落格或 RSS</option>
                <option value="google_news">Google 新聞（關鍵字）</option>
                <option value="web_change">網頁變更（例如更新紀錄）</option>
              </select>
              <input
                v-model="newSource.url"
                type="text"
                :placeholder="newSource.source_type === 'google_news' ? '關鍵字（例如：DeepSeek R1）或網址' : newSource.source_type === 'web_change' ? '要留意變更的網址（https://…）' : '網址或頻道連結'"
                class="h-8 rounded-md border border-border bg-input px-2.5 text-sm text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none sm:col-span-2"
              >
            </div>
            <div class="mt-2.5 flex justify-end">
              <Button size="sm" :disabled="!newSource.name || !newSource.url" @click="addSource">
                <Plus class="size-3.5" /> 加入來源
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
              class="flex items-center justify-between gap-3 rounded-xl border-0 p-3 text-sm shadow-sm transition-all"
              :class="src.is_active === 0
                ? 'bg-muted/30 opacity-60 dark:bg-white/[0.02]'
                : 'bg-white/45 hover:bg-white/70 dark:bg-white/[0.06] dark:hover:bg-white/[0.1]'"
            >
              <div class="min-w-0 flex-1">
                <div class="mb-1 flex items-center gap-2">
                  <Badge :class="sourceMeta(src.source_type).badgeClass">{{ sourceMeta(src.source_type).label }}</Badge>
                  <span class="truncate font-semibold text-foreground">{{ src.name }}</span>
                  <span v-if="src.is_active === 0" class="rounded bg-muted px-1.5 py-px text-2xs text-muted-foreground font-mono">已暫停</span>
                  <span v-else class="rounded bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 px-1.5 py-px text-2xs font-mono">啟用中</span>
                  <span class="font-mono text-2xs text-subtle-foreground">Tier {{ src.tier ?? '—' }}</span>
                </div>
                <div class="flex items-center gap-3 truncate font-mono text-2xs text-subtle-foreground">
                  <span class="max-w-xs truncate">{{ src.url }}</span>
                  <span v-if="(src.hot_hours ?? []).length" class="shrink-0 rounded bg-primary-soft px-1.5 py-px text-primary-soft-foreground">
                    學習時段 {{ (src.hot_hours ?? []).map((h) => h + ':00').join('、') }}
                  </span>
                  <span v-else class="shrink-0">還在學習更新時段</span>
                </div>
              </div>
              <div class="flex items-center gap-1 shrink-0">
                <button
                  class="rounded-md p-2 transition-colors"
                  :class="src.is_active === 0
                    ? 'text-primary hover:bg-primary-soft'
                    : 'text-subtle-foreground hover:bg-muted hover:text-foreground'"
                  :title="src.is_active === 0 ? '恢復檢查' : '暫停這個來源'"
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
          <p class="glass-tint mb-3 rounded-lg p-2.5 text-sm text-muted-foreground">
            在收藏上按「多推薦」或「少推薦」會調整這裡的主題權重；靜音的主題不會再出現。
          </p>
          <div
            v-for="tp in radar.topics"
            :key="tp.topic_tag"
            class="flex items-center justify-between gap-2 rounded-lg px-2 py-2 font-mono text-sm transition-colors hover:bg-accent/50"
          >
            <div class="flex items-center gap-2.5">
              <span class="font-semibold" :class="tp.is_blocked ? 'text-subtle-foreground line-through' : 'text-foreground'">#{{ tp.topic_tag }}</span>
              <span v-if="tp.is_blocked" class="rounded border border-danger/30 bg-danger-soft px-1.5 py-px text-2xs text-danger">已靜音</span>
              <span v-else-if="tp.weight > 1" class="rounded border border-primary/30 bg-primary-soft px-1.5 py-px text-2xs text-primary-soft-foreground">+{{ (tp.weight - 1).toFixed(1) }}</span>
              <span v-else-if="tp.weight < 1" class="rounded border border-warning/30 bg-warning-soft px-1.5 py-px text-2xs text-warning">{{ (tp.weight - 1).toFixed(1) }}</span>
            </div>
            <div class="flex items-center gap-1">
              <button class="inline-flex h-7 items-center gap-1 rounded-md bg-muted px-2 font-sans text-sm text-primary-soft-foreground transition-colors hover:bg-accent" title="權重 +0.5" @click="tuneTopic(tp.topic_tag, 'boost')"><TrendingUp class="size-3.5" />多推薦</button>
              <button class="inline-flex h-7 items-center gap-1 rounded-md bg-muted px-2 font-sans text-sm text-danger transition-colors hover:bg-accent" title="權重 -1.0" @click="tuneTopic(tp.topic_tag, 'dampen')"><TrendingDown class="size-3.5" />少推薦</button>
              <button class="h-7 rounded-md bg-muted px-2 font-sans text-sm text-muted-foreground transition-colors hover:bg-accent" @click="tuneTopic(tp.topic_tag, tp.is_blocked ? 'reset' : 'mute')">
                {{ tp.is_blocked ? '取消靜音' : '靜音' }}
              </button>
            </div>
          </div>
          <p v-if="radar.topics.length === 0" class="py-10 text-center text-sm text-muted-foreground">
            還沒有調整過任何主題。在收藏上按「多推薦」或「少推薦」後會出現在這裡。
          </p>
        </div>

        <!-- Digests -->
        <div v-else-if="tab === 'digests'" class="space-y-4">
          <article v-for="dig in radar.digests" :key="dig.id" class="rounded-xl border border-border bg-background-subtle p-4">
            <div class="flex items-center justify-between border-b border-hairline pb-2.5 text-sm">
              <span class="font-bold text-foreground">{{ dig.title }}</span>
              <span class="font-mono text-2xs text-subtle-foreground">{{ formatRelativeTime(dig.created_at) }}</span>
            </div>
            <div class="prose-reader mt-3 max-h-60 overflow-y-auto text-sm" v-html="renderMarkdown(dig.markdown_content)" />
          </article>
          <p v-if="radar.digests.length === 0" class="py-12 text-center text-sm text-muted-foreground">
            還沒有精選。同一段時間出現多則高分內容時，會整理成一份精選。
          </p>
        </div>

        <!-- Dream Pass: 品味自省畫像 -->
        <div v-else-if="tab === 'dreampass'" class="space-y-4">
          <!-- 當前品味畫像卡片 -->
          <div class="glass-tint rounded-xl border border-border/50 p-4">
            <div class="mb-2 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Sparkles class="size-4 text-primary" />
                <span class="text-sm font-semibold text-foreground">你的興趣描述</span>
                <span v-if="profileUpdatedAt" class="font-mono text-2xs text-subtle-foreground">
                  最後更新：{{ formatRelativeTime(profileUpdatedAt) }}
                </span>
              </div>
              <div class="flex items-center gap-2">
                <Button size="sm" variant="outline" :disabled="isProfileSaving" @click="saveProfile">
                  <Loader2 v-if="isProfileSaving" class="size-3 animate-spin" />
                  儲存
                </Button>
                <Button size="sm" :disabled="isDreamPassRunning" @click="triggerDreamPass">
                  <RefreshCw v-if="!isDreamPassRunning" class="size-3" />
                  <Loader2 v-else class="size-3 animate-spin" />
                  {{ isDreamPassRunning ? '整理中…' : '依最近 7 天整理建議' }}
                </Button>
              </div>
            </div>
            <p class="mb-2 text-sm text-muted-foreground">
              探索用這段描述判斷內容和你的相關程度；分數 >= 2.5 的會自動收錄。
            </p>
            <textarea
              v-model="profileText"
              rows="3"
              placeholder="例如：關注 Rust、AI Agent、工業自動化；不看娛樂新聞"
              class="w-full rounded-lg border border-border bg-input p-2.5 font-mono text-sm text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
            />
          </div>

          <!-- Dream Pass 最新自省卡 -->
          <div v-if="dreamPassProposal" class="rounded-xl border border-primary/20 bg-primary-soft/10 p-4">
            <div class="mb-3 flex items-center justify-between">
              <div class="flex items-center gap-2">
                <Sliders class="size-4 text-primary" />
                <span class="text-sm font-bold text-foreground">修訂建議</span>
                <Badge
                  :class="dreamPassProposal.status === 'applied' ? 'bg-success-soft text-success' : dreamPassProposal.status === 'dismissed' ? 'bg-muted text-muted-foreground' : 'bg-warning-soft text-warning'"
                >
                  {{ dreamPassProposal.status === 'applied' ? '已採用' : dreamPassProposal.status === 'dismissed' ? '已忽略' : '待決定' }}
                </Badge>
              </div>
              <span class="font-mono text-2xs text-subtle-foreground">
                {{ formatRelativeTime(dreamPassProposal.created_at) }}
              </span>
            </div>

            <!-- 觀察理由 -->
            <div class="mb-3 rounded-lg bg-background/60 p-3 text-sm">
              <div class="mb-1 font-semibold text-foreground">觀察到的使用情形</div>
              <div class="text-muted-foreground leading-relaxed">{{ dreamPassProposal.observations }}</div>
            </div>

            <!-- 建議演進差異對比 -->
            <div class="mb-3 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
              <div class="rounded-lg border border-border/50 bg-background/40 p-2.5">
                <div class="mb-1 font-semibold text-subtle-foreground">目前的描述</div>
                <div class="text-sm text-muted-foreground line-clamp-4">{{ dreamPassProposal.current_profile }}</div>
              </div>
              <div class="rounded-lg border border-primary/30 bg-primary-soft/20 p-2.5">
                <div class="mb-1 font-semibold text-primary-soft-foreground">建議改成</div>
                <div class="text-sm text-foreground line-clamp-4">{{ dreamPassProposal.suggested_profile }}</div>
              </div>
            </div>

            <!-- 差異摘要 -->
            <div v-if="dreamPassProposal.diff_summary" class="mb-3 text-sm text-muted-foreground">
              <span class="font-semibold text-foreground">差異：</span> {{ dreamPassProposal.diff_summary }}
            </div>

            <!-- 操作按鈕 -->
            <div v-if="dreamPassProposal.status === 'pending'" class="flex items-center justify-end gap-2">
              <Button size="sm" variant="ghost" @click="handleDismissDreamPass(dreamPassProposal.id)">
                <X class="size-3.5" /> 忽略
              </Button>
              <Button size="sm" :disabled="isDreamPassApplying" @click="handleApplyDreamPass(dreamPassProposal.id)">
                <Check class="size-3.5" />
                <Loader2 v-if="isDreamPassApplying" class="size-3.5 animate-spin" />
                採用
              </Button>
            </div>
          </div>
          <div v-else class="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
            <Sparkles class="mx-auto mb-2 size-6 text-muted-foreground/60" />
            <p>還沒有修訂建議。按上面的「依最近 7 天整理建議」，會依你最近的加星、標籤與閱讀紀錄提出修改。</p>
          </div>
        </div>

        <!-- Rules: 確定性硬規則引擎 -->
        <div v-else-if="tab === 'rules'" class="space-y-4">
          <!-- 新增規則表單 -->
          <div class="glass-tint rounded-xl p-3.5">
            <div class="mb-2 flex items-center justify-between">
              <span class="text-sm font-semibold text-foreground">新增規則（不使用 AI，收錄時立即套用）</span>
              <button
                class="flex items-center gap-1 font-mono text-sm text-primary transition-colors hover:underline"
                @click="showRuleSandbox = !showRuleSandbox"
              >
                <FlaskConical class="size-3" />
                {{ showRuleSandbox ? '收起測試' : '測試規則' }}
              </button>
            </div>

            <div class="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
              <input
                v-model="newRule.name"
                type="text"
                placeholder="規則名稱（例如：GitHub 自動加標籤）"
                class="h-8 rounded-md border border-border bg-input px-2.5 text-sm text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
              >
              <div class="flex gap-1.5 sm:col-span-2">
                <select v-model="newRule.field" class="h-8 w-32 rounded-md border border-border bg-input px-2 text-sm text-foreground focus:border-primary focus:outline-none">
                  <option value="domain">網域</option>
                  <option value="url">網址</option>
                  <option value="title">標題</option>
                  <option value="source_type">來源類型</option>
                  <option value="content">全文</option>
                </select>
                <select v-model="newRule.operator" class="h-8 w-28 rounded-md border border-border bg-input px-2 text-sm text-foreground focus:border-primary focus:outline-none">
                  <option value="contains">包含</option>
                  <option value="equals">等於</option>
                  <option value="startswith">開頭是</option>
                  <option value="endswith">結尾是</option>
                  <option value="regex">正規表示式</option>
                </select>
                <input
                  v-model="newRule.value"
                  type="text"
                  placeholder="要比對的文字（例如：github.com）"
                  class="h-8 flex-1 rounded-md border border-border bg-input px-2.5 text-sm text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
                >
              </div>
            </div>

            <div class="mt-2 grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
              <div class="flex gap-1.5 sm:col-span-2">
                <select v-model="newRule.action_type" class="h-8 w-36 rounded-md border border-border bg-input px-2 text-sm text-foreground focus:border-primary focus:outline-none">
                  <option value="add_tag">加上標籤</option>
                  <option value="set_category">設定分類</option>
                  <option value="star">加星</option>
                  <option value="archive">封存</option>
                  <option value="mute">靜音</option>
                </select>
                <input
                  v-if="['add_tag', 'set_category'].includes(newRule.action_type || '')"
                  v-model="newRule.action_value"
                  type="text"
                  :placeholder="newRule.action_type === 'add_tag' ? '標籤名稱（例如：dev）' : '分類名稱（例如：工程架構）'"
                  class="h-8 flex-1 rounded-md border border-border bg-input px-2.5 text-sm text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none"
                >
                <div v-else class="flex h-8 flex-1 items-center px-2 text-sm text-muted-foreground">
                  不需要其他設定
                </div>
              </div>
              <div class="flex items-center justify-end gap-2">
                <div class="flex items-center gap-1 font-mono text-2xs text-subtle-foreground">
                  <span>優先順序</span>
                  <input
                    v-model.number="newRule.priority"
                    type="number"
                    class="h-8 w-14 rounded-md border border-border bg-input px-1.5 text-center text-sm text-foreground focus:border-primary focus:outline-none"
                  >
                </div>
                <Button size="sm" :disabled="!newRule.name || !newRule.value || isCreatingRule" @click="handleCreateRule">
                  <Plus class="size-3.5" /> 加入規則
                </Button>
              </div>
            </div>
          </div>

          <!-- 測試沙盒 -->
          <div v-if="showRuleSandbox" class="rounded-xl border border-primary/30 bg-primary-soft/5 p-3.5 text-sm">
            <div class="mb-2 flex items-center justify-between">
              <span class="font-semibold text-foreground">測試規則（不會儲存任何東西）</span>
              <Button size="sm" variant="outline" :disabled="isTestingRule" @click="runRuleTest">
                <FlaskConical class="size-3" />
                {{ isTestingRule ? '測試中…' : '測試' }}
              </Button>
            </div>
            <div class="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
              <div>
                <label class="font-mono text-sm text-subtle-foreground">測試標題</label>
                <input v-model="testSample.title" class="h-7 w-full rounded border border-border bg-input px-2 text-sm text-foreground">
              </div>
              <div>
                <label class="font-mono text-sm text-subtle-foreground">測試網址</label>
                <input v-model="testSample.url" class="h-7 w-full rounded border border-border bg-input px-2 text-sm text-foreground">
              </div>
            </div>
            <div v-if="testResult" class="mt-2.5 rounded bg-background/80 p-2 font-mono text-sm">
              <div class="font-bold text-foreground">符合的規則：{{ testResult.matched_rules.length ? testResult.matched_rules.join(', ') : '無' }}</div>
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
          <div v-else-if="rules.length === 0" class="py-10 text-center text-sm text-muted-foreground">
            還沒有規則。規則會在收錄時自動加上標籤、分類或加星。
          </div>
          <div v-else class="space-y-2">
            <div
              v-for="r in rules"
              :key="r.id"
              class="flex items-center justify-between gap-3 rounded-xl border border-border/40 bg-white/45 p-3 text-sm shadow-sm transition-colors hover:bg-white/70 dark:bg-white/[0.06] dark:hover:bg-white/[0.1]"
            >
              <div class="min-w-0 flex-1">
                <div class="mb-1 flex items-center gap-2">
                  <span class="font-semibold text-foreground">{{ r.name }}</span>
                  <span class="font-mono text-2xs text-subtle-foreground">優先順序 {{ r.priority }}</span>
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
                <Button size="sm" variant="ghost" class="h-7 px-2 text-sm" @click="handleToggleRule(r)">
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
