import { mount } from '@vue/test-utils'

import SkuThumb from '@/core/components/SkuThumb.vue'

const PHOTO = 'https://basket-44.wbbasket.ru/vol9537/part953770/953770957/images/big/1.webp'

describe('SkuThumb', () => {
  it('renders the card photo when the catalogue has one', () => {
    const wrapper = mount(SkuThumb, { props: { src: PHOTO, label: 'M-TRX01-BLK' } })

    expect(wrapper.find('img').attributes('src')).toBe(PHOTO)
    expect(wrapper.find('img').attributes('alt')).toBe('Фото M-TRX01-BLK')
  })

  it('does not tell WB which of our pages is asking', () => {
    // The image is fetched from WB's CDN, so the request leaves our origin and
    // no policy of ours applies to it. WB may learn a card was viewed; without
    // this it also learns the URL of the page that viewed it — which for this
    // app names the SKU and the report the seller is reading.
    const wrapper = mount(SkuThumb, { props: { src: PHOTO } })

    expect(wrapper.find('img').attributes('referrerpolicy')).toBe('no-referrer')
  })

  it('defers the fetch until the row is on screen', () => {
    // The P&L renders every SKU of a window at once. Eager loading turns
    // opening it into a few hundred CDN requests before the first row paints.
    const wrapper = mount(SkuThumb, { props: { src: PHOTO } })

    expect(wrapper.find('img').attributes('loading')).toBe('lazy')
  })

  it('shows the placeholder when the catalogue holds no photo', () => {
    // A SKU can be settled before its first catalogue harvest, and the P&L's
    // account-level rows are not a product at all.
    const wrapper = mount(SkuThumb, { props: { src: null } })

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('svg').exists()).toBe(true)
  })

  it('falls back to the placeholder when WB no longer serves the image', async () => {
    // The URL is a cache of what the CDN served at the last catalogue sync, so
    // a re-shot card 404s until the next one. A broken-image glyph in a data
    // table reads as "this row is broken"; the placeholder reads as "no photo".
    const wrapper = mount(SkuThumb, { props: { src: PHOTO } })

    await wrapper.find('img').trigger('error')

    expect(wrapper.find('img').exists()).toBe(false)
    expect(wrapper.find('svg').exists()).toBe(true)
  })

  it('keeps the same box whether or not there is a photo', () => {
    // A row whose height depends on WB having served an image makes a table of
    // forty SKUs ripple as it loads.
    const withPhoto = mount(SkuThumb, { props: { src: PHOTO, size: 'md' } })
    const without = mount(SkuThumb, { props: { src: null, size: 'md' } })

    expect(without.classes()).toEqual(withPhoto.classes())
    expect(withPhoto.classes()).toEqual(expect.arrayContaining(['h-10', 'w-10']))
  })
})
