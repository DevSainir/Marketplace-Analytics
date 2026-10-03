/**
 * PUBLIC API CONTRACT — advertising module.
 *
 * «Реклама»: where a кабинет's advertising money went — by bid type and zone,
 * by day against ДРР от продаж, and by article — and how much of it WB's bonus
 * pool paid. Grew out of the finmodel lab's «Реклама» tab; the figures now come
 * from `GET /v1/advertising`.
 *
 * The ONLY entry point other parts of the app may import from.
 */
export { advertisingRoutes } from '@/modules/advertising/routes'
