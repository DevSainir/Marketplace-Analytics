/**
 * The reload that follows a deploy must land on the page the person clicked,
 * not the one they clicked from.
 *
 * A real router over a memory history; the lazy route fails the way a built
 * app does in a tab opened before the deploy — Vite's preload helper fires
 * `vite:preloadError` and, when that is cancelled, resolves the import empty.
 */
import { createMemoryHistory, createRouter } from 'vue-router'

import { RELOADED_FOR_STALE_ASSETS, installStaleAssetReload } from '@/core/router/staleAssets'

const Blank = { template: '<div />' }

class FakeLocation {
  assigned = []
  reloads = 0
  assign(href) {
    this.assigned.push(href)
  }
  reload() {
    this.reloads += 1
  }
}

class FakeStorage {
  items = new Map()
  getItem(key) {
    return this.items.get(key) ?? null
  }
  setItem(key, value) {
    this.items.set(key, String(value))
  }
  removeItem(key) {
    this.items.delete(key)
  }
}

/** What Vite's preload helper does when a chunk of the old build is gone. */
function staleChunk(events) {
  return () => {
    const event = new Event('vite:preloadError', { cancelable: true })
    event.payload = new Error('Unable to preload CSS for /assets/Old-abc123.css')
    events.dispatchEvent(event)
    if (!event.defaultPrevented) return Promise.reject(event.payload)
    return Promise.resolve(undefined)
  }
}

async function setup() {
  const events = new EventTarget()
  const location = new FakeLocation()
  const storage = new FakeStorage()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/monitoring', component: Blank },
      { path: '/finreports', component: staleChunk(events) },
      { path: '/summary', component: Blank },
    ],
  })
  router.onError(() => {}) // the failed navigation's own rejection, not under test
  installStaleAssetReload(router, { storage, location, events })
  await router.push('/monitoring')
  return { router, location, storage, events }
}

describe('a stale chunk on navigation', () => {
  it('loads the target page from scratch, not the current one', async () => {
    const { router, location } = await setup()

    await router.push('/finreports?period=week').catch(() => {})

    expect(location.assigned).toEqual(['/finreports?period=week'])
    expect(location.reloads).toBe(0)
  })

  it('tries only once, then lets the error through', async () => {
    const { router, location } = await setup()
    await router.push('/finreports').catch(() => {})

    // The fresh page's first navigation failed too: a broken build, not a stale tab.
    const failure = await router.push('/finreports').catch((error) => error)

    expect(location.assigned).toEqual(['/finreports'])
    expect(failure).toBeInstanceOf(Error)
  })

  it('gives the next deploy its own reload after a successful navigation', async () => {
    const { router, location, storage } = await setup()
    await router.push('/finreports').catch(() => {})

    await router.push('/summary')
    await router.push('/finreports').catch(() => {})

    expect(storage.getItem(RELOADED_FOR_STALE_ASSETS)).toBe('1')
    expect(location.assigned).toEqual(['/finreports', '/finreports'])
  })
})

describe('a stale chunk outside a navigation', () => {
  it('reloads the current page', async () => {
    const { location, events } = await setup()

    staleChunk(events)()

    expect(location.reloads).toBe(1)
    expect(location.assigned).toEqual([])
  })
})
