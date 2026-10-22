import { mount } from '@vue/test-utils'

import AbTestsTable from '@/modules/abTests/components/AbTestsTable.vue'

function row(overrides = {}) {
  return {
    id: 'aaaaaaaa-0000-7000-8000-000000000001',
    nm_id: 995716075,
    vendor_code: 'ДЕТ_ПЛАТЬЕ',
    name: 'Тест главного фото',
    status: 'draft',
    variant_count: 2,
    started_at: null,
    finished_at: null,
    created_at: '2026-09-04T10:00:00Z',
    ...overrides,
  }
}

function table(rows) {
  return mount(AbTestsTable, {
    props: { rows },
    global: { stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('a test can be deleted from the list', () => {
  it('asks once before emitting the delete', async () => {
    // The API and the store could always delete; the list simply had no button,
    // so a test created by mistake stayed for good. The confirm is in the row
    // rather than a modal, so it cannot be aimed at the wrong test.
    const wrapper = table([row()])

    await wrapper.get('[data-testid="delete-test"]').trigger('click')

    expect(wrapper.get('[data-testid="delete-test"]').text()).toBe('Really delete?')
    expect(wrapper.emitted('delete')).toBeUndefined()

    await wrapper.get('[data-testid="delete-test"]').trigger('click')

    expect(wrapper.emitted('delete')).toEqual([['aaaaaaaa-0000-7000-8000-000000000001']])
  })

  it('disarms the first row when a second one is armed', async () => {
    // Two rows both reading "Really delete?" is an invitation to delete the
    // wrong test with the next click.
    const wrapper = table([row(), row({ id: 'bbbb', name: 'Второй' })])
    const buttons = wrapper.findAll('[data-testid="delete-test"]')

    await buttons[0].trigger('click')
    await buttons[1].trigger('click')

    expect(buttons[0].text()).toBe('Delete')
    expect(buttons[1].text()).toBe('Really delete?')
    expect(wrapper.emitted('delete')).toBeUndefined()
  })
})
