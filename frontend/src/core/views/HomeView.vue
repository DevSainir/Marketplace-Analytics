<script setup>
// Landing page. Presentational only — no data fetching (see architecture rules).
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

      <div class="mt-xl flex justify-center phone:mt-lg">
        <RouterLink
          to="/monitoring"
          class="inline-flex w-full items-center justify-center rounded-btn bg-action px-lg py-sm text-base font-semibold text-white shadow-soft transition hover:bg-action-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action phone:min-h-11 sm:w-auto"
        >
          Открыть мониторинг →
        </RouterLink>
      </div>
    </section>
  </div>
</template>
