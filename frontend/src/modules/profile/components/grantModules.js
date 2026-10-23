/**
 * Every grantable surface, in the order the UI lists them.
 *
 * One per page of the header, in the header's order; a switch opens its whole
 * page, money included. The KEYS are the contract — they must match the backend's
 * `ModuleKey`; the labels are this page's own.
 */
export const GRANT_MODULES = [
  { key: 'monitoring', label: 'Monitoring', hint: 'Product cards and the funnel' },
  { key: 'summary', label: 'Summary', hint: 'Revenue, margin, orders and ads' },
  { key: 'finreports', label: 'P&L', hint: 'Profit, cost price, logistics' },
  { key: 'ab_tests', label: 'A/B tests', hint: 'Photo rotation' },
  { key: 'heatmap', label: 'Heatmap', hint: 'Every metric by day, money included' },
  { key: 'advertising', label: 'Advertising', hint: 'Spend, ACoS (sales), bonuses' },
]

export const GRANT_LEVELS = [
  { value: 'read_write', label: 'Read and write', hint: 'Can change data' },
  { value: 'read_only', label: 'Read only', hint: 'Views, does not change' },
]

/** Short label for a level, for a table cell. */
export function levelLabel(value) {
  return GRANT_LEVELS.find((level) => level.value === value)?.label ?? value
}

/** Short label for a module key, for a chip. */
export function moduleLabel(key) {
  return GRANT_MODULES.find((module) => module.key === key)?.label ?? key
}
