/**
 * Every grantable surface, in the order the UI lists them.
 *
 * A labs copy of the profile module's `MODULES`: that list is not re-exported
 * from `@/modules/profile`, and the sandbox may not reach past a module's
 * Public API. The KEYS are the contract — they must match the backend's
 * `ModuleKey`; the labels are this page's own.
 */
export const GRANT_MODULES = [
  { key: 'monitoring', label: 'Мониторинг', hint: 'Карточки и воронка' },
  { key: 'finreports', label: 'P&L', hint: 'Прибыль, себестоимость, логистика' },
  // «Сводка» needs BOTH of the above — it shows the P&L's money beside
  // monitoring's demand — so it is not a switch of its own.
  { key: 'ab_tests', label: 'A/Б-тесты', hint: 'Ротация фото' },
  { key: 'advertising', label: 'Реклама', hint: 'Расход, ДРР от продаж, бонусы' },
]

export const GRANT_LEVELS = [
  { value: 'read_write', label: 'Чтение и запись', hint: 'Может менять данные' },
  { value: 'read_only', label: 'Только чтение', hint: 'Смотрит, но не меняет' },
]

/** Short label for a level, for a table cell. */
export function levelLabel(value) {
  return GRANT_LEVELS.find((level) => level.value === value)?.label ?? value
}

/** Short label for a module key, for a chip. */
export function moduleLabel(key) {
  return GRANT_MODULES.find((module) => module.key === key)?.label ?? key
}
