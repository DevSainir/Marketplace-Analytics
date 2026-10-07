import { describeDetail } from '@/modules/monitoring/detailState'

const idle = { loading: false, error: null, notFound: null }

describe('describeDetail', () => {
  it('leaves a card on screen in place through a reload and a failed one', () => {
    // The card dims under the busy bar and a failure is a line above it;
    // neither may replace the figures with a placeholder.
    const product = { nm_id: 1 }

    expect(
      describeDetail({ windowTooWide: false, product, store: { ...idle, loading: true } }),
    ).toBeNull()
    expect(
      describeDetail({ windowTooWide: false, product, store: { ...idle, error: 'x' } }),
    ).toBeNull()
  })

  it('shows a first load in place of the card that is not there yet', () => {
    const state = describeDetail({
      windowTooWide: false,
      product: null,
      store: { ...idle, loading: true },
    })

    expect(state).toEqual({ kind: 'loading' })
  })

  it('states the window bound first, as a bound rather than a failure', () => {
    const state = describeDetail({
      windowTooWide: true,
      product: null,
      store: { ...idle, error: 'x' },
    })

    expect(state.kind).toBe('empty')
  })
})
