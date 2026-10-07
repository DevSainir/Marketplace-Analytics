import { mount } from '@vue/test-utils'

import DataState from '@/core/components/DataState.vue'

describe('DataState', () => {
  it('says what failed and why, in one look on every page', () => {
    const wrapper = mount(DataState, { props: { kind: 'error', text: 'Нет связи с сервером.' } })

    expect(wrapper.text()).toContain('Не удалось загрузить')
    expect(wrapper.text()).toContain('Нет связи с сервером.')
  })

  it('reports a failure above figures that stay, without claiming a load failed', () => {
    // The same line carries a failed save (a balance mark, an exclusion), so
    // it gives the reason only.
    const wrapper = mount(DataState, {
      props: { kind: 'error', layout: 'line', text: 'Не удалось сохранить отметку' },
    })

    expect(wrapper.text()).toBe('Не удалось сохранить отметку')
  })

  it('uses the one wording for an empty period unless the page has its own', () => {
    expect(mount(DataState, { props: { kind: 'empty' } }).text()).toBe(
      'Нет данных за выбранный период',
    )
  })

  it('says «Загружаем…» for every first load', () => {
    expect(mount(DataState, { props: { kind: 'loading' } }).text()).toContain('Загружаем…')
  })
})
