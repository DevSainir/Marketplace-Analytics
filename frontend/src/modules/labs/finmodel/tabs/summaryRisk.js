/**
 * Таблица «Кончится в ближайшие три недели» на вкладке «Сводка»: колонки,
 * итоги и совет по каждой строке. Вынесена из summary.js ради потолка в 500
 * строк — считается она там же, где и всё остальное за период.
 */
import { $ } from '@/modules/labs/finmodel/dom'
import { dateRu, esc, money, nf0, num } from '@/modules/labs/finmodel/format'
import { riskBadge, sortState, table } from '@/modules/labs/finmodel/table'

/** Нарисовать таблицу риска. `risky` уже отсортирована по дням до нуля. */
export function riskTable(risky, lossSum) {
  if (!risky.length) return
  var rcols = [
    {
      key: 'code',
      name: 'Артикул',
      l: true,
      get: function (r) {
        return '<span class="code">' + esc(r.code) + '</span>'
      },
    },
    {
      key: 'avail',
      name: 'Доступно',
      get: function (r) {
        return nf0.format(r.avail)
      },
    },
    {
      key: 'burn',
      name: 'Расход/д',
      get: function (r) {
        return num(r.burn, 1)
      },
    },
    {
      key: 'd',
      name: 'Дней',
      sort: true,
      get: function (r) {
        return riskBadge(r.d)
      },
    },
    {
      key: 'when',
      name: 'Дата',
      get: function (r) {
        return r.when ? dateRu(r.when) : '—'
      },
    },
    {
      key: 'per',
      name: 'Маржа/ед',
      get: function (r) {
        return money(r.per)
      },
      cls: function (r) {
        return r.per < 0 ? 'neg' : ''
      },
    },
    {
      key: 'mday',
      name: 'Маржа/д',
      title: 'Расход в день × маржа на единицу',
      get: function (r) {
        return money(r.mday)
      },
      cls: function (r) {
        return r.mday < 0 ? 'neg' : ''
      },
    },
    {
      key: 'loss',
      name: 'Простой 4 нед',
      title: 'Сколько маржи потеряем, пока ждём новую партию',
      get: function (r) {
        return r.loss == null ? '—' : money(r.loss)
      },
      cls: function (r) {
        return r.loss > 50000 ? 'neg' : ''
      },
    },
    {
      key: 'office',
      name: 'В офисе',
      get: function (r) {
        return r.office ? nf0.format(r.office) : '<span class="muted">—</span>'
      },
    },
    {
      key: 'way',
      name: 'В пути',
      title: 'Едет к клиентам; вернётся примерно семь из десяти',
      get: function (r) {
        return nf0.format(r.way)
      },
    },
    {
      key: 'act',
      name: 'Что делать',
      l: true,
      sortable: false,
      get: function (r) {
        if (r.per != null && r.per < 0) return '<span class="badge b-mute">пусть кончается</span>'
        if (r.office > 0 && r.dOff != null && r.dOff > r.d + 7) {
          return '<span class="badge b-good">отгрузить офис: ' + r.dOff + ' дн</span>'
        }
        if (r.d < 28) return '<span class="badge b-crit">производство не успеет</span>'
        return '<span class="badge b-warn">пора запускать партию</span>'
      },
    },
  ]
  sortState.risk = sortState.risk || { key: 'd', dir: 1 }
  table($('t-risk'), 'risk', rcols, risky, {
    code: 'Итого ' + risky.length,
    avail: nf0.format(
      risky.reduce(function (x, r) {
        return x + r.avail
      }, 0),
    ),
    mday: money(
      risky.reduce(function (x, r) {
        return x + (r.mday || 0)
      }, 0),
    ),
    loss: money(lossSum),
    office: nf0.format(
      risky.reduce(function (x, r) {
        return x + r.office
      }, 0),
    ),
    way: nf0.format(
      risky.reduce(function (x, r) {
        return x + r.way
      }, 0),
    ),
  })
}
