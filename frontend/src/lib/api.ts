/**
 * Typed API client — mirrors the FastAPI contract exactly.
 * Backend contract: app/routers/{items,categories,ingest,radar}.py
 */

export type SourceType = 'youtube' | 'bilibili' | 'github' | 'rss' | 'note' | 'snippet' | string

export interface Citation {
  citation_id: number
  parent_id: number
  parent_title: string
  parent_source_type: SourceType
  mention_context?: string | null
}

export interface SubEntity {
  citation_id: number
  target_item_id?: number | null
  target_name?: string | null
  title_l1?: string | null
  target_canonical_url?: string | null
  category_name?: string | null
  mention_context?: string | null
  tech_tags?: string[] | null
}

export interface Item {
  id: number
  title_l1: string
  summary_l1: string
  url: string
  source_type: SourceType
  category_name: string
  tech_tags: string[] | null
  is_read: number | boolean
  is_starred: number | boolean
  created_at: string
  published_date?: string | null
  author?: string | null
  origin?: string | null
  sub_entities_count?: number
  citations_count?: number
  deep_analysis?: string | null
  content_raw?: string | null
  citations?: Citation[]
  sub_entities?: SubEntity[]
}

export interface Category {
  id: number
  name: string
  item_count?: number
}

export interface Stats {
  inbox: number
  starred: number
  archived: number
  total: number
}

export interface RadarSource {
  id: number
  name: string
  source_type: 'youtube' | 'github' | 'rss' | string
  url: string
  tier?: number
  hot_hours?: number[]
  is_active?: number | boolean
}

export interface RadarSettings {
  enabled: boolean
  interval_minutes: number
  max_analyze_per_cycle: number
  notification_mode: 'silent' | 'daily_digest' | 'vip_alert'
  daily_digest_hour: number
  vip_threshold: number
  auto_digest_push?: boolean
  auto_star_push?: boolean
  updated_at?: string
}

export interface RadarTopic {
  topic_tag: string
  weight: number
  is_blocked: number | boolean
}

export interface RadarDigest {
  id: number
  title: string
  created_at: string
  markdown_content: string
}

export interface TriageView {
  read?: 'true' | 'false'
  starred?: 'true'
}


let apiKey = ''
let authVersion = 0

export function setApiKey(value: string) {
  if (apiKey !== value) authVersion++
  apiKey = value
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (!apiKey) throw new Error('請先登入')
  const version = authVersion
  function ensureCurrentSession() {
    if (version !== authVersion) throw new Error('登入狀態已變更，請重新操作')
  }
  const res = await fetch(path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers, Authorization: `Bearer ${apiKey}` },
  })
  ensureCurrentSession()
  if (res.status === 401) {
    setApiKey('')
    window.dispatchEvent(new Event('omnikeep-auth-required'))
  }
  if (!res.ok) {
    let detail = `HTTP ${res.status}`
    try {
      const body = await res.json()
      detail = body.detail || body.error || detail
    } catch {
      /* non-json error body */
    }
    throw new Error(detail)
  }
  const body = res.status === 204 ? undefined : await res.json()
  ensureCurrentSession()
  return body as T
}

/* ---------------- Items ---------------- */

export interface ItemFilters {
  category?: string
  q?: string
  read?: 'true' | 'false'
  starred?: 'true'
}

export function getItems(filters: ItemFilters = {}): Promise<Item[]> {
  const params = new URLSearchParams()
  if (filters.category) params.append('category', filters.category)
  if (filters.q) params.append('q', filters.q)
  if (filters.read) params.append('read', filters.read)
  if (filters.starred) params.append('starred', filters.starred)
  const qs = params.toString()
  return request<Item[]>(`/api/items${qs ? `?${qs}` : ''}`)
}

export function getItem(id: number): Promise<Item> {
  return request<Item>(`/api/items/${id}`)
}

export function patchItem(id: number, patch: Partial<Pick<Item, 'is_read' | 'is_starred' | 'category_name'>>): Promise<Item> {
  return request<Item>(`/api/items/${id}`, { method: 'PATCH', body: JSON.stringify(patch) })
}

export function deleteItem(id: number): Promise<void> {
  return request<void>(`/api/items/${id}`, { method: 'DELETE' })
}

export function getStats(): Promise<Stats> {
  return request<Stats>('/api/items/stats')
}

export function seedDemoItems(): Promise<{ success: boolean; count: number; message: string }> {
  return request<{ success: boolean; count: number; message: string }>('/api/items/seed-demo', {
    method: 'POST',
  })
}

