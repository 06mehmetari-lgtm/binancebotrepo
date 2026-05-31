import Redis from 'ioredis'

export function createRedis() {
  return new Redis({
    host: process.env.REDIS_HOST || 'redis',
    port: 6379,
    password: process.env.REDIS_PASSWORD || undefined,
    lazyConnect: false,
    connectTimeout: 3000,
    maxRetriesPerRequest: 1,
  })
}
