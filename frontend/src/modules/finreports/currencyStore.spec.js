import { createPinia, setActivePinia } from 'pinia'

import { fetchSettlementCurrency } from '@/modules/finreports/api'
import { useCurrencyStore } from '@/modules/finreports/currencyStore'

vi.mock('@/modules/finreports/api', () => ({ fetchSettlementCurrency: vi.fn() }))

beforeEach(() => {
  setActivePinia(createPinia())
  vi.mocked(fetchSettlementCurrency).mockReset()
})

describe('useCurrencyStore', () => {
  it('asks the backend once, however many pages want the unit', async () => {
    // The matrix, the chart and the A/Б summary all ask on the same page load.
    vi.mocked(fetchSettlementCurrency).mockResolvedValue('KGS')
    const store = useCurrencyStore()

    await Promise.all([store.ensureLoaded(), store.ensureLoaded()])
    await store.ensureLoaded()

    expect(store.currency).toBe('KGS')
    expect(fetchSettlementCurrency).toHaveBeenCalledTimes(1)
  })

  it('leaves no unit when the request fails, and lets the next page retry', async () => {
    // Rejecting would take down the page that asked; a bare number does not.
    vi.mocked(fetchSettlementCurrency)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce('KGS')
    const store = useCurrencyStore()

    await store.ensureLoaded()
    const afterFailure = store.currency
    await store.ensureLoaded()

    expect(afterFailure).toBe('')
    expect(store.currency).toBe('KGS')
  })
})
