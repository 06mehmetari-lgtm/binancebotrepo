'use client'
import { useState, useEffect, useRef } from 'react'

interface Doc {
  id: string
  title: string
  preview: string
  content: string
  created_at: number
}

function timeAgo(ts: number) {
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s önce`
  if (diff < 3600) return `${Math.floor(diff / 60)}dk önce`
  if (diff < 86400) return `${Math.floor(diff / 3600)}sa önce`
  return `${Math.floor(diff / 86400)}g önce`
}

export default function TrainingPage() {
  const [docs, setDocs] = useState<Doc[]>([])
  const [title, setTitle] = useState('')
  const [content, setContent] = useState('')
  const [sending, setSending] = useState(false)
  const [status, setStatus] = useState<{ type: 'ok' | 'err'; msg: string } | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const fetchDocs = async () => {
    try {
      const data = await fetch('/api/training').then(r => r.json())
      if (Array.isArray(data)) setDocs(data)
    } catch {}
  }

  useEffect(() => { fetchDocs() }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !content.trim()) {
      setStatus({ type: 'err', msg: 'Başlık ve içerik zorunlu.' })
      return
    }
    setSending(true)
    setStatus(null)
    try {
      const res = await fetch('/api/training', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: title.trim(), content: content.trim() }),
      })
      const data = await res.json()
      if (data.ok) {
        setStatus({ type: 'ok', msg: 'Döküman kaydedildi! AI bir sonraki taramada bunu uygulayacak.' })
        setTitle('')
        setContent('')
        fetchDocs()
      } else {
        setStatus({ type: 'err', msg: data.error ?? 'Hata oluştu.' })
      }
    } catch {
      setStatus({ type: 'err', msg: 'Bağlantı hatası.' })
    } finally {
      setSending(false)
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Bu dökümanı silmek istediğinizden emin misiniz?')) return
    try {
      await fetch(`/api/training?id=${id}`, { method: 'DELETE' })
      setDocs(d => d.filter(x => x.id !== id))
    } catch {}
  }

  const examples = [
    'Bitcoin yalnızca RSI 30\'un altındayken long al.',
    'Funding rate %0.1 üzerindeyse short sinyali verme.',
    'Regime "volatile" iken işlem açma, sadece flat kal.',
    'ETH ve SOL için short sinyallerini görmezden gel.',
    'Trend yönünde işlem aç, karşı trend sinyallerini reddet.',
  ]

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      {/* Header */}
      <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/60">
        <div className="flex items-start gap-3">
          <span className="text-3xl leading-none">📚</span>
          <div>
            <h1 className="text-xl font-bold text-white">AI Eğitim Merkezi</h1>
            <p className="text-gray-400 text-sm mt-1">
              Sisteme kendi kurallarınızı ve stratejilerinizi öğretin. Yazdığınız her döküman,
              AI ajanların analiz sırasında dikkate aldığı operatör talimatlarına eklenir.
              İngilizce veya Türkçe yazabilirsiniz.
            </p>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        {/* LEFT — form */}
        <div className="lg:col-span-2 space-y-4">
          <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/60">
            <h2 className="text-white font-semibold text-sm mb-4">Yeni Döküman Ekle</h2>
            <form onSubmit={handleSubmit} className="space-y-3">
              <div>
                <label className="text-gray-400 text-xs block mb-1">Başlık</label>
                <input
                  type="text"
                  value={title}
                  onChange={e => setTitle(e.target.value)}
                  placeholder="ör: Risk Yönetimi Kuralları"
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm
                             placeholder:text-gray-600 focus:outline-none focus:border-orange-500 transition-colors"
                />
              </div>
              <div>
                <label className="text-gray-400 text-xs block mb-1">İçerik (strateji, kural, döküman...)</label>
                <textarea
                  ref={textareaRef}
                  value={content}
                  onChange={e => setContent(e.target.value)}
                  placeholder="Sisteme öğretmek istediğiniz kuralları, stratejileri veya belgeleri buraya yazın ya da yapıştırın..."
                  rows={12}
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm
                             placeholder:text-gray-600 focus:outline-none focus:border-orange-500 transition-colors
                             resize-y font-mono leading-relaxed"
                />
                <p className="text-gray-700 text-xs mt-1 text-right">{content.length} karakter</p>
              </div>

              {status && (
                <div className={`rounded-lg px-3 py-2 text-xs ${
                  status.type === 'ok'
                    ? 'bg-green-900/40 border border-green-700/50 text-green-400'
                    : 'bg-red-900/40 border border-red-700/50 text-red-400'
                }`}>
                  {status.msg}
                </div>
              )}

              <button
                type="submit"
                disabled={sending}
                className="w-full bg-orange-500 hover:bg-orange-600 disabled:bg-gray-700 disabled:text-gray-500
                           text-white font-semibold rounded-lg py-2.5 text-sm transition-colors"
              >
                {sending ? 'Kaydediliyor...' : 'AI\'ya Öğret'}
              </button>
            </form>
          </div>

          {/* Quick examples */}
          <div className="border border-gray-800 rounded-xl p-4 bg-gray-900/40">
            <h3 className="text-gray-400 text-xs font-semibold mb-3 uppercase tracking-wider">Örnek Talimatlar</h3>
            <div className="space-y-2">
              {examples.map((ex, i) => (
                <button
                  key={i}
                  onClick={() => {
                    setContent(prev => prev ? prev + '\n' + ex : ex)
                    textareaRef.current?.focus()
                  }}
                  className="w-full text-left text-xs text-gray-500 hover:text-gray-300 hover:bg-gray-800/60
                             rounded px-2 py-1.5 transition-colors border border-transparent hover:border-gray-700/50"
                >
                  <span className="text-gray-700 mr-1">+</span> {ex}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* RIGHT — saved docs */}
        <div className="lg:col-span-3 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-white font-semibold text-sm">
              Kayıtlı Dökümanlar
              <span className="ml-2 text-xs text-gray-600 font-normal">{docs.length} döküman</span>
            </h2>
            <button onClick={fetchDocs} className="text-xs text-gray-600 hover:text-gray-400 transition-colors">
              ↺ Yenile
            </button>
          </div>

          {docs.length === 0 ? (
            <div className="border border-gray-800 rounded-xl p-8 bg-gray-900/40 text-center">
              <p className="text-gray-600 text-sm">Henüz döküman eklenmedi.</p>
              <p className="text-gray-700 text-xs mt-1">Sol taraftaki formu kullanarak AI&apos;ya strateji öğretin.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {docs.map(doc => (
                <div
                  key={doc.id}
                  className="border border-gray-800 rounded-xl bg-gray-900/50 overflow-hidden"
                >
                  <div className="flex items-start gap-3 p-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="text-white font-semibold text-sm truncate">{doc.title}</span>
                        <span className="text-gray-700 text-xs shrink-0">{timeAgo(doc.created_at)}</span>
                      </div>
                      <p className="text-gray-500 text-xs leading-relaxed line-clamp-2">{doc.preview}</p>
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => setExpandedId(expandedId === doc.id ? null : doc.id)}
                        className="text-xs text-gray-600 hover:text-gray-300 px-2 py-1 rounded
                                   hover:bg-gray-800 transition-colors"
                      >
                        {expandedId === doc.id ? '▲' : '▼'}
                      </button>
                      <button
                        onClick={() => handleDelete(doc.id)}
                        className="text-xs text-red-800 hover:text-red-400 px-2 py-1 rounded
                                   hover:bg-red-900/20 transition-colors"
                      >
                        Sil
                      </button>
                    </div>
                  </div>

                  {expandedId === doc.id && (
                    <div className="border-t border-gray-800 px-4 pb-4 pt-3">
                      <pre className="text-gray-400 text-xs leading-relaxed whitespace-pre-wrap font-mono
                                      max-h-64 overflow-y-auto bg-gray-950/50 rounded p-3 border border-gray-800/60">
                        {doc.content}
                      </pre>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* Info card */}
          <div className="border border-blue-900/40 rounded-xl p-4 bg-blue-950/20">
            <h3 className="text-blue-400 text-xs font-semibold mb-2">Nasıl Çalışır?</h3>
            <ul className="text-gray-500 text-xs space-y-1.5 leading-relaxed">
              <li>• Dökümanlar Redis&apos;te <code className="text-gray-400">training:docs</code> anahtarında saklanır</li>
              <li>• AI analiz sırasında (LLM sentez aşaması) bu talimatlar prompt&apos;a eklenir</li>
              <li>• Groq 70B ve Ollama modelleri bu talimatları dikkate alarak karar verir</li>
              <li>• Değişiklikler anında geçerli olur — servis yeniden başlatma gerekmez</li>
              <li>• Birden fazla döküman ekleyebilirsiniz (hepsi birleştirilerek gönderilir)</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  )
}
