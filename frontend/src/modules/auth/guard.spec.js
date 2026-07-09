import { safeRedirect } from '@/modules/auth/guard'

describe('safeRedirect', () => {
  it('accepts same-app absolute paths', () => {
    expect(safeRedirect('/monitoring?sku=123')).toBe('/monitoring?sku=123')
  })

  it('rejects external and protocol-relative URLs', () => {
    expect(safeRedirect('https://evil.example')).toBe('/monitoring')
    expect(safeRedirect('//evil.example')).toBe('/monitoring')
  })

  it('rejects non-string values from the query', () => {
    expect(safeRedirect(undefined)).toBe('/monitoring')
    expect(safeRedirect(['/a', '/b'])).toBe('/monitoring')
  })
})
