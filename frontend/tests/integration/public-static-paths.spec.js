/**
 * Ничто в `public/` не должно закрывать собой маршрут SPA.
 *
 * nginx отдаёт приложение правилом `try_files $uri $uri/ /index.html`, и вторая
 * ветка — та, что ищет КАТАЛОГ, — срабатывает раньше отката на `index.html`.
 * Каталог в `public/`, названный как маршрут, поэтому перехватывает его: nginx
 * находит директорию, листинг выключен, и вместо страницы приходит 403.
 *
 * Это уже случилось. Датапак финмодели лежал в `public/labs/finmodel/`, и
 * `/labs/finmodel` на проде отдавал 403, пока соседний `/labs/monitoring`
 * открывался. Ни один тест этого не видел, и увидеть не мог: dev-сервер Vite
 * такого правила не знает, у него любой неизвестный путь и так уходит в
 * `index.html`. Ломается только за nginx — как и CSP (см. csp.spec.js).
 *
 * Отсюда правило: имя каталога в `public/` не может совпасть с первым сегментом
 * маршрута. Файл рядом безопасен — `try_files` отдаёт его как файл.
 */
import { readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'

import router from '@/core/router'

const PUBLIC = resolve(process.cwd(), 'public')

/** Каталоги в `public/` — только они перехватывают `$uri/`. */
function publicDirectories(dir = PUBLIC, prefix = '') {
  const found = []
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (!statSync(path).isDirectory()) continue
    const asUrl = prefix + '/' + entry
    found.push(asUrl)
    found.push(...publicDirectories(path, asUrl))
  }
  return found
}

/** Пути всех маршрутов приложения — уже развёрнутые, вложенные включительно. */
function routePaths() {
  return router.getRoutes().map((route) => route.path)
}

describe('static files in public/', () => {
  it('никогда не занимают путь маршрута', () => {
    const directories = new Set(publicDirectories())
    const clashes = routePaths().filter((path) => directories.has(path))

    expect(
      clashes,
      'Каталог в public/ с именем маршрута перехватывает его в nginx ' +
        '(`try_files $uri $uri/`) и страница отдаёт 403. Переименуйте каталог ' +
        'или положите файл без каталога-тёзки:\n' +
        clashes.map((c) => `  public${c}/ закрывает маршрут ${c}`).join('\n'),
    ).toEqual([])
  })
})
