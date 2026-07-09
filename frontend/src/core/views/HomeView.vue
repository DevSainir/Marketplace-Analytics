<script setup>
const features = [
  {
    title: 'Воронка продаж',
    description:
      'Ежедневные просмотры карточки, корзины, заказы и выкупы по каждому SKU — напрямую из аналитики Wildberries.',
    accent: 'text-indigo-600 bg-indigo-50',
    icon: 'M3 13.5 9 7.5l4 4L21 3.5M21 3.5h-5M21 3.5v5',
  },
  {
    title: 'Эффективность рекламы',
    description:
      'Расходы, CPM, CTR и CPC на уровне кампаний с кросс-атрибуцией заказов по каждому цветовому варианту.',
    accent: 'text-emerald-600 bg-emerald-50',
    icon: 'M12 3v18M5.5 12H12m6.5-6.5L12 12',
  },
  {
    title: 'Покрытие остатков',
    description:
      'Остатки в разрезе размер × склад с маскированием out-of-stock, чтобы провалы спроса не выглядели как потеря интереса.',
    accent: 'text-amber-600 bg-amber-50',
    icon: 'M4 7.5 12 3l8 4.5v9L12 21l-8-4.5v-9ZM12 12l8-4.5M12 12 4 7.5M12 12v9',
  },
]
</script>

<template>
  <div class="mx-auto w-full max-w-7xl px-4 py-16 sm:px-6 sm:py-24 lg:px-8">
    <!-- Hero -->
    <section class="mx-auto max-w-3xl text-center">
      <span
        class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-500 shadow-sm"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
        Данные Wildberries · live
      </span>

      <h1 class="mt-6 text-4xl font-bold tracking-tight text-slate-900 sm:text-6xl">
        Аналитика маркетплейса
        <span class="text-indigo-600">без лишнего шума.</span>
      </h1>

      <p class="mx-auto mt-6 max-w-2xl text-lg leading-8 text-slate-500">
        Сервис нормализует сырые метрики Wildberries — маскирует периоды отсутствия на складе,
        выделяет промо-всплески и сезонность, — чтобы менеджеры видели реальный спрос на товар.
      </p>

      <div class="mt-10 flex items-center justify-center gap-4">
        <RouterLink
          to="/monitoring"
          class="rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
        >
          Открыть мониторинг →
        </RouterLink>
        <a
          href="#features"
          class="rounded-lg border border-slate-200 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          Что внутри
        </a>
      </div>
    </section>

    <!-- Feature cards -->
    <section id="features" class="mt-20 grid grid-cols-1 gap-6 md:grid-cols-3">
      <article
        v-for="feature in features"
        :key="feature.title"
        class="rounded-xl border border-slate-200 bg-white p-6 shadow-sm"
      >
        <span
          class="inline-flex h-10 w-10 items-center justify-center rounded-lg"
          :class="feature.accent"
        >
          <svg
            class="h-5 w-5"
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
        <h2 class="mt-4 text-base font-semibold text-slate-900">{{ feature.title }}</h2>
        <p class="mt-2 text-sm leading-6 text-slate-500">{{ feature.description }}</p>
      </article>
    </section>
  </div>
</template>
