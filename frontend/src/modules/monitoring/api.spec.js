import MockAdapter from 'axios-mock-adapter'

import apiClient from '@/core/api/axios'
import { fetchSkuClusters } from '@/modules/monitoring/api'

let mock

beforeEach(() => {
  mock = new MockAdapter(apiClient)
})

afterEach(() => {
  mock.restore()
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
