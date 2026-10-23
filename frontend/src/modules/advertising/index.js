/**
 * PUBLIC API CONTRACT — advertising module.
 *
 * "Advertising": where a workspace's advertising money went — by bid type and zone,
 * by day against DRR from sales, and by article — and how much of it WB's bonus
 * pool paid. Grew out of the finmodel lab's "Advertising" tab; the figures now come
 * from `GET /v1/advertising`.
 *
 * The ONLY entry point other parts of the app may import from.
 */
export { advertisingRoutes } from '@/modules/advertising/routes'