export function searchSemantic(q: string, limit: number = 20): Promise<Item[]> {
  const params = new URLSearchParams()
  params.append('q', q)
  params.append('limit', String(limit))
  return request<Item[]>(`/api/items/search/semantic?${params.toString()}`)
}

export interface SnapshotStatus {
  available: boolean
  item_id: string
  path?: string
  size_bytes?: number
  mtime?: number
}

export function getSnapshotStatus(itemId: number | string): Promise<SnapshotStatus> {
  return request<SnapshotStatus>(`/api/items/${itemId}/snapshot/status`)
}

export async function fetchSnapshotHtml(itemId: number | string): Promise<string> {
  if (!apiKey) throw new Error('請先登入')
  const res = await fetch(`/api/items/${itemId}/snapshot`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  })
  if (!res.ok) {
    if (res.status === 404) throw new Error('此項目尚未建立離線快照')
    throw new Error(`獲取快照失敗 (HTTP ${res.status})`)
  }
  return res.text()
}

export async function openSnapshotInNewTab(itemId: number | string): Promise<void> {
  const html = await fetchSnapshotHtml(itemId)
  const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
  const blobUrl = URL.createObjectURL(blob)
  const w = window.open(blobUrl, '_blank')
  if (!w) {
    window.location.href = blobUrl
  }
  setTimeout(() => URL.revokeObjectURL(blobUrl), 60000)
}

/* ---------------- Categories ---------------- */

export function getCategories(): Promise<Category[]> {
  return request<Category[]>('/api/categories')
}

export function createCategory(name: string): Promise<Category> {
  return request<Category>('/api/categories', { method: 'POST', body: JSON.stringify({ name }) })
}

export function deleteCategory(name: string): Promise<void> {
  return request<void>(`/api/categories/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

/* ---------------- Ingest ---------------- */

export interface IngestResult {
  success: boolean
  item?: Item
  detail?: string
}

export function ingest(content: string, opts: { category?: string | null; async?: boolean } = {}): Promise<IngestResult> {
  return request<IngestResult>('/api/ingest', {
    method: 'POST',
    body: JSON.stringify({
      content,
      category: opts.category ?? null,
      async_mode: opts.async ?? false,
    }),
  })
}

/* ---------------- Radar ---------------- */

export function getRadarSources(): Promise<{ sources: RadarSource[] }> {
  return request<{ sources: RadarSource[] }>('/api/radar/sources')
}

export function addRadarSource(source: { name: string; source_type: string; url: string }): Promise<unknown> {
  return request('/api/radar/sources', { method: 'POST', body: JSON.stringify(source) })
}

export function deleteRadarSource(id: number | string): Promise<unknown> {
  return request(`/api/radar/sources/${id}`, { method: 'DELETE' })
}

export function toggleRadarSourceActive(id: number | string, isActive?: boolean): Promise<{ success: boolean; source: RadarSource }> {
  return request<{ success: boolean; source: RadarSource }>(`/api/radar/sources/${id}/toggle`, {
    method: 'PATCH',
    body: JSON.stringify(isActive !== undefined ? { is_active: isActive } : {}),
  })
}

export function getRadarSettings(): Promise<{ success: boolean; settings: RadarSettings }> {
  return request<{ success: boolean; settings: RadarSettings }>('/api/radar/settings')
}

export function updateRadarSettings(settings: Partial<RadarSettings>): Promise<{ success: boolean; settings: RadarSettings }> {
  return request<{ success: boolean; settings: RadarSettings }>('/api/radar/settings', {
    method: 'PUT',
    body: JSON.stringify(settings),
  })
}

export function getRadarTopics(): Promise<{ topics: RadarTopic[] }> {
  return request<{ topics: RadarTopic[] }>('/api/radar/topics')
}

export function getRadarDigests(): Promise<{ digests: RadarDigest[] }> {
  return request<{ digests: RadarDigest[] }>('/api/radar/digests')
}

export function radarScan(): Promise<{ result?: { new_items_count?: number } }> {
  return request('/api/radar/scan?async_mode=false&force=true', { method: 'POST' })
}

export type SignalAction = 'boost' | 'dampen' | 'mute' | 'reset'

export function radarFeedback(payload: { topic_tag: string; action: SignalAction } | { item_id: number; action: SignalAction }): Promise<{ result: { weight: number } }> {
  return request('/api/radar/feedback', { method: 'POST', body: JSON.stringify(payload) })
}

export interface InterestProfileData {
  success: boolean
  profile: string
  updated_at?: string | null
}

export interface DreamPassProposal {
  id: number
  status: 'pending' | 'applied' | 'dismissed'
  observations: string
  suggested_profile: string
  diff_summary: string
  current_profile: string
  created_at: string
  applied_at?: string | null
}

export function getInterestProfile(): Promise<InterestProfileData> {
  return request<InterestProfileData>('/api/radar/profile')
}

export function updateInterestProfile(profile: string): Promise<InterestProfileData> {
  return request<InterestProfileData>('/api/radar/profile', {
    method: 'PUT',
    body: JSON.stringify({ profile }),
  })
}

export function runDreamPass(days: number = 7): Promise<{ success: boolean; proposal: DreamPassProposal }> {
  return request<{ success: boolean; proposal: DreamPassProposal }>(`/api/radar/profile/dreampass/run?days=${days}`, {
    method: 'POST',
  })
}

export function getLatestDreamPass(status?: string): Promise<{ success: boolean; proposal: DreamPassProposal | null }> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  return request<{ success: boolean; proposal: DreamPassProposal | null }>(`/api/radar/profile/dreampass/latest${qs}`)
}

export function applyDreamPass(proposalId: number): Promise<{ success: boolean; message: string; profile: string }> {
  return request<{ success: boolean; message: string; profile: string }>(`/api/radar/profile/dreampass/${proposalId}/apply`, {
    method: 'POST',
  })
}

export function dismissDreamPass(proposalId: number): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>(`/api/radar/profile/dreampass/${proposalId}/dismiss`, {
    method: 'POST',
  })
}

/* ---------------- Hard Rules Engine ---------------- */

export interface HardRule {
  id: number
  name: string
  field: 'url' | 'domain' | 'title' | 'source_type' | 'content' | string
  operator: 'contains' | 'equals' | 'startswith' | 'endswith' | 'regex' | string
  value: string
  action_type: 'add_tag' | 'set_category' | 'star' | 'archive' | 'mute' | string
  action_value: string
  priority: number
  is_active: number
  created_at: string
  updated_at: string
}

export function getRules(activeOnly: boolean = false): Promise<HardRule[]> {
  return request<HardRule[]>(`/api/rules${activeOnly ? '?active_only=true' : ''}`)
}

export function createRule(rule: Partial<HardRule>): Promise<{ success: boolean; rule: HardRule }> {
  return request<{ success: boolean; rule: HardRule }>('/api/rules', {
    method: 'POST',
    body: JSON.stringify(rule),
  })
}

export function updateRule(ruleId: number, patch: Partial<HardRule>): Promise<{ success: boolean; rule: HardRule }> {
  return request<{ success: boolean; rule: HardRule }>(`/api/rules/${ruleId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  })
}

