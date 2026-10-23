import MockAdapter from 'axios-mock-adapter'

import apiClient from '@/core/api/axios'
import { downloadCostPricesXlsx, importCostPricesXlsx } from '@/modules/finreports/api'

let mock

beforeEach(() => {
  mock = new MockAdapter(apiClient)
})

afterEach(() => {
  mock.restore()
})

describe('importCostPricesXlsx', () => {
  it('sends the file as intact multipart, not JSON-serialized', async () => {
    // Regression guard: the shared client defaults to application/json, and
    // axios reacts to that by turning a FormData into JSON — dropping the file,
    // which the backend then rejects as "Field required". The body reaching the
    // adapter must still be a FormData carrying the file.
    let captured
    mock.onPost('/v1/finreports/cost-prices/import').reply((config) => {
      captured = config
      return [200, { applied: 1, skipped: 0, issues: [] }]
    })

    const file = new File(['xlsx-bytes'], 'costs.xlsx')
    const result = await importCostPricesXlsx(file)

    expect(captured.data).toBeInstanceOf(FormData)
    expect(captured.data.get('file')).toBe(file)
    expect(String(captured.headers['Content-Type'])).not.toContain('application/json')
    expect(result).toEqual({ applied: 1, skipped: 0, issues: [] })
  })
})

describe('downloadCostPricesXlsx', () => {
  it('requests a blob and decodes the RFC 5987 non-ASCII filename', async () => {
    const encoded = encodeURIComponent('Ωμέγα κόστος.xlsx')
    mock.onGet('/v1/finreports/cost-prices/export').reply(200, new Blob(['xlsx']), {
      'content-disposition': `attachment; filename="cost-prices.xlsx"; filename*=UTF-8''${encoded}`,
    })

    const { blob, filename } = await downloadCostPricesXlsx()

    expect(blob).toBeInstanceOf(Blob)
    expect(filename).toBe('Ωμέγα κόστος.xlsx')
  })

  it('falls back to the ASCII filename when there is no filename*', async () => {
    mock.onGet('/v1/finreports/cost-prices/export').reply(200, new Blob(['xlsx']), {
      'content-disposition': 'attachment; filename="cost-prices.xlsx"',
    })

    const { filename } = await downloadCostPricesXlsx()

    expect(filename).toBe('cost-prices.xlsx')
  })
})
