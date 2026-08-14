import MockAdapter from 'axios-mock-adapter'

import apiClient from '@/core/api/axios'
import { fetchSkuClusters, probeSkuSearchPosition } from '@/modules/monitoring/api'

let mock

beforeEach(() => {
  mock = new MockAdapter(apiClient)
})

afterEach(() => {
  mock.restore()
})

describe('probeSkuSearchPosition', () => {
  it('outruns the default 15s budget — a cold scan legitimately takes longer', async () => {
    // Regression: the probe walks up to three ranked pages sequentially against a
    // host that throttles per IP, so an uncached check routinely passed 15s and
    // surfaced as «timeout of 15000ms exceeded» — while the backend went on to
    // finish the scan and cache it, making the very next attempt look instant.
    let captured
    mock.onGet('/v1/monitoring/skus/251034871/search-position').reply((config) => {
      captured = config
      return [200, { nm_id: 251034871, query: 'носки', position: 42 }]
    })

    await probeSkuSearchPosition(251034871, 'носки')

    expect(captured.timeout).toBeGreaterThan(15000)
  })

  it('asks WB again only when refresh is requested', async () => {
    // `refresh` costs WB rate budget, so it must never ride along by default:
    // the param is omitted entirely rather than sent as false.
    const seen = []
    mock.onGet('/v1/monitoring/skus/7/search-position').reply((config) => {
      seen.push(config.params)
      return [200, {}]
    })

    await probeSkuSearchPosition(7, 'носки')
    await probeSkuSearchPosition(7, 'носки', { refresh: true })

    expect(seen[0].refresh).toBeUndefined()
    expect(seen[1].refresh).toBe(true)
  })
})

describe('fetchSkuClusters', () => {
  it('keeps the stored half on the shared budget — it answers from indexed rows', async () => {
    // The two halves of the panel are split precisely so a throttled WB cannot
    // delay this one; giving it a probe-sized timeout would hide a slow query.
    let captured
    mock.onGet('/v1/monitoring/skus/251034871/clusters').reply((config) => {
      captured = config
      return [200, { nm_id: 251034871, items: [] }]
    })

    await fetchSkuClusters(251034871, { limit: 50 })

    expect(captured.timeout).toBeLessThanOrEqual(15000)
  })
})
