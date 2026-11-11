import assert from 'node:assert/strict'
import { readFile, readdir } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}
const read = (path) => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8')

const { LOCAL_LOGIN_KEY, turnsLocalLoginOff } = await load('lib/localLogin.ts')
const on = { value: true, env_available: false }

test('switching it off while it is on asks first', () => {
  assert.equal(LOCAL_LOGIN_KEY, 'LOCAL_AUTO_LOGIN')
  assert.equal(turnsLocalLoginOff(on, { LOCAL_AUTO_LOGIN: false }, []), true)
  assert.equal(turnsLocalLoginOff(on, { LOCAL_AUTO_LOGIN: false, BACKUP_KEEP: 3 }, ['GITHUB_TOKEN']), true)
})

test('other changes, switching it on, and an already-off switch do not ask', () => {
  assert.equal(turnsLocalLoginOff(on, {}, []), false)
  assert.equal(turnsLocalLoginOff(on, { BACKUP_KEEP: 3 }, ['GITHUB_TOKEN']), false)
  assert.equal(turnsLocalLoginOff(on, { LOCAL_AUTO_LOGIN: true }, []), false)
  assert.equal(turnsLocalLoginOff({ value: false, env_available: true, env_value: false }, { LOCAL_AUTO_LOGIN: true }, []), false)
  assert.equal(turnsLocalLoginOff({ value: false }, { LOCAL_AUTO_LOGIN: false }, []), false)
  assert.equal(turnsLocalLoginOff(undefined, { LOCAL_AUTO_LOGIN: false }, []), false)
})

test('going back to .env asks only when .env says off', () => {
  const overEnvOff = { value: true, env_available: true, env_value: false }
  assert.equal(turnsLocalLoginOff(overEnvOff, {}, ['LOCAL_AUTO_LOGIN']), true)
  // Nothing in .env: the built-in default is on.
  assert.equal(turnsLocalLoginOff(on, {}, ['LOCAL_AUTO_LOGIN']), false)
})

test('the settings page confirms with a way to copy the key before saving', async () => {
  const dialog = await read('components/modals/SettingsDialog.vue')
  assert.match(dialog, /turnsLocalLoginOff\(byKey\.value\.get\(LOCAL_LOGIN_KEY\), pending\.value\.values, pending\.value\.reset\)/)
  assert.match(dialog, /複製存取金鑰/)
  assert.match(dialog, /配對碼/)
  assert.match(dialog, /@click="save\(true\)"/)
  // The 系統 tab is listed once even though the server now describes a group with that id.
  assert.match(dialog, /groups\.filter\(\(g\) => g\.id !== 'system'\)/)
})

test('the key is handed out for copying only, and App.vue alone stores it', async () => {
  const api = await load('lib/api.ts')
  api.setApiKey('synthetic-session-key')
  assert.equal(api.getApiKey(), 'synthetic-session-key')
  api.setApiKey('')
  assert.equal(api.getApiKey(), '')
  const users = []
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const url = new URL(entry.name + (entry.isDirectory() ? '/' : ''), dir)
      if (entry.isDirectory()) await walk(url)
      else if (/\.(vue|ts)$/.test(entry.name) && entry.name !== 'api.ts'
        && (await readFile(url, 'utf8')).includes('getApiKey')) users.push(entry.name)
    }
  }
  await walk(new URL('../src/', import.meta.url))
  assert.deepEqual(users, ['SettingsDialog.vue'])
})
