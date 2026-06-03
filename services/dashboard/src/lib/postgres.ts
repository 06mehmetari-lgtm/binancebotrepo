import { Pool } from 'pg'

let pool: Pool | null = null

export function getPostgresPool(): Pool {
  if (pool) return pool
  const url =
    process.env.POSTGRES_URL ||
    `postgresql://${process.env.POSTGRES_USER || 'prometheus'}:${process.env.POSTGRES_PASSWORD || ''}@${
      process.env.POSTGRES_HOST || 'postgres'
    }:5432/prometheus_trading`
  pool = new Pool({
    connectionString: url,
    max: 5,
    connectionTimeoutMillis: 5000,
  })
  return pool
}

export async function closePostgresPool(): Promise<void> {
  if (pool) {
    await pool.end()
    pool = null
  }
}
