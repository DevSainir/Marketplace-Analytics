/**
 * Точка входа страницы: загрузить датапак, собрать состояние, отрисовать.
 *
 * Разметку и стили даёт вьюха, поэтому здесь нет ни одного узла — только
 * корень, от которого страница ищет свои элементы.
 */
import { $, setRoot } from '@/modules/labs/finmodel/dom'
import { buildChrome } from '@/modules/labs/finmodel/chrome'
import { esc } from '@/modules/labs/finmodel/format'
import { render } from '@/modules/labs/finmodel/render'
import { indexCols } from '@/modules/labs/finmodel/select'
import { initAssumptions, setDP, setSaveState } from '@/modules/labs/finmodel/state'

/** Датапак лежит в public/ — миллион байт данных незачем гнать через сборку. */
const DATAPACK_URL = '/labs/finmodel/datapack.json'

/**
 * Смонтировать страницу в переданный корень. Возвращает отписку: страница
 * сама ничего не слушает вне своего поддерева, поэтому размонтирование —
 * это просто забыть корень.
 */
export async function mountFinmodel(el) {
  setRoot(el)
  try {
    const response = await fetch(DATAPACK_URL)
    if (!response.ok) throw new Error(String(response.status))
    setDP(await response.json())
  } catch (error) {
    const host = $('panels')
    if (host) {
      host.innerHTML =
        '<div class="loading">Не удалось загрузить датапак — ' + esc(error.message) + '</div>'
    }
    return () => setRoot(null)
  }

  indexCols()
  initAssumptions()
  setSaveState('допущения только в этом браузере')
  buildChrome()
  render()

  return () => setRoot(null)
}
