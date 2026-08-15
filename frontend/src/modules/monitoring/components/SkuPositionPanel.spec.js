import { mount } from '@vue/test-utils'

import SkuPositionPanel from '@/modules/monitoring/components/SkuPositionPanel.vue'

const POSITION = {
  nm_id: 953770957,
  query: 'носки',
  normalized_query: 'мужские носки',
  checked_at: '2026-08-14T09:00:00Z',
  total_found: 111119,
  positions_scanned: 300,
  truncated: true,
  position: 7,
  page: 1,
  position_on_page: 7,
  other_skus: [{ nm_id: 144178006, vendor_code: 'M-TRX01-BEJ', position: 41 }],
}

const PIN = {
  keyword: 'штаны бананы мужские',
  normalized_query: 'бананы мужские штаны',
  position: 26,
  positions_scanned: 300,
  total_found: 7486,
  truncated: true,
  checked_at: '2026-08-15T13:37:00Z',
  created_at: '2026-08-15T10:00:00Z',
}

const mountPanel = (props = {}) => mount(SkuPositionPanel, { props })

it('reports the live rank with its page and WB’s own phrasing', () => {
  const wrapper = mountPanel({ position: POSITION })

  expect(wrapper.text()).toContain('7')
  expect(wrapper.text()).toContain('мужские носки')
  expect(wrapper.text()).toContain('M-TRX01-BEJ')
})

it('names the scanned depth when the SKU did not rank inside it', () => {
  // A SKU can rank deeper than the probe looks, so the empty state states the
  // depth instead of implying the SKU is absent from WB.
  const wrapper = mountPanel({ position: { ...POSITION, position: null, page: null } })

  expect(wrapper.text()).toContain('не найден в первых 300')
})

it('says WB did not answer instead of reporting the SKU as unranked', () => {
  // The panel's central rule: «не проверилось» and «нет в выдаче» lead a seller
  // to opposite decisions about the bid.
  const wrapper = mountPanel({ positionError: 'WB притормозил запрос. Повторите через минуту.' })

  expect(wrapper.text()).toContain('притормозил')
  expect(wrapper.text()).not.toContain('не найден в первых')
})

it('emits the typed phrase on submit and never an empty one', async () => {
  const wrapper = mountPanel()

  await wrapper.get('form').trigger('submit')
  await wrapper.get('input').setValue('носки')
  await wrapper.get('form').trigger('submit')

  expect(wrapper.emitted('check')).toEqual([['носки']])
})

it('pins the typed phrase and clears the field', async () => {
  // Leaving the phrase in the input after pinning invites pinning it twice, and
  // the card is now where that phrase lives.
  const wrapper = mountPanel()

  await wrapper.get('input').setValue('штаны бананы')
  const pinButton = wrapper.findAll('button').find((b) => b.text() === 'Закрепить')
  await pinButton.trigger('click')

  expect(wrapper.emitted('pin')).toEqual([['штаны бананы']])
  expect(wrapper.get('input').element.value).toBe('')
})

it('shows a pinned card with its position and the date it was taken', () => {
  // A rank with no timestamp is not actionable: the pin is re-probed three times
  // a day, so which run produced the number is part of the number.
  const wrapper = mountPanel({ pins: [PIN] })

  expect(wrapper.text()).toContain('штаны бананы мужские')
  expect(wrapper.text()).toContain('26')
  expect(wrapper.text()).toContain('Дата обновления')
})

it('distinguishes a pin never checked from one checked and not found', () => {
  // Two states that look identical if collapsed and mean opposite things.
  const fresh = mountPanel({ pins: [{ ...PIN, position: null, checked_at: null }] })
  const missing = mountPanel({ pins: [{ ...PIN, position: null }] })

  expect(fresh.text()).toContain('Ещё не проверялся')
  expect(missing.text()).toContain('вне первых 300')
})

it('disables «Проверить все позиции» while a run is in flight', () => {
  // A second run would only be refused by the backend's lock, with no way for
  // the seller to know why.
  const wrapper = mountPanel({ refreshingAll: true, refreshMessage: 'Проверяем 3 запроса.' })

  expect(wrapper.get('button').attributes('disabled')).toBeDefined()
  expect(wrapper.text()).toContain('Проверяем 3 запроса.')
})
