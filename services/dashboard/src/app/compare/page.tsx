'use client'

import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'
import Link from 'next/link'
import { computeSQS } from '@/lib/sqs'

type CoinBundle = {
  symbol: string
  sqs: number
  signal?: { direction?: string; confidence?: number; regime?: string; drift_status?: string }
  verdict?: { direction?: string; confidence?: number }
  backtest?: { sharpe_ratio?: number; win_rate_pct?: number }
  features?: { rsi_14?: number; imbalance_5?: number; regime?: string }
}

function CompareContent() {
  const searchParams = useSearchParams()
  const raw = searchParams.get('symbols') ?? 'BTCUSDT,ETHUSDT'
  const symbols = raw
    .split(',')
    .map(s => s.trim().toUpperCase())
    .filter(s => s.endsWith('USDT'))
    .slice(0, 4)

  const [rows, setRows] = useState<CoinBundle[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (symbols.length === 0) {
      setLoading(false)
      return
    }
    Promise.all(
      symbols.map(sym =>
        fetch(`/api/coin/${sym}`)
          .then(r => r.json())
          .then(data => {
            const sig = data.signal ?? {}
            const feat = data.features ?? {}
            const bt = data.backtest ?? {}
            const sqs = computeSQS({
              confidence: sig.confidence ?? 0,
              direction: sig.direction ?? 'flat',
              sharpe: bt.sharpe_ratio ?? null,
              winRate: bt.win_rate_pct ?? null,
              regime: sig.regime ?? feat.regime ?? null,
              drift: sig.drift_status ?? feat.drift_status ?? 'STABLE',
              imbalance5: feat.imbalance_5 ?? null,
            })
            return {
              symbol: sym,
              sqs,
              signal: sig,
              verdict: data.verdict,
              backtest: bt,
              features: feat,
            } as CoinBundle
          })
          .catch(() => ({ symbol: sym, sqs: 0 } as CoinBundle)),
      ),
    ).then(setRows).finally(() => setLoading(false))
  }, [symbols.join(',')])

  if (loading) {
    return <p className="text-gray-500 text-center mt-20">Karşılaştırma yükleniyor…</p>
  }

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-black text-white">⚖ Coin Karşılaştırma</h1>
        <p className="text-gray-500 text-sm mt-1">
          URL: <code className="text-orange-400">/compare?symbols=BTCUSDT,ETHUSDT,SOLUSDT</code> (max 4)
        </p>
      </header>

      <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
        {rows.map(r => (
          <div key={r.symbol} className="bg-gray-900 border border-gray-800 rounded-xl p-4 space-y-3">
            <div className="flex justify-between items-start">
              <Link href={`/coin/${r.symbol}`} className="text-white font-bold hover:text-orange-400">
                {r.symbol}
              </Link>
              <span className="text-orange-400 font-black text-lg">{r.sqs}</span>
            </div>
            <p className="text-xs text-gray-500">SQS skoru</p>
            <div className="text-xs space-y-1">
              <p>
                Sinyal:{' '}
                <span className="text-white">{r.signal?.direction ?? 'flat'}</span>{' '}
                ({Math.round((r.signal?.confidence ?? 0) * 100)}%)
              </p>
              <p>
                Verdict:{' '}
                <span className="text-white">{r.verdict?.direction ?? '—'}</span>
              </p>
              <p>
                Backtest: Sharpe {r.backtest?.sharpe_ratio?.toFixed(2) ?? '—'} · WR{' '}
                {r.backtest?.win_rate_pct?.toFixed(0) ?? '—'}%
              </p>
              <p>RSI: {r.features?.rsi_14?.toFixed(1) ?? '—'}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function ComparePage() {
  return (
    <Suspense fallback={<p className="text-gray-500 text-center mt-20">Yükleniyor…</p>}>
      <CompareContent />
    </Suspense>
  )
}
