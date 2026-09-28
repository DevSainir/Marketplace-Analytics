/**
 * The finish dialog — «Какое изображение оставить на карточке?».
 *
 * What is pinned is the choice: every photo is offered, the best CTR is picked
 * to begin with, the one on the card is marked, and what goes back to the view
 * is the photo the seller actually clicked. The upload itself is the backend's.
 */
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import FinishTestDialog from '@/modules/abTests/components/FinishTestDialog.vue'

const MAIN = '00000000-0000-7000-8000-00000000000a'
const BEST = '00000000-0000-7000-8000-00000000000b'
const LIVE = '00000000-0000-7000-8000-00000000000c'
const DROPPED = '00000000-0000-7000-8000-00000000000d'

function variant(id, overrides = {}) {
  return {
    variant_id: id,
    position: 1,
    is_original: false,
    is_active: false,
    is_excluded: false,
    click_through: '5.00',
    ...overrides,
  }
}

const TEST = {
  id: 'test-1',
  status: 'paused',
  variants: [
    variant(MAIN, { position: 0, is_original: true, click_through: '6.91' }),
    // A string, as the wire sends it — and two digits against one, the case
    // that once crowned the wrong photo.
    variant(BEST, { position: 1, click_through: '11.24' }),
    variant(LIVE, { position: 2, is_active: true, click_through: '8.92' }),
    variant(DROPPED, { position: 3, is_excluded: true, click_through: null }),
  ],
}

let wrapper = null

function build(extra = {}) {
  wrapper = mount(FinishTestDialog, {
    props: { open: true, test: TEST, ...extra },
    attachTo: document.body,
  })
  return wrapper
}

function options() {
  return Array.from(document.body.querySelectorAll('[data-testid="finish-option"]'))
}

function click(selector) {
  document.body.querySelector(selector).click()
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('the finish dialog', () => {
  it('offers every photo, «Главное» and excluded ones included, with its CTR', () => {
    build()

    const texts = options().map((el) => el.textContent.replace(/\s+/g, ' ').trim())
    expect(texts).toHaveLength(4)
    expect(texts[0]).toContain('Главное')
    expect(texts[0]).toContain('CTR 6,91%')
    expect(texts[2]).toContain('На карточке')
    expect(texts[3]).toContain('Убрано')
    expect(texts[3]).toContain('CTR —')
  })

  it('starts on the photo with the best CTR', () => {
    build()

    const chosen = options().filter((el) => el.getAttribute('aria-checked') === 'true')
    expect(chosen).toHaveLength(1)
    expect(chosen[0].textContent).toContain('Вариант 1')
    expect(chosen[0].textContent).toContain('Лучший CTR')
  })

  it('hands back the photo the seller picked', async () => {
    build()

    options()[2].click()
    await wrapper.vm.$nextTick()
    click('[data-testid="finish-confirm"]')

    expect(wrapper.emitted('confirm')).toEqual([[LIVE]])
  })

  it('closes from the backdrop, but not while the finish is in flight', async () => {
    build({ saving: true })
    click('[data-testid="finish-scrim"]')
    expect(wrapper.emitted('close')).toBeUndefined()

    await wrapper.setProps({ saving: false })
    click('[data-testid="finish-scrim"]')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('shows its own failure, not an error left over from the page', async () => {
    build({ error: 'Старая ошибка загрузки' })
    expect(document.body.textContent).not.toContain('Старая ошибка загрузки')

    click('[data-testid="finish-confirm"]')
    await wrapper.setProps({ error: 'WB отклонил фото.' })

    expect(document.body.textContent).toContain('WB отклонил фото.')
  })
})