export function deleteRule(ruleId: number): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>(`/api/rules/${ruleId}`, {
    method: 'DELETE',
  })
}

export function testRule(sampleItem: Record<string, unknown>): Promise<{
  matched_rules: string[]
  changes: Record<string, { before: unknown; after: unknown }>
  result_item: Record<string, unknown>
}> {
  return request('/api/rules/test', {
    method: 'POST',
    body: JSON.stringify(sampleItem),
  })
}

/* ---------------- Session Bridge ---------------- */

export type SessionPlatformId = 'instagram' | 'facebook' | 'google' | 'x'

export interface SessionPlatformStatus {
  id: SessionPlatformId
  connected: boolean
  cookies: number
}

export interface SessionBridgeSnapshot {
  mode: 'cdp' | 'cookiefile' | 'none' | 'unknown'
  cdp_port?: number
  cdp_reachable?: boolean
  auto_launch?: boolean
  profile_dir?: string
  cookie_file?: string
  cookie_file_exists?: boolean
  total_cookies: number
  platforms: SessionPlatformStatus[]
}

export function getSessionStatus(): Promise<{ bridge: SessionBridgeSnapshot }> {
  return request<{ bridge: SessionBridgeSnapshot }>('/api/session/status')
}

export function openPlatformLogin(platform: SessionPlatformId): Promise<{ success: boolean; url: string }> {
  return request('/api/session/login', { method: 'POST', body: JSON.stringify({ platform }) })
}

export function refreshSession(): Promise<{ bridge: SessionBridgeSnapshot }> {
  return request('/api/session/refresh', { method: 'POST' })
}

/* ---------------- Watch & Proposals (Local Proposal Engine) ---------------- */

export interface WatchToggleMap {
  filenames: boolean
  readme: boolean
  deps: boolean
  code: boolean
  git: boolean
}

export interface OutboundToggleMap {
  summary: boolean
  docs: boolean
  deps: boolean
  code: boolean
  git: boolean
}

export type WatchPreset = 'open' | 'balanced' | 'strict' | 'custom'

