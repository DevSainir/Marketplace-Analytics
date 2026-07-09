<template>
  <div class="mx-auto flex w-full max-w-3xl flex-col items-center px-4 py-24 text-center sm:py-32">
    <span
      class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-500 shadow-sm"
    >
      Ошибка 404
    </span>

    <h1 class="mt-6 text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
      Страница не найдена
    </h1>

    <p class="mx-auto mt-4 max-w-md text-base leading-7 text-slate-500">
      Такой страницы не существует или она была перемещена. Проверьте адрес или вернитесь на
      главную.
    </p>

    <RouterLink
      to="/"
      class="mt-10 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-600"
    >
      ← На главную
    </RouterLink>
  </div>
</template>
