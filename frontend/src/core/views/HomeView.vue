<script setup>
// Landing page. Presentational only — no data fetching (see architecture rules).
const features = [
  {
    title: 'Воронка продаж',
    description:
      'Ежедневные просмотры карточки, корзины, заказы и выкупы по каждому SKU — напрямую из аналитики Wildberries.',
    tone: 'action',
    icon: 'M3 13.5 9 7.5l4 4L21 3.5M21 3.5h-5M21 3.5v5',
  },
  {
    title: 'Эффективность рекламы',
    description:
      'Расходы, CPM, CTR и CPC на уровне кампаний с кросс-атрибуцией заказов по каждому цветовому варианту.',
    tone: 'positive',
    icon: 'M12 3v18M5.5 12H12m6.5-6.5L12 12',
  },
  {
    title: 'Покрытие остатков',
    description:
      'Остатки в разрезе размер × склад с маскированием out-of-stock, чтобы провалы спроса не выглядели как потеря интереса.',
    tone: 'warning',
    icon: 'M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9ZM12 12l8-4.5M12 12 4 7.5M12 12v9',
  },
]

// Semantic tint chips — kept as a token map so the template stays declarative.
const toneChip = {
  action: 'text-action bg-action/10',
  positive: 'text-status-positive bg-status-positive/10',
  warning: 'text-status-warning bg-status-warning/10',
}
</script>

<template>
  <!-- `.app-container` is the shared width + safe-area gutter (main.css) — see
       design_system.md «Page Chrome & Canvas». The `phone:` overrides below are
       the app's single max-width breakpoint (≤430px, i.e. the 17 Pro's 402pt):
       on a phone this page is a scroll, not a poster, so it trades the desktop
       page's air for the number of screens it takes to read. -->
  <div class="app-container py-16 phone:py-lg sm:py-24">
    <!-- Hero -->
    <section class="mx-auto max-w-3xl text-center">
      <span
        class="inline-flex items-center gap-sm rounded-full border border-border-subtle bg-surface px-md py-xs text-tiny font-medium text-muted shadow-soft"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-status-positive"></span>
        Данные Wildberries · live
      </span>

      <!-- 36px over a 402pt screen breaks «маркетплейса» onto a line of its own
           and pushes the call to action below the fold; 30px keeps the whole
           hero — chip, headline, promise, buttons — on the first screen. -->
      <h1
        class="mt-lg text-4xl font-bold tracking-tight text-primary phone:mt-md phone:text-3xl sm:text-6xl"
      >
        Аналитика маркетплейса
        <span class="text-action">без лишнего шума.</span>
      </h1>

      <p class="mx-auto mt-lg max-w-2xl text-lg leading-8 text-muted phone:mt-md phone:leading-7">
        Сервис нормализует сырые метрики Wildberries — маскирует периоды отсутствия на складе,
        выделяет промо-всплески и сезонность, — чтобы менеджеры видели реальный спрос на товар.
      </p>

      <div class="mt-xl flex flex-col items-center justify-center gap-sm phone:mt-lg sm:flex-row">
        <RouterLink
          to="/monitoring"
          class="inline-flex w-full items-center justify-center rounded-btn bg-action px-lg py-sm text-base font-semibold text-white shadow-soft transition hover:bg-action-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action phone:min-h-11 sm:w-auto"
        >
          Открыть мониторинг →
        </RouterLink>
        <a
          href="#features"
          class="inline-flex w-full items-center justify-center rounded-btn border border-border-subtle bg-surface px-lg py-sm text-base font-semibold text-primary shadow-soft transition hover:bg-canvas phone:min-h-11 sm:w-auto"
        >
          Что внутри
        </a>
      </div>
    </section>

    <!-- Feature cards -->
    <section
      id="features"
      class="mt-20 grid grid-cols-1 gap-lg phone:mt-xl phone:gap-md md:grid-cols-3"
    >
      <article
        v-for="feature in features"
        :key="feature.title"
        class="rounded-card border border-border-subtle bg-surface p-lg shadow-card phone:p-md"
      >
        <!-- Stacked on desktop, where three cards sit side by side and the icon
             is the column's marker; on a phone the cards are one column and the
             icon reads better as a bullet on the title's line, which also buys
             back a row of height per card. -->
        <div class="phone:flex phone:items-center phone:gap-sm">
          <span
            class="inline-flex h-10 w-10 items-center justify-center rounded-btn phone:h-8 phone:w-8 phone:flex-none"
            :class="toneChip[feature.tone]"
          >
            <svg
              class="h-5 w-5 phone:h-4 phone:w-4"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
            >
              <path :d="feature.icon" />
            </svg>
          </span>
          <h2 class="mt-md text-h3 font-semibold text-primary phone:mt-0">{{ feature.title }}</h2>
        </div>
        <p class="mt-sm text-base leading-6 text-muted">{{ feature.description }}</p>
      </article>
    </section>
  </div>
</template>
