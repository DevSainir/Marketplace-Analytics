import MockAdapter from 'axios-mock-adapter'

import apiClient from '@/core/api/axios'
import {
  fetchSkuClusters,
  fetchSkuPositionCheck,
  startSkuPositionCheck,
} from '@/modules/monitoring/api'

let mock

beforeEach(() => {
  mock = new MockAdapter(apiClient)
})

afterEach(() => {
  mock.restore()
})

describe('startSkuPositionCheck', () => {
  it('queues the check and returns the normalised phrase', async () => {
    // The check is a task now: WB refuses roughly every second attempt and the
    // retries take minutes, so nothing is held open waiting for an answer.
    let captured
    mock.onPost('/v1/monitoring/skus/251034871/search-position/checks').reply((config) => {
      captured = config
      return [202, { task_id: 'check-1', query: 'носки мужские' }]
    })

    const queued = await startSkuPositionCheck(251034871, '  носки   мужские ')

    expect(captured.params.query).toBe('  носки   мужские ')
    expect(queued).toEqual({ task_id: 'check-1', query: 'носки мужские' })
  })
})

describe('fetchSkuPositionCheck', () => {
  it('reports null when this SKU has no check on record', async () => {
    // Asked on every mount, including the first: a bare null must not read as an
    // error, or the panel shows a failure where nothing has happened.
    mock.onGet('/v1/monitoring/skus/7/search-position/checks').reply(200, null)

    expect(await fetchSkuPositionCheck(7)).toBeNull()
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
