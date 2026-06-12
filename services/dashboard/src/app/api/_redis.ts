import Redis from 'ioredis'

function redisPassword(): string | undefined {
  const p = (process.env.REDIS_PASSWORD ?? '').trim()
  return p || undefined
}

export function createRedis() {
  return new Redis({
    host: process.env.REDIS_HOST || 'redis',
    port: 6379,
    password: redisPassword(),
    lazyConnect: false,
    connectTimeout: 5000,
    commandTimeout: 8000,
    maxRetriesPerRequest: 2,
  })
}
