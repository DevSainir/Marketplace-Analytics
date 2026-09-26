import { createPinia, setActivePinia } from 'pinia'
import { nextTick, ref } from 'vue'

import { fetchSkuClusters } from '@/modules/monitoring/api'
import { useMonitoringStore } from '@/modules/monitoring/store'
import { useSkuClusters } from '@/modules/monitoring/useSkuClusters'

vi.mock('@/modules/monitoring/api', () => ({
  fetchSkuClusters: vi.fn(),
}))

const PRODUCT = { nm_id: 953770957, window: { start: '2026-08-01', end: '2026-08-13' } }

let monitoring

beforeEach(() => {
  setActivePinia(createPinia())
  monitoring = useMonitoringStore()
  vi.clearAllMocks()
  fetchSkuClusters.mockResolvedValue({ nm_id: PRODUCT.nm_id, window: PRODUCT.window, items: [] })
})

describe('the per-кабинет cluster switch', () => {
  it('fetches nothing for a кабинет with the block switched off', async () => {
    useSkuClusters(() => false)

    monitoring.currentProduct = PRODUCT
    await nextTick()

    expect(fetchSkuClusters).not.toHaveBeenCalled()
  })

  it('loads the open SKU’s clusters for a кабинет with the block on', async () => {
    useSkuClusters(() => true)

    monitoring.currentProduct = PRODUCT
    await nextTick()

    expect(fetchSkuClusters).toHaveBeenCalledWith(
      PRODUCT.nm_id,
      { date_from: '2026-08-01', date_to: '2026-08-13' },
      expect.anything(),
    )
  })

  it('starts loading once a late workspace list turns the switch on', async () => {
    // The workspace list and the SKU detail load independently, so the flag
    // can arrive after the SKU is already on screen.
    const enabled = ref(false)
    useSkuClusters(() => enabled.value)
    monitoring.currentProduct = PRODUCT
    await nextTick()

    enabled.value = true
    await nextTick()

    expect(fetchSkuClusters).toHaveBeenCalledTimes(1)
  })
})
