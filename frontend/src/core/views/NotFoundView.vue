<template>
  <div class="mx-auto flex w-full max-w-3xl flex-col items-center px-4 py-24 text-center sm:py-32">
    <span
      class="inline-flex items-center gap-1.5 rounded-full border border-border-subtle bg-white px-3 py-1 text-xs font-medium text-muted shadow-sm"
    >
      Ошибка 404
    </span>

    <h1 class="mt-6 text-4xl font-bold tracking-tight text-primary sm:text-5xl">
      Страница не найдена
    </h1>

    <p class="mx-auto mt-4 max-w-md text-base leading-7 text-muted">
      Такой страницы не существует или она была перемещена. Проверьте адрес или вернитесь на
      главную.
    </p>

    <RouterLink
      to="/"
      class="mt-10 rounded-lg bg-action px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-action-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-action"
    >
      ← На главную
    </RouterLink>
  </div>
</template>
