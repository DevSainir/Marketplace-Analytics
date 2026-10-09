<template>
  <!-- On the shared container and the design system's type and button, like
       every other page — it was the one page on stock Tailwind (bg-white,
       text-xs, rounded-lg, its own button). -->
  <div class="app-container flex flex-col items-center py-xl text-center sm:py-24">
    <span
      class="rounded-full border border-border-subtle bg-surface px-md py-xs text-tiny font-medium text-muted shadow-soft"
    >
      Ошибка 404
    </span>

    <h1 class="mt-lg text-h2 font-bold text-primary">Страница не найдена</h1>

    <p class="mx-auto mt-sm max-w-md text-base text-muted">
      Такой страницы не существует или она была перемещена. Проверьте адрес или вернитесь на
      главную.
    </p>

    <RouterLink to="/" class="ui-btn ui-btn--primary mt-xl">← На главную</RouterLink>
  </div>
</template>
