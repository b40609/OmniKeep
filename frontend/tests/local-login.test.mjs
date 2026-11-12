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
  // Every way of saving (a block's button, a switch, 重設) goes through one guard.
  const form = await read('composables/useSettingsForm.ts')
  assert.match(form, /turnsLocalLoginOff\(byKey\.value\.get\(LOCAL_LOGIN_KEY\), values, reset\)/)
  assert.match(form, /localLoginPending\.value = \{ values, reset \}\s+return false/)
  const page = await read('components/settings/SettingsPage.vue')
  assert.match(page, /複製存取金鑰/)
  assert.match(page, /配對碼/)
  assert.match(page, /:open="!!form\.localLoginPending\.value"/)
  assert.match(page, /@confirm="confirmLocalLogin"/)
  // Closing the question without confirming saves nothing.
  assert.match(page, /if \(!open\) cancelLocalLogin\(\)/)
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
  assert.deepEqual(users, ['SettingsPage.vue'])
})
