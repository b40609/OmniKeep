import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

const { SETTINGS_SECTIONS, resolveSettingsTarget, sectionOfGroup } = await load('lib/settingsSections.ts')
const { EXPERIMENTS, readExperiments, experimentsSupported, blockedShortcut } = await load('lib/experiments.ts')

test('settings are six groups by purpose, then the experimental features', () => {
  assert.deepEqual(SETTINGS_SECTIONS.map((s) => s.id),
    ['general', 'channels', 'ai', 'notifications', 'data', 'advanced', 'labs'])
  for (const section of SETTINGS_SECTIONS) assert.ok(section.label && section.lead, section.id)
})

test('links made for the older tabs land in the group that now holds them', () => {
  assert.deepEqual(resolveSettingsTarget('ai'), { section: 'ai', block: '' })
  assert.deepEqual(resolveSettingsTarget('brain'), { section: 'ai', block: 'ask' })
  assert.deepEqual(resolveSettingsTarget('profile'), { section: 'general', block: 'profile' })
  assert.deepEqual(resolveSettingsTarget('telegram'), { section: 'channels', block: 'telegram' })
  assert.deepEqual(resolveSettingsTarget('line'), { section: 'channels', block: 'line' })
  assert.deepEqual(resolveSettingsTarget('github'), { section: 'channels', block: 'github' })
  assert.deepEqual(resolveSettingsTarget('backup'), { section: 'data', block: 'backup' })
  assert.deepEqual(resolveSettingsTarget('push'), { section: 'notifications', block: '' })
  assert.deepEqual(resolveSettingsTarget('system'), { section: 'advanced', block: '' })
})

test('a group id opens that group, and anything unknown opens the first one', () => {
  assert.deepEqual(resolveSettingsTarget('labs'), { section: 'labs', block: '' })
  assert.deepEqual(resolveSettingsTarget('channels', 'sessions'), { section: 'channels', block: 'sessions' })
  assert.deepEqual(resolveSettingsTarget('advanced', 'push-keys'), { section: 'advanced', block: 'push-keys' })
  for (const odd of ['', 'nope', null, undefined]) assert.deepEqual(resolveSettingsTarget(odd), { section: 'general', block: '' })
  assert.equal(sectionOfGroup('telegram'), 'channels')
  assert.equal(sectionOfGroup('labs'), 'labs')
})

const labs = (values) => [{ fields: [{ key: 'PRIMARY_MODEL', value: 'x' }] },
  { fields: EXPERIMENTS.map((e, i) => ({ key: e.key, value: values[i] })) }]

test('experiments are read from the settings the server describes', () => {
  assert.deepEqual(readExperiments(labs([true, false, true])), { radar: true, watch: false, daily: true })
  assert.equal(experimentsSupported(labs([false, false, false])), true)
  // Only a real true counts as on.
  assert.deepEqual(readExperiments(labs(['true', 1, undefined])), { radar: false, watch: false, daily: false })
})

test('a server from before the switches existed reads as everything off', () => {
  const older = [{ fields: [{ key: 'PRIMARY_MODEL', value: 'x' }] }]
  assert.deepEqual(readExperiments(older), { radar: false, watch: false, daily: false })
  assert.equal(experimentsSupported(older), false)
  assert.deepEqual(readExperiments(null), { radar: false, watch: false, daily: false })
  assert.deepEqual(readExperiments([]), { radar: false, watch: false, daily: false })
})

test('each experiment says what it does and what switching it off does not stop', () => {
  assert.deepEqual(EXPERIMENTS.map((e) => e.id), ['radar', 'watch', 'daily'])
  for (const e of EXPERIMENTS) assert.ok(e.label && e.description && e.background, e.id)
  assert.match(EXPERIMENTS[0].background, /背景檢查/)
})

test('shortcut keys belong to their experiment', () => {
  const off = { radar: false, watch: false, daily: false }
  const on = { radar: true, watch: true, daily: true }
  assert.equal(blockedShortcut('r', off), 'radar')
  assert.equal(blockedShortcut('R', off), 'radar')
  assert.equal(blockedShortcut('d', off), 'radar')
  assert.equal(blockedShortcut('D', off), 'daily')
  for (const k of ['r', 'R', 'd', 'D']) assert.equal(blockedShortcut(k, on), null)
  assert.equal(blockedShortcut('D', { ...off, radar: true }), 'daily')
  for (const k of ['n', 'b', 'j', '?', 'Escape']) assert.equal(blockedShortcut(k, off), null)
})
