import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import ts from 'typescript'

async function load(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8')
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  })
  return import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
}

const { onceAtATime } = await load('../src/lib/localRetry.ts')

test('requests that fail together share one sign-in attempt', async () => {
  let calls = 0
  let finish
  const retry = onceAtATime(() => { calls++; return new Promise((resolve) => { finish = resolve }) })
  const first = retry()
  const second = retry()
  finish(true)
  assert.equal(await first, true)
  assert.equal(await second, true)
  assert.equal(calls, 1)
})

test('the next time the key stops working it tries again', async () => {
  let calls = 0
  const retry = onceAtATime(async () => { calls++; return true })
  await retry()
  await retry()
  assert.equal(calls, 2)
})

test('a failed attempt counts as not signed in', async () => {
  const retry = onceAtATime(async () => { throw new Error('offline') })
  assert.equal(await retry(), false)
})

test('a key that stops working on this machine tries the local sign-in before the login box', async () => {
  const app = await readFile(new URL('../src/App.vue', import.meta.url), 'utf8')
  const handler = app.slice(app.indexOf('async function onAuthRequired'))
  assert.match(handler, /requireLogin\(true\)\s*\n\s*await retryLocalSignIn\(\)/)
  assert.match(app, /const retryLocalSignIn = onceAtATime\([\s\S]*?checkLocalAuth\(\)/)
})
