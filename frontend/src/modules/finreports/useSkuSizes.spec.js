import { nextTick, ref } from 'vue'

import { useSkuSizes } from '@/modules/finreports/useSkuSizes'
import { useExpandedSkus } from '@/modules/finreports/usePnlSkuTable'

/** A fetch whose answers the test releases by hand, in any order. */
function deferredFetch() {
  const pending = []
  const fetch = (nmId, params) =>
    new Promise((resolve, reject) => pending.push({ nmId, params, resolve, reject }))
  return { fetch, pending }
}

describe('useSkuSizes', () => {
  it('drops an answer for a window that was replaced, and leaves nothing spinning', async () => {
    // The endless «Считаем размеры…»: the old code returned early on a stale
    // answer and left the entry at `loading: true`, which is never asked again.
    const window = { from: '2026-09-01', to: '2026-09-07' }
    const { fetch, pending } = deferredFetch()
    const { sizes, load, reset } = useSkuSizes({ period: () => window, fetch })

    load(42)
    reset()
    pending[0].resolve({ rows: ['old window'] })
    await Promise.resolve()

    expect(sizes.value[42]).toBeUndefined()
  })

  it('asks again for an article once the cache is reset', async () => {
    const { fetch, pending } = deferredFetch()
    const { load, reset } = useSkuSizes({
      period: () => ({ from: '2026-09-01', to: '2026-09-07' }),
      fetch,
    })

    load(42)
    reset()
    load(42)

    expect(pending).toHaveLength(2)
  })

  it('keeps one request per article while it is in flight', () => {
    const { fetch, pending } = deferredFetch()
    const { load } = useSkuSizes({
      period: () => ({ from: '2026-09-01', to: '2026-09-07' }),
      fetch,
    })

    load(42)
    load(42)

    expect(pending).toHaveLength(1)
  })

  it('records a failure as an error, not as a row that is still loading', async () => {
    const { fetch, pending } = deferredFetch()
    const { sizes, load } = useSkuSizes({
      period: () => ({ from: '2026-09-01', to: '2026-09-07' }),
      fetch,
    })

    const done = load(42)
    pending[0].reject(new Error('Network Error'))
    await done

    expect(sizes.value[42].loading).toBe(false)
    expect(sizes.value[42].error).not.toBe('')
  })
})

describe('useExpandedSkus', () => {
  it('re-asks for an open article whose sizes were dropped by a reload', async () => {
    // The other half of the spinner: a report reload empties the cache while
    // the row stays open, and asking only on the click left it with nothing.
    const asked = []
    const sizes = ref({})
    const { toggle } = useExpandedSkus(
      (nmId) => asked.push(nmId),
      () => sizes.value,
    )
    toggle(42)
    sizes.value = { 42: { loading: false, error: '', data: {} } }
    await nextTick()
    asked.length = 0

    sizes.value = {}
    await nextTick()

    expect(asked).toEqual([42])
  })
})
