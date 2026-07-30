import { mount } from '@vue/test-utils'

import CostPriceGrid from '@/modules/finreports/components/CostPriceGrid.vue'

const COSTED = [
  {
    nm_id: 953770957,
    cost: '662.00',
    currency: 'KGS',
    vendor_code: 'M-TRX01-BLK',
    source: 'seed',
    note: '',
    sold_units: 3052,
  },
]

const MISSING = [
  {
    nm_id: 940954338,
    cost: '0',
    currency: '',
    vendor_code: 'm-lnx02-blk',
    source: '',
    note: '',
    sold_units: 2533,
  },
]

function mountGrid(props = {}) {
  return mount(CostPriceGrid, {
    props: { items: COSTED, missing: MISSING, currency: 'KGS', saving: false, ...props },
  })
}

/** Type into the cost field of the row whose vendor code matches. */
async function type(wrapper, vendorCode, value) {
  const row = wrapper.findAll('tbody tr').find((tr) => tr.text().includes(vendorCode))
  const input = row.find('input')
  await input.setValue(value)
}

function saveButton(wrapper) {
  return wrapper.findAll('button').find((b) => b.text().startsWith('Сохранить'))
}

describe('which edits reach the server', () => {
  it('lists uncosted SKUs first, by units settled', () => {
    // The seller's next-best action is always "cost the SKU that sells most".
    const wrapper = mountGrid()

    const first = wrapper.findAll('tbody tr')[0]

    expect(first.text()).toContain('m-lnx02-blk')
  })

  it('saves a cost of zero on a SKU that had none', async () => {
    // `Number(null)` is 0, so comparing a typed "0" against an absent cost with
    // Number() makes them equal and drops the edit. Absent is not zero.
    const wrapper = mountGrid()

    await type(wrapper, 'm-lnx02-blk', '0')
    await saveButton(wrapper).trigger('click')

    const { save, clear } = wrapper.emitted('save')[0][0]
    expect(save).toEqual([
      { nm_id: 940954338, cost: 0, currency: 'KGS', vendor_code: 'm-lnx02-blk' },
    ])
    expect(clear).toEqual([])
  })

  it('treats an emptied field on a costed SKU as a removal', async () => {
    // Otherwise the seller clears the box, presses Save, and the old cost keeps
    // sitting in every margin while the grid shows it as empty.
    const wrapper = mountGrid()

    await type(wrapper, 'M-TRX01-BLK', '')
    await saveButton(wrapper).trigger('click')

    const { save, clear } = wrapper.emitted('save')[0][0]
    expect(save).toEqual([])
    expect(clear).toEqual([953770957])
  })

  it('ignores an emptied field on a SKU that had no cost anyway', async () => {
    const wrapper = mountGrid()

    await type(wrapper, 'm-lnx02-blk', '')

    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('does not resubmit a value equal to what is already stored', async () => {
    const wrapper = mountGrid()

    await type(wrapper, 'M-TRX01-BLK', '662')

    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('counts pending writes and removals together on the button', async () => {
    const wrapper = mountGrid()

    await type(wrapper, 'm-lnx02-blk', '800')
    await type(wrapper, 'M-TRX01-BLK', '')

    expect(saveButton(wrapper).text()).toContain('(2)')
  })

  it('blocks the save on a negative cost', async () => {
    // Accepted, it inverts the margin on every unit of that SKU ever sold.
    const wrapper = mountGrid()

    await type(wrapper, 'm-lnx02-blk', '-5')

    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('неотрицательным числом')
  })

  it('offers the explicit clear only on rows that have a cost', () => {
    const wrapper = mountGrid()

    const clears = wrapper.findAll('button').filter((b) => b.text() === 'Очистить')

    expect(clears).toHaveLength(1)
  })
})
