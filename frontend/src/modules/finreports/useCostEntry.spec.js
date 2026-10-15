import { saveCostPrices } from '@/modules/finreports/api'
import { useCostEntry } from '@/modules/finreports/useCostEntry'

vi.mock('@/modules/finreports/api', () => ({ saveCostPrices: vi.fn() }))

/** The store surface the composable touches, and nothing else. */
function fakeStore(report = { currency: 'KGS' }) {
  return { report, costPrices: { items: [], missing: [{ nm_id: 111 }] }, loadReport: vi.fn() }
}

beforeEach(() => vi.clearAllMocks())

describe('useCostEntry', () => {
  it('saves one cost in the statement currency, then re-reads the statement', async () => {
    const store = fakeStore()

    await useCostEntry(store).save({ nmId: 111, cost: 795.5, vendorCode: 'no-cost' })

    expect(saveCostPrices).toHaveBeenCalledWith([
      { nm_id: 111, cost: 795.5, vendor_code: 'no-cost', currency: 'KGS' },
    ])
    expect(store.loadReport).toHaveBeenCalled()
  })

  it('drops the editor list so it cannot still show the article as missing', async () => {
    const store = fakeStore()

    await useCostEntry(store).save({ nmId: 111, cost: 1, vendorCode: '' })

    expect(store.costPrices).toBeNull()
  })

  it('leaves the currency to the backend when the window settled nothing', async () => {
    await useCostEntry(fakeStore({ currency: '' })).save({ nmId: 1, cost: 1, vendorCode: '' })

    expect(saveCostPrices.mock.calls[0][0][0]).not.toHaveProperty('currency')
  })

  it('throws a refused save and keeps the statement as it was', async () => {
    saveCostPrices.mockRejectedValueOnce(new Error('422'))
    const store = fakeStore()

    await expect(useCostEntry(store).save({ nmId: 1, cost: 1, vendorCode: '' })).rejects.toThrow()
    expect(store.loadReport).not.toHaveBeenCalled()
  })
})
