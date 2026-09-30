import { METRIC_COLORS, isOnMark } from '@/modules/monitoring/chartOptions'
import {
  AGGREGATE_METRIC_GROUPS,
  SKU_METRIC_GROUPS,
  buildMetricChart,
  labelledGroups,
} from '@/modules/monitoring/metricChart'
import { TRAFFIC_COLUMNS, buildMetricsMatrix } from '@/modules/monitoring/metricsMatrix'

const DAYS = ['2026-07-01', '2026-07-02', '2026-07-03']

/** A backend matrix row: flat, day-major, `COLUMNS_PER_DAY` cells per day. */
function row(key, valuesByBucket) {
  const values = DAYS.flatMap((_, day) =>
    TRAFFIC_COLUMNS.map((column) => valuesByBucket[column.key]?.[day] ?? null),
  )
  return { key, values }
}

/**
 * The display matrix the store hands the chart, built the way the store builds
 * it — the real mapping code rather than a hand-written shape that can drift
 * from it. In «Демо»'s units: priced in RUB, advertised in KGS.
 */
function matrixView(rows = [], currencies = { prices: 'RUB', ads: ['KGS'] }) {
  return buildMetricsMatrix(
    {
      nm_id: 1,
      matrix: { days: DAYS, buckets: TRAFFIC_COLUMNS.map((column) => column.key), rows },
    },
    currencies,
  )
}

/** Build with the per-SKU catalogue, which is what both pages' chart uses. */
const chartOf = (metrics, rows = [], hover) =>
  buildMetricChart(matrixView(rows), { metrics, groups: SKU_METRIC_GROUPS, hover })

const seriesNamed = (chart, name) => chart.option.series.find((entry) => entry.name === name)
const axisOf = (chart) => [chart.option.yAxis].flat()[0]

/** One hovered point, as ECharts hands it to an axis-trigger formatter. */
const point = (seriesIndex, seriesName, value, dataIndex = 1) => ({
  seriesIndex,
  dataIndex,
  seriesName,
  value,
  marker: '',
  axisValue: '02.07',
})

