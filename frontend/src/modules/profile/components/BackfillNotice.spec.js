import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { setWorkspaceId } from '@/core/api/axios'
import { fetchBackfillStatus } from '@/modules/profile/api'
import BackfillNotice from '@/modules/profile/components/BackfillNotice.vue'

vi.mock('@/modules/profile/api', () => ({ fetchBackfillStatus: vi.fn() }))

const lane = (key, state, percent = 40) => ({ lane: key, label: key, state, percent })

async function mountNotice(lanes, status) {
  fetchBackfillStatus.mockResolvedValue(status)
  const wrapper = mount(BackfillNotice, { props: { lanes } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setWorkspaceId('ws-1')
  setActivePinia(createPinia())
})

describe('BackfillNotice', () => {
  it('says the history is still loading for the lanes the page is built on', async () => {
    // A new workspace's page was simply empty for the day the backfill runs,
    // which read as a broken service.
    const wrapper = await mountNotice(['pnl'], {
      active: true,
      lanes: [lane('pnl', 'running', 42)],
    })

    expect(wrapper.text()).toContain('Загружаем историю из WB')
    expect(wrapper.text()).toContain('42 %')
  })

  it('stays silent about lanes another page is built on', async () => {
    const wrapper = await mountNotice(['pnl'], {
      active: true,
      lanes: [lane('funnel', 'running'), lane('pnl', 'done', 100)],
    })

    expect(wrapper.text()).toBe('')
  })
})