export interface WatchTarget {
  id: string
  name: string
  target_type: string
  path: string
  preset: WatchPreset
  read_scope: WatchToggleMap
  outbound_consent: OutboundToggleMap
  is_active: boolean
  last_scan_at?: string | null
  fingerprint_item_id?: string | null
  fingerprint_version?: string | null
  created_at?: string
}

export interface Proposal {
  id: string
  item_id: string
  target_id?: string | null
  proposal_type: string
  impact: number
  confidence: number
  effort: number
  user_impact?: number | null
  user_confidence?: number | null
  user_effort?: number | null
  status: 'pending' | 'approved' | 'dismissed'
  title_l1?: string
  summary_l1?: string
  deep_analysis?: string
  created_at?: string
}

export interface BackupRun {
  id: string
  sink: string
  status: string
  file_path?: string
  size_bytes?: number
  error?: string
  created_at: string
}

export interface BackupStatus {
  sink: string
  backup_dir: string
  keep: number
  backup_hour: number
  runs: BackupRun[]
}

export function getWatchTargets(): Promise<WatchTarget[]> {
  return request('/api/watch/targets')
}

export function createWatchTarget(payload: {
  name: string
  path: string
  target_type?: string
  preset?: WatchPreset
  read_scope?: Partial<WatchToggleMap>
  outbound_consent?: Partial<OutboundToggleMap>
}): Promise<WatchTarget> {
  return request('/api/watch/targets', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateWatchTarget(id: string, payload: Partial<{
  name: string
  path: string
  preset: WatchPreset
  read_scope: Partial<WatchToggleMap>
  outbound_consent: Partial<OutboundToggleMap>
  is_active: boolean
}>): Promise<WatchTarget> {
  return request(`/api/watch/targets/${id}`, { method: 'PATCH', body: JSON.stringify(payload) })
}

export function deleteWatchTarget(id: string): Promise<{ success: boolean }> {
  return request(`/api/watch/targets/${id}`, { method: 'DELETE' })
}

export function scanWatchTarget(id: string): Promise<{ success: boolean }> {
  return request(`/api/watch/targets/${id}/scan`, { method: 'POST' })
}

export function getProposals(status?: string): Promise<Proposal[]> {
  return request(`/api/watch/proposals${status ? `?status=${status}` : ''}`)
}

export function decideProposal(id: string, payload: {
  status: 'approved' | 'dismissed'
  user_impact?: number
  user_confidence?: number
  user_effort?: number
  reason?: string
}): Promise<Proposal> {
  return request(`/api/watch/proposals/${id}/decide`, { method: 'POST', body: JSON.stringify(payload) })
}

export function getBackupStatus(): Promise<BackupStatus> {
  return request('/api/watch/backup/status')
}

export function runBackupNow(): Promise<{ success: boolean }> {
  return request('/api/watch/backup/run', { method: 'POST' })
}

/* ---------------- Behavior events & swipe deck (P1) ---------------- */

export interface BehaviorEventPayload {
  event_type: string
  item_id?: string
  proposal_id?: string
  meta?: Record<string, unknown>
}

export function logBehaviorEvent(payload: BehaviorEventPayload): Promise<{ success: boolean }> {
  return request('/api/behavior/event', { method: 'POST', body: JSON.stringify({ ...payload, source: 'pwa' }) })
}

export function getBehaviorStats(days = 7): Promise<{ total_events: number; window_days: number; by_type: Record<string, number> }> {
  return request(`/api/behavior/stats?days=${days}`)
}

/* ---------------- Bookmark Importer ---------------- */

export interface BookmarkImportResult {
  success: boolean
  total_parsed: number
  imported_count: number
  queued_count: number
  skipped_count: number
  errors: string[]
  sample_ids: string[]
}

export function importBookmarks(
  content: string,
  options?: { filename?: string; enqueue_ai?: boolean; default_category?: string }
): Promise<BookmarkImportResult> {
  return request<BookmarkImportResult>('/api/items/import/bookmarks', {
    method: 'POST',
    body: JSON.stringify({
      content,
      filename: options?.filename || 'bookmarks.html',
      enqueue_ai: options?.enqueue_ai ?? false,
      default_category: options?.default_category || 'Inbox',
    }),
  })
}

/* ---------------- Localhost Auto-Auth ---------------- */

export interface LocalAuthResult {
  authenticated: boolean
  api_key: string
}

export async function checkLocalAuth(): Promise<LocalAuthResult> {
  try {
    const res = await fetch('/api/session/local-auth')
    if (!res.ok) return { authenticated: false, api_key: '' }
    return await res.json()
  } catch {
    return { authenticated: false, api_key: '' }
  }
}