describe('buildMetricChart', () => {
  it('draws nothing at all when the window has no days', () => {
    // The page renders the block only when there is something in it; a chart
    // over an empty window would be an axis around nothing.
    expect(buildMetricChart({ days: [], rows: [] }, { groups: SKU_METRIC_GROUPS })).toBeNull()
    expect(buildMetricChart(null, { groups: SKU_METRIC_GROUPS })).toBeNull()
  })

  describe('reading the matrix', () => {
    it('follows the day-major stride when reading a bucket', () => {
      // A day section is COLUMNS_PER_DAY wide. Reading with the wrong stride
      // returns some other bucket's number, which renders perfectly happily —
      // so this pins the arithmetic rather than the absence of a crash.
      const chart = chartOf(['spend'], [row('spend', { total: [10, 20, 30] })])

      // One unit in the pick, so the numbers are the numbers.
      expect(seriesNamed(chart, 'Затраты').data).toEqual([10, 20, 30])
    })

    it('reads CPM out of the day\u2019s «Общая» column', () => {
      // The backend serves it there as the day's whole ad bill over the показы
      // it bought; the chart is a lookup, so this is what breaks if the row
      // ever goes back to being blank.
      const chart = chartOf(['cpm'], [row('cpm', { total: [150, 300, 225] })])

      expect(seriesNamed(chart, 'CPM').data).toEqual([150, 300, 225])
    })

    it('reads a mini-block metric off its one-cell-per-day row', () => {
      // «Цены» and «Остатки» are not day × bucket grids: each row already
      // carries a single «Общая» cell per day, so the stride must not apply.
      const chart = chartOf(['customer_price'], [row('customer_price', { total: [990, 890, 890] })])

      expect(seriesNamed(chart, 'Цена покупателя').data).toEqual([990, 890, 890])
    })

    it('renders a day WB served nothing as a gap, not as a zero', () => {
      // A blank day and a zero day mean different things, and joining the line
      // across the blank would draw a trend that never happened.
      const chart = chartOf(['spend'], [row('spend', { total: [5, null, 7] })])

      expect(seriesNamed(chart, 'Затраты').data[1]).toBeNull()
      expect(chart.option.series[0].connectNulls).toBe(false)
    })

    it('ignores a metric the catalogue does not hold', () => {
      // The account-wide page offers a shorter list; a key from the other one
      // must drop out rather than produce a phantom empty series.
      const chart = chartOf(['spend', 'нет-такого'], [row('spend', { total: [1, 2, 3] })])

      expect(chart.option.series.map((entry) => entry.name)).toEqual(['Затраты'])
    })
  })

  describe('the rulers are fixed', () => {
    const counts = row('orders', { total: [10, 20, 15] })
    const money = row('spend', { total: [200, 400, 100] })

    it('reads штуки down the left edge and деньги down the right', () => {
      const chart = chartOf(['spend', 'orders'], [money, counts])
      const axes = [chart.option.yAxis].flat()

      expect(axes[0].position).toBe('left')
      expect(axes[1].position).toBe('right')
      // Both drawn as they are: neither scale is an index.
      expect(seriesNamed(chart, 'Заказы, шт').data).toEqual([10, 20, 15])
      expect(seriesNamed(chart, 'Затраты').data).toEqual([200, 400, 100])
    })

    it('keeps BOTH scales even when only one of them has anything on it', () => {
      // The point of a fixed scale. A ruler that appears and disappears with
      // the selection is what made «Заказы» a readable column one moment and a
      // smear along the axis the next.
      const chart = chartOf(['cpc'], [row('cpc', { total: [10, 12, 11] })])
      const axes = [chart.option.yAxis].flat()

      expect(axes[0].position).toBe('left')
      expect(axes[1].position).toBe('right')
      expect(axes[0].max).toBe(500) // ничего в штуках — шкала на месте
      expect(axes[1].max).toBe(12)
    })

    it('does not let one unit move the other one scale', () => {
      // Ticking «Клики» must not rescale «Заказы» — both are штуки, but the
      // money ruler cannot move at all, and that is the half that used to.
      const alone = chartOf(['spend'], [money])
      const withCounts = chartOf(['spend', 'orders'], [money, counts])

      expect([alone.option.yAxis].flat()[1].max).toBe([withCounts.option.yAxis].flat()[1].max)
    })

    it('keeps the left ruler for the FUNNEL, not for everything in штуках', () => {
      // Показы run to five figures and клики to four while заказы run to two:
      // one ruler true for the first two draws the third along the axis, which
      // is the complaint that produced the list.
      const chart = chartOf(['spend', 'views', 'clicks', 'carts', 'orders'])

      // Затраты → рубли; показы and клики → the index; корзины and заказы →
      // the counts ruler they share an order of magnitude with.
      expect(chart.option.series.map((entry) => entry.yAxisIndex)).toEqual([1, 2, 2, 0, 0])
    })

    it('sends a percent to the index, like everything else without a ruler', () => {
      const chart = chartOf(['ctr', 'orders'])

      expect(chart.option.series.map((entry) => entry.yAxisIndex)).toEqual([2, 0])
    })
  })

  describe('what has no ruler is an index', () => {
    const counts = row('orders', { total: [10, 20, 15] })

    it('rebases a percent to 100 at its first reported day', () => {
      const chart = chartOf(['ctr', 'orders'], [row('ctr', { total: [2, 4, 1] }), counts])

      expect(seriesNamed(chart, 'CTR, %').data).toEqual([100, 200, 50])
      expect(seriesNamed(chart, 'Заказы, шт').data).toEqual([10, 20, 15])
    })

    it('takes the baseline from the first day that reported, not from day one', () => {
      // A window often opens on blank days; rebasing against nothing would drop
      // the series entirely.
      const chart = chartOf(['ctr'], [row('ctr', { total: [null, 2, 4] })])

      expect(seriesNamed(chart, 'CTR, %').data).toEqual([null, 100, 200])
    })

    it('leaves an all-blank series alone rather than dividing by nothing', () => {
      const chart = chartOf(['ctr'], [row('ctr', { total: [null, null, null] })])

      expect(seriesNamed(chart, 'CTR, %').data).toEqual([null, null, null])
    })

    it('draws its scale nowhere — an index has no unit to report', () => {
      const chart = chartOf(['ctr', 'orders'], [row('ctr', { total: [2, 4, 1] }), counts])
      const axes = [chart.option.yAxis].flat()

      expect(axes).toHaveLength(3)
      expect(axes[2].axisLabel.show).toBe(false)
      expect(axes[2].splitLine.show).toBe(false)
    })

    it('keeps the index off the scales that have units', () => {
      // The whole reason it has its own axis: an index of 100 landing on «100
      // штук» would be a number in the wrong units on a real gridline.
      const chart = chartOf(['ctr', 'orders'], [row('ctr', { total: [2, 4, 1] }), counts])

      expect([chart.option.yAxis].flat()[0].max).toBe(20) // заказы, не индекс
    })
  })

  describe('the ruler of заказов', () => {
    it('covers «Заказы органика» by the same rule', () => {
      // The same count of the same thing through one traffic bucket, so it is
      // true on the same scale.
      const chart = buildMetricChart(
        matrixView([
          row('orders', { total: [10, 20, 15], organic: [4, 8, 6] }),
          row('spend', { total: [4000, 8000, 2000] }),
          row('cpm', { total: [200, 400, 100] }),
        ]),
        { metrics: ['spend', 'cpm', 'orders_organic'], groups: AGGREGATE_METRIC_GROUPS },
      )

      expect(seriesNamed(chart, 'Заказы органика, шт').data).toEqual([4, 8, 6])
    })
  })

  describe('the value axis', () => {
    it('tops out at what was actually plotted, not above it', () => {
      // It used to round up to a «nice» ceiling: 430 became 450, and a fifth of
      // the canvas was empty air above the data.
      const chart = chartOf(['spend'], [row('spend', { total: [400, 430, 420] })])

      expect([chart.option.yAxis].flat()[1].max).toBe(430)
    })

    it('puts the rules on numbers a reader recognises', () => {
      // The top is an odd number by design, so the rules cannot be a quarter of
      // it: 430 / 4 is 107,5.
      const chart = chartOf(['spend'], [row('spend', { total: [400, 430, 420] })])

      expect([chart.option.yAxis].flat()[1].interval).toBe(100)
    })

    it('starts at zero and carries no unit name', () => {
      // A mixed pick plots indices, and naming the axis would claim those were
      // quantities too.
      const chart = chartOf(['spend'], [row('spend', { total: [10, 20, 30] })])

      expect(axisOf(chart).min).toBe(0)
      expect(axisOf(chart).name).toBeUndefined()
    })

    it('falls back to a round ceiling when the window reports nothing at all', () => {
      expect([chartOf(['spend']).option.yAxis].flat()[1].max).toBe(500)
    })

    it('never cuts a series off the top of its own scale', () => {
      const chart = chartOf(
        ['spend', 'orders'],
        [row('spend', { total: [100, 300, 100] }), row('orders', { total: [80, 80, 80] })],
      )
      const axes = [chart.option.yAxis].flat()

      expect(axes[0].max).toBeGreaterThanOrEqual(80) // заказы
      expect(axes[1].max).toBeGreaterThanOrEqual(300) // затраты
    })
  })

  describe('the order metrics are drawn in', () => {
    it('follows the catalogue, not the order the chips were clicked', () => {
      // The pick order used to reach the plot, so the same three metrics gave a
      // different legend, a different hover and different column positions on
      // every visit.
      const forwards = chartOf(['spend', 'carts', 'orders'])
      const backwards = chartOf(['orders', 'carts', 'spend'])

      expect(backwards.option.series.map((entry) => entry.name)).toEqual(
        forwards.option.series.map((entry) => entry.name),
      )
      expect(forwards.option.series.map((entry) => entry.name)).toEqual([
        'Затраты',
        'Корзины, шт',
        'Заказы, шт',
      ])
    })

    it('offers CPM straight after CTR, on both catalogues', () => {
      // The order is the legend's and the hover's too, so a metric's place in
      // the list is where a reader will keep finding it.
      const advertising = (groups) => groups[0].items.map((item) => item.key)

      expect(advertising(SKU_METRIC_GROUPS)).toEqual([
        'spend',
        'views',
        'clicks',
        'ctr',
        'cpm',
        'cpc',
        'drr_orders',
        'drr_sales',
      ])
      // CTR cannot follow to the account-wide page — «Клики» there is the
      // funnel's card opens, not advertising clicks — so CPM takes its place.
      expect(advertising(AGGREGATE_METRIC_GROUPS)).toEqual([
        'spend',
        'views',
        'clicks',
        'cpm',
        'drr_orders',
      ])
    })

    it('stands the columns of a day as корзины, заказы, остатки', () => {
      // Columns are drawn in series order, so this is what a reader sees left
      // to right inside every day.
      const chart = chartOf(['stock_quantity', 'orders', 'carts'])

      expect(chart.option.series.map((entry) => entry.name)).toEqual([
        'Корзины, шт',
        'Заказы, шт',
        'Остатки на складах, шт',
      ])
    })
  })

  describe('colour', () => {
    it('gives a metric the same hue however it was picked', () => {
      // Colour by slot made «Заказы» blue on one reading of the page and orange
      // on the next, so the legend had to be re-read every time.
      const first = chartOf(['orders', 'spend'])
      const second = chartOf(['spend', 'ctr', 'orders'])

      expect(seriesNamed(first, 'Заказы, шт').color).toBe(seriesNamed(second, 'Заказы, шт').color)
      expect(seriesNamed(first, 'Затраты').color).toBe(seriesNamed(second, 'Затраты').color)
    })

    it('gives every metric of a catalogue its own hue', () => {
      const keys = SKU_METRIC_GROUPS.flatMap((group) => group.items.map((item) => item.key))
      const hues = keys.map((key) => METRIC_COLORS[key])

      expect(new Set(hues).size).toBe(keys.length)
    })

    it('paints затраты and остатки green, корзины blue and заказы orange', () => {
      // The four the reader asked for by name, pinned so a palette edit cannot
      // quietly swap them.
      const chart = chartOf(['spend', 'carts', 'orders', 'stock_quantity'])
      const hue = (name) => seriesNamed(chart, name).color

      expect(hue('Затраты')).toBe('#1BAF7A')
      expect(hue('Остатки на складах, шт')).toBe('#0B7A3B')
      expect(hue('Корзины, шт')).toBe('#2A78D6')
      expect(hue('Заказы, шт')).toBe('#EB6834')
    })
  })

  describe('what counts as hovering a metric', () => {
    it('is the dot and the line through it, not the fill under them', () => {
      // The fill belongs to its series as far as ECharts is concerned, so a
      // cursor anywhere in the band arrived as «наведён на Затраты» and
      // answered with Затраты alone — over most of the plot.
      expect(isOnMark({ cursorY: 100, markY: 104 })).toBe(true)
      expect(isOnMark({ cursorY: 100, markY: 260 })).toBe(false)
    })

    it('counts a column whole — it has no fill to be confused with', () => {
      expect(isOnMark({ subType: 'bar', cursorY: 300, markY: 40 })).toBe(true)
    })

    it('reads «cannot tell» as «not on it»', () => {
      // ECharts reports an area hover with no value at all, so the unknown case
      // IS the fill case, and the day's whole list answers both.
      expect(isOnMark({ cursorY: 100, markY: null })).toBe(false)
      expect(isOnMark({ cursorY: null, markY: 100 })).toBe(false)
    })
  })

  describe('the hover', () => {
    const hoverOf = (chart, points) => chart.option.tooltip.formatter(points)

    it('shows the real value, and only that', () => {
      // An index is a shape, not a quantity: a reader who wants to know what
      // «200» meant in money must not have to leave the chart to find out.
      // The index itself is already on the canvas.
      // CTR has no ruler of its own, so it is the series drawn as a shape.
      const chart = chartOf(['ctr'], [row('ctr', { total: [2, 4, 1] })])

      const hover = hoverOf(chart, [point(0, 'CTR, %', 100)])

      expect(hover).toContain('4') // the CTR actually measured that day
      expect(hover).not.toContain('(100)') // not the index it plots at
    })

    it('prints заказы as the count they already are', () => {
      // The plotted number IS the count here — nothing to translate back.
      const chart = chartOf(['orders'], [row('orders', { total: [100, 120, 90] })])

      const hover = hoverOf(chart, [point(0, 'Заказы, шт', 120)])

      expect(hover).toContain('120')
    })

    it('splits the rows into the groups the picker uses', () => {
      // Six unlike numbers in a flat list are read by hunting; «Реклама» and
      // «Воронка» are where the reader already looks for a metric.
      const chart = chartOf(['spend', 'carts'])

      const hover = hoverOf(chart, [point(0, 'Затраты', 100), point(1, 'Корзины, шт', 100)])

      expect(hover).toContain('Реклама')
      expect(hover).toContain('Воронка')
      expect(hover).toContain('dotted') // the rule between the two groups
    })

    it('answers a hover over the day with every metric on the plot', () => {
      const chart = chartOf(['spend', 'carts'], [], { index: null })

      const hover = hoverOf(chart, [point(0, 'Затраты', 100), point(1, 'Корзины, шт', 140)])

      expect(hover).toContain('Затраты')
      expect(hover).toContain('Корзины, шт')
    })

    it('answers a hover on one line with that metric alone', () => {
      // The reader pointed at a line; answering with five other metrics leaves
      // them doing the filtering the chart could have done.
      const cursor = { index: 1 }
      const chart = chartOf(['spend', 'carts'], [], cursor)

      const hover = hoverOf(chart, [point(0, 'Затраты', 100), point(1, 'Корзины, шт', 140)])

      expect(hover).toContain('Корзины, шт')
      expect(hover).not.toContain('Затраты')
    })

    it('shows both metrics where two of them cross', () => {
      // At a crossing there is no telling which line was aimed at, so narrowing
      // to one would be a guess.
      const chart = chartOf(['spend', 'carts'], [], { index: 1 })

      const hover = hoverOf(chart, [point(0, 'Затраты', 140), point(1, 'Корзины, шт', 140)])

      expect(hover).toContain('Корзины, шт')
      expect(hover).toContain('Затраты')
    })
  })

  describe('the currency', () => {
    const hoverOf = (chart, points) => chart.option.tooltip.formatter(points)

    it('states spend in the hover in the unit its campaigns bill in', () => {
      const chart = chartOf(['spend'], [row('spend', { total: [10, 20, 30] })])

      const hover = hoverOf(chart, [point(0, 'Затраты', 20)])

      expect(hover).toContain('20с')
    })

    it("states a price beside spend in its own unit, not the spend's", () => {
      // A KGS-settled кабинет is priced in RUB: one chart-wide unit printed the
      // price in soms, or the spend in roubles, whichever came first.
      const chart = chartOf(
        ['spend', 'seller_price'],
        [row('spend', { total: [10, 20, 30] }), row('seller_price', { total: [100, 200, 300] })],
      )

      const hover = hoverOf(chart, [point(0, 'Затраты', 20), point(1, 'Цена продавца', 200)])

      expect(hover).toContain('20с')
      expect(hover).toContain('200₽')
    })

    it('prints money with no unit while the currency is unknown', () => {
      const view = matrixView([row('spend', { total: [10, 20, 30] })], {})
      const chart = buildMetricChart(view, { metrics: ['spend'], groups: SKU_METRIC_GROUPS })

      const hover = hoverOf(chart, [point(0, 'Затраты', 20)])

      expect(chart.option.series.map((entry) => entry.name)).toEqual(['Затраты'])
      expect(hover).toContain('<b>20</b>')
    })

    it('hands each money item the currency of its own figures, and leaves names alone', () => {
      // The sign goes on the figure («20с», «4 120₽»); a name is only a name.
      const items = labelledGroups(SKU_METRIC_GROUPS, { prices: 'RUB', ads: ['KGS'] }).flatMap(
        (group) => group.items,
      )
      const item = (key) => items.find((entry) => entry.key === key)

      expect(item('spend')).toMatchObject({ name: 'Затраты', currency: ['KGS'] })
      expect(item('seller_price')).toMatchObject({ name: 'Цена продавца', currency: 'RUB' })
      expect(item('ctr').currency).toBeUndefined()
    })
  })

  describe('marks', () => {
    it('draws корзины, заказы and остатки as columns on a short window', () => {
      // Three separate counts, so they are never stacked: a stack would draw a
      // total in which a cart is a unit of stock.
      const chart = chartOf(['carts', 'orders', 'stock_quantity'])

      expect(chart.option.series.map((entry) => entry.type)).toEqual(['bar', 'bar', 'bar'])
      expect(chart.option.series.every((entry) => !entry.stack)).toBe(true)
    })

    it('gives every LINE its own area, in its own hue', () => {
      // One fill was tried first and read as «one important line and some
      // decorations». At this opacity several of them overlap into a grey,
      // which is itself the reading: here these metrics ran together.
      const chart = chartOf(['spend', 'ctr', 'cpm'])

      expect(chart.option.series.every((entry) => entry.areaStyle)).toBe(true)
      expect(new Set(chart.option.series.map((entry) => entry.areaStyle.color)).size).toBe(3)
    })

    it('leaves a column without one — it has no area to fill', () => {
      const chart = chartOf(['spend', 'carts'])

      expect(chart.option.series[0].areaStyle).toBeTruthy()
      expect(chart.option.series[1].areaStyle).toBeUndefined()
    })

    it('lets a whole line answer a hover, not just its twenty dots', () => {
      // What makes «hover this metric» a line-sized target instead of a 5px
      // one: ECharts fires no event for the path between symbols unless asked.
      const chart = chartOf(['spend'])

      expect(chart.option.series[0].triggerLineEvent).toBe(true)
    })

    it('draws rates, prices and ratios as lines', () => {
      const chart = chartOf(['spend', 'customer_price', 'order_conversion'])

      expect(chart.option.series.every((entry) => entry.type === 'line')).toBe(true)
    })
  })

  describe('what the component renders around the plot', () => {
    it('names and colours the legend to match the series', () => {
      const chart = chartOf(['spend', 'orders'])

      expect(chart.legend.map((entry) => entry.name)).toEqual(
        chart.option.series.map((entry) => entry.name),
      )
      expect(chart.legend.map((entry) => entry.color)).toEqual(
        chart.option.series.map((entry) => entry.color),
      )
    })

    it('flags a selection whose every series is blank', () => {
      // So the component can say «нет данных» instead of drawing empty axes.
      expect(chartOf(['spend'], [row('spend', { total: [null, null, null] })]).empty).toBe(true)
      expect(chartOf(['spend'], [row('spend', { total: [1, 2, 3] })]).empty).toBe(false)
    })

    it('flags an empty selection as empty too', () => {
      expect(chartOf([]).empty).toBe(true)
    })
  })

  describe('a long window', () => {
    /** The same chart over a run of consecutive days. */
    const over = (count) => {
      const days = Array.from({ length: count }, (_, i) => {
        const day = new Date('2026-01-05T00:00:00Z') // a Monday
        day.setUTCDate(day.getUTCDate() + i)
        return day.toISOString().slice(0, 10)
      })
      return buildMetricChart(
        buildMetricsMatrix({
          nm_id: 1,
          matrix: {
            days,
            buckets: TRAFFIC_COLUMNS.map((column) => column.key),
            rows: [],
          },
        }),
        { metrics: ['orders'], groups: SKU_METRIC_GROUPS },
      )
    }

    it('divides the axis by ONE week', () => {
      // The division was always weekly in the data, but the dates were sized so
      // that only every second one fitted — and the plot read as fortnightly.
      const isStart = over(90).option.xAxis.splitLine.interval

      expect([0, 7, 14, 21].map(isStart)).toEqual([true, true, true, true])
      expect([1, 6, 8, 13].map(isStart)).toEqual([false, false, false, false])
    })

    it('labels the same days the uprights stand on', () => {
      const chart = over(90)

      expect(chart.option.xAxis.axisLabel.interval(7)).toBe(true)
      expect(chart.option.xAxis.axisLabel.interval(8)).toBe(false)
    })

    it('asks for a date on every day while a month still fits', () => {
      // The weekly ruler is what a long window needs; imposing it on a
      // fortnight would leave two labels under ten days of data. `0` is «every
      // category» — ECharts still drops the ones that physically overlap, but
      // its own auto step is conservative enough to print a month on odd days.
      const short = over(28).option.xAxis

      expect(short.axisLabel.interval).toBe(0)
      expect(short.splitLine.interval).toBe(0)
    })

    it('turns the columns into lines once a month is past', () => {
      // A column needs room; 365 of them across a card is 1,5px each, which is
      // a texture rather than a bar.
      expect(over(31).option.series[0].type).toBe('bar')
      expect(over(90).option.series[0].type).toBe('line')
    })

    it('keeps the whole window on one canvas, however long it is', () => {
      // No ribbon to scroll and no per-day width to multiply out: a year has to
      // be on screen at once, which is the whole point of the layout.
      expect(over(365)).not.toHaveProperty('dayWidth')
      expect(over(365).option.xAxis.data).toHaveLength(365)
    })
  })

  describe('the two catalogues', () => {
    it('offers only metrics an account-wide sum can honestly answer', () => {
      // Prices are per-card facts, CTR and CPC need one card's campaigns, and
      // «Процент выкупа» is a lagged cohort the aggregate endpoint does not
      // compute. Each is absent rather than approximated.
      const keys = AGGREGATE_METRIC_GROUPS.flatMap((group) => group.items.map((item) => item.key))

      expect(keys).not.toContain('seller_price')
      expect(keys).not.toContain('customer_price')
      expect(keys).not.toContain('ctr')
      expect(keys).not.toContain('cpc')
      expect(keys).not.toContain('buyout_percent')
    })

    it('resolves a selection against the catalogue it was handed', () => {
      const view = matrixView([row('order_sum', { total: [10, 20, 30] })])

      const aggregate = buildMetricChart(view, {
        metrics: ['order_sum'],
        groups: AGGREGATE_METRIC_GROUPS,
      })
      const sku = buildMetricChart(view, { metrics: ['order_sum'], groups: SKU_METRIC_GROUPS })

      expect(aggregate.option.series.map((entry) => entry.name)).toEqual(['Заказы'])
      expect(sku.option.series).toEqual([]) // the SKU catalogue has no such key
    })
  })
})
