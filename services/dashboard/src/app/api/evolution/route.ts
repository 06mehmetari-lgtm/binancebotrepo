import { NextResponse } from 'next/server'
import { createRedis } from '../_redis'

function safeJson(raw: string | null): unknown {
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export async function GET() {
  const redis = createRedis()
  try {
    const genomeKeys = await redis.keys('neat:best_genome:*')

    const pipeline = redis.pipeline()
    for (const key of genomeKeys) {
      pipeline.get(key)
    }
    pipeline.get('shadow:leaderboard')
    const results = await pipeline.exec()

    const genomes = []
    for (let i = 0; i < genomeKeys.length; i++) {
      const raw = results?.[i]?.[1] as string | null
      const genome = safeJson(raw) as Record<string, unknown> | null
      if (!genome) continue
      // Attach the symbol extracted from the key name if not already present
      if (!genome.symbol) {
        genome.symbol = genomeKeys[i].replace('neat:best_genome:', '')
      }
      genomes.push(genome)
    }

    // Sort by fitness descending; treat missing/non-numeric as 0
    genomes.sort((a, b) => {
      const af = typeof a.fitness === 'number' ? a.fitness : 0
      const bf = typeof b.fitness === 'number' ? b.fitness : 0
      return bf - af
    })

    const leaderboardRaw = results?.[genomeKeys.length]?.[1] as string | null
    const shadowLeaderboard = safeJson(leaderboardRaw) ?? []

    return NextResponse.json({ genomes, shadow_leaderboard: shadowLeaderboard })
  } catch (e) {
    return NextResponse.json({ genomes: [], shadow_leaderboard: [] }, { status: 500 })
  } finally {
    redis.disconnect()
  }
}
