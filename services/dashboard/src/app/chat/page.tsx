'use client'
import { useState, useRef, useEffect } from 'react'

interface Message {
  role: 'user' | 'assistant'
  content: string
  sources?: string[]
  ts: number
}

const SUGGESTIONS = [
  'Bitcoin için hangi seviyeler önemli?',
  'Ne zaman long pozisyon açılmalı?',
  'Stop-loss seviyeleri nerede?',
  'Hangi indikatörler kullanılıyor?',
  'Risk yönetimi kuralları neler?',
  'Hangi koşullarda short alınmalı?',
]

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async (text?: string) => {
    const msg = (text ?? input).trim()
    if (!msg || loading) return

    setInput('')
    setError('')
    const userMsg: Message = { role: 'user', content: msg, ts: Date.now() / 1000 }
    setMessages(prev => [...prev, userMsg])
    setLoading(true)

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg }),
      })
      const data = await res.json()
      if (data.error) {
        setError(data.error)
      } else {
        setMessages(prev => [
          ...prev,
          { role: 'assistant', content: data.reply, sources: data.sources, ts: Date.now() / 1000 },
        ])
      }
    } catch {
      setError('Bağlantı hatası.')
    } finally {
      setLoading(false)
      inputRef.current?.focus()
    }
  }

  return (
    <div className="max-w-3xl mx-auto flex flex-col h-[calc(100vh-120px)]">
      {/* Header */}
      <div className="border border-gray-800 rounded-xl p-4 bg-gray-900/60 mb-4 flex items-center gap-3">
        <span className="text-2xl">💬</span>
        <div>
          <h1 className="text-white font-bold text-base">Döküman Chatbotu</h1>
          <p className="text-gray-500 text-xs">Öğrenilmiş PDF&apos;lerden cevap verir — kripto analiz, strateji, kurallar</p>
        </div>
        <a href="/training" className="ml-auto text-xs text-orange-400 hover:text-orange-300 transition-colors shrink-0">
          📚 Dökümanlar →
        </a>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {messages.length === 0 && !loading && (
          <div className="text-center py-10 space-y-4">
            <p className="text-gray-600 text-sm">Dökümanlarınız hakkında soru sorun</p>
            <div className="grid grid-cols-2 gap-2">
              {SUGGESTIONS.map((s, i) => (
                <button
                  key={i}
                  onClick={() => send(s)}
                  className="text-left text-xs text-gray-500 hover:text-gray-300 bg-gray-900/60 hover:bg-gray-800/80
                             border border-gray-800 hover:border-gray-700 rounded-lg px-3 py-2.5 transition-all"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-3 ${
              m.role === 'user'
                ? 'bg-orange-500/20 border border-orange-500/30 text-white'
                : 'bg-gray-800/80 border border-gray-700/50 text-gray-200'
            }`}>
              {m.role === 'assistant' && (
                <div className="flex items-center gap-1.5 mb-2 text-orange-400 text-xs font-semibold">
                  <span>⚡</span> PROMETHEUS AI
                </div>
              )}
              <p className="text-sm leading-relaxed whitespace-pre-wrap">{m.content}</p>
              {m.sources && m.sources.length > 0 && (
                <div className="mt-2 pt-2 border-t border-gray-700/40">
                  <p className="text-gray-600 text-[10px] mb-1">Kaynak dökümanlar:</p>
                  <div className="flex flex-wrap gap-1">
                    {m.sources.map((s, j) => (
                      <span key={j} className="text-[10px] bg-gray-700/40 text-gray-500 rounded px-1.5 py-0.5 border border-gray-700/30">
                        📄 {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-gray-800/80 border border-gray-700/50 rounded-2xl px-4 py-3">
              <div className="flex items-center gap-1.5 mb-2 text-orange-400 text-xs font-semibold">
                <span>⚡</span> PROMETHEUS AI
              </div>
              <div className="flex gap-1 items-center">
                <span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce [animation-delay:0ms]" />
                <span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce [animation-delay:150ms]" />
                <span className="w-2 h-2 bg-gray-500 rounded-full animate-bounce [animation-delay:300ms]" />
              </div>
            </div>
          </div>
        )}

        {error && (
          <div className="bg-red-900/30 border border-red-700/40 rounded-xl px-4 py-3 text-red-400 text-xs">
            {error}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="mt-4 flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && !e.shiftKey && send()}
          placeholder="Dökümanlar hakkında soru sorun..."
          disabled={loading}
          className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-white text-sm
                     placeholder:text-gray-600 focus:outline-none focus:border-orange-500 transition-colors
                     disabled:opacity-50"
        />
        <button
          onClick={() => send()}
          disabled={!input.trim() || loading}
          className="bg-orange-500 hover:bg-orange-600 disabled:bg-gray-700 disabled:text-gray-500
                     text-white font-bold rounded-xl px-5 py-3 text-sm transition-colors shrink-0"
        >
          Gönder
        </button>
      </div>
    </div>
  )
}
