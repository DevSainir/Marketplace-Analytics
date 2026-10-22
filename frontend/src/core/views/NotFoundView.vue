<template>
  <!-- On the shared container and the design system's type and button, like
       every other page — it was the one page on stock Tailwind (bg-white,
       text-xs, rounded-lg, its own button). -->
  <div class="app-container flex flex-col items-center py-xl text-center sm:py-24">
    <span
      class="rounded-full border border-border-subtle bg-surface px-md py-xs text-tiny font-medium text-muted shadow-soft"
    >
      Error 404
    </span>

    <h1 class="mt-lg text-h2 font-bold text-primary">Page not found</h1>

    <p class="mx-auto mt-sm max-w-md text-base text-muted">
      This page does not exist or has moved. Check the address or go back to the home page.
    </p>

    <RouterLink to="/" class="ui-btn ui-btn--primary mt-xl">← Home</RouterLink>
  </div>
</template>
