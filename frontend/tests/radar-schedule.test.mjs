import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

const source = await readFile(new URL('../src/lib/radarSchedule.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
})
const { radarScheduleNote } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)

const saved = (patch) => ({
  enabled: true, interval_minutes: 180, max_analyze_per_cycle: 3, notification_mode: 'silent',
  daily_digest_hour: 8, vip_threshold: 4, scheduler_running: true, ...patch,
})
const sources = [{ id: 1, is_active: 1 }, { id: 2, is_active: 0 }, { id: 3, is_active: 1 }]

test('says what the radar is really doing once settings are loaded', () => {
  assert.equal(radarScheduleNote(null, sources), null)
  assert.deepEqual(radarScheduleNote(saved({}), sources), { tone: 'ok', text: '目前：開啟，每 3 小時檢查 2 個來源。' })
  assert.equal(radarScheduleNote(saved({ interval_minutes: 90 }), sources).text, '目前：開啟，每 90 分鐘檢查 2 個來源。')
  assert.equal(radarScheduleNote(saved({ enabled: false }), sources).tone, 'off')
  assert.match(radarScheduleNote(saved({ interval_minutes: 0 }), sources).text, /手動檢查/)
})

test('warns when switching on would not scan anything', () => {
  const none = radarScheduleNote(saved({}), sources.map((s) => ({ ...s, is_active: 0 })))
  assert.equal(none.tone, 'warn')
  assert.match(none.text, /沒有啟用中的來源/)
  // A server with background services off cannot honour the toggle at all.
  const stopped = radarScheduleNote(saved({ scheduler_running: false }), sources)
  assert.equal(stopped.tone, 'warn')
  assert.match(stopped.text, /BACKGROUND_SERVICES_ENABLED=false/)
})
