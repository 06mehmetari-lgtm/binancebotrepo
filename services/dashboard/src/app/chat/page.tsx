'use client'

import { useEffect, useState } from 'react'

type Msg = { role: 'user' | 'assistant'; text: string; provider?: string }

export default function ChatPage() {
  const [symbol, setSymbol] = useState('BTCUSDT')
  const [input, setInput] = useState('')
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [busy, setBusy] = useState(false)
  const [useLlm, setUseLlm] = useState(true)

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    setInput('')
    setMsgs(m => [...m, { role: 'user', text }])
    setBusy(true)
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, symbol, use_llm: useLlm }),
      })
      const j = await res.json()
      setMsgs(m => [
        ...m,
        { role: 'assistant', text: j.answer ?? j.error ?? 'Yanıt yok', provider: j.provider },
      ])
    } catch (e) {
      setMsgs(m => [...m, { role: 'assistant', text: String(e) }])
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    setMsgs([
      {
        role: 'assistant',
        text: 'Prometheus AI asistanı. Örnek: "BTC long açmalı mıyım?", "GRASS neden flat?", "funding riski nedir?"',
      },
    ])
  }, [symbol])

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      <header>
        <h1 className="text-2xl font-black text-white">💬 Döküman & AI Chat</h1>
        <p className="text-gray-500 text-sm mt-1">
          learn:profile + sinyal + verdict + RAG trade memory · Ollama ile Türkçe yanıt
        </p>
      </header>

      <div className="flex gap-2 flex-wrap">
        <input
          value={symbol}
          onChange={e => setSymbol(e.target.value.toUpperCase())}
          className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm font-mono text-white w-32"
        />
        <label className="text-xs text-gray-500 flex items-center gap-1">
          <input type="checkbox" checked={useLlm} onChange={e => setUseLlm(e.target.checked)} />
          Ollama LLM
        </label>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl min-h-[400px] max-h-[60vh] overflow-y-auto p-4 space-y-3">
        {msgs.map((m, i) => (
          <div
            key={i}
            className={`rounded-lg px-3 py-2 text-sm max-w-[90%] ${
              m.role === 'user'
                ? 'ml-auto bg-orange-900/40 text-orange-100 border border-orange-800/50'
                : 'bg-gray-800/80 text-gray-200 border border-gray-700/50'
            }`}
          >
            {m.text}
            {m.provider && (
              <p className="text-[10px] text-gray-600 mt-1">{m.provider}</p>
            )}
          </div>
        ))}
        {busy && <p className="text-gray-500 text-xs animate-pulse">Düşünüyor…</p>}
      </div>

      <div className="flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && send()}
          placeholder="Sorunuzu yazın…"
          className="flex-1 bg-gray-900 border border-gray-700 rounded-xl px-4 py-3 text-sm text-white"
        />
        <button
          type="button"
          onClick={send}
          disabled={busy}
          className="px-5 py-3 rounded-xl bg-purple-600 text-white font-bold text-sm disabled:opacity-50"
        >
          Gönder
        </button>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        {['Long açmalı mıyım?', 'Neden flat?', 'Funding riski?', 'Kaçınma kuralı ne?'].map(q => (
          <button
            key={q}
            type="button"
            onClick={() => setInput(q)}
            className="px-2 py-1 rounded bg-gray-800 text-gray-400 hover:text-white"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
