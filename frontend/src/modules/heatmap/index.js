/**
 * PUBLIC API CONTRACT — heatmap module.
 *
 * «Тепловая карта»: every article of a кабинет, day by day, painted by one
 * metric — the view for a кабинет with too many working articles to watch one
 * at a time. Lives at /heatmap; /labs/heatmap adds what is still being tried out.
 *
 * The ONLY entry point other parts of the app may import from.
 */
export { heatmapRoutes } from '@/modules/heatmap/routes'
