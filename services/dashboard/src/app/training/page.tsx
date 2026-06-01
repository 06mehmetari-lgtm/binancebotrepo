'use client'
import { useState, useEffect, useRef, useCallback } from 'react'

interface Doc {
  id: string
  title: string
  preview: string
  content: string
  source?: 'pdf' | 'text'
  filename?: string
  created_at: number
}

interface QueueItem {
  id: string
  title: string
  filename: string
  created_at: number
  text_length: number
  status: 'pending' | 'processing' | 'done' | 'error'
  error?: string
  processed_at?: number
  retry_after?: number
}

type UploadState = 'idle' | 'extracting' | 'queued' | 'error'

function timeAgo(ts: number) {
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 60) return `${diff}s önce`
  if (diff < 3600) return `${Math.floor(diff / 60)}dk önce`
  if (diff < 86400) return `${Math.floor(diff / 3600)}sa önce`
  return `${Math.floor(diff / 86400)}g önce`
}

function fileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'Sırada bekliyor',
  processing: 'Groq analiz ediyor...',
  done: 'Öğrenildi ✓',
  error: 'Hata',
}
const STATUS_COLOR: Record<string, string> = {
  pending: 'text-yellow-400 bg-yellow-900/30 border-yellow-700/40',
  processing: 'text-blue-400 bg-blue-900/30 border-blue-700/40',
  done: 'text-green-400 bg-green-900/30 border-green-700/40',
  error: 'text-red-400 bg-red-900/30 border-red-700/40',
}

export default function TrainingPage() {
  const [docs, setDocs] = useState<Doc[]>([])
  const [queue, setQueue] = useState<QueueItem[]>([])
  const [file, setFile] = useState<File | null>(null)
  const [title, setTitle] = useState('')
  const [uploadState, setUploadState] = useState<UploadState>('idle')
  const [statusMsg, setStatusMsg] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const fetchDocs = useCallback(async () => {
    try {
      const data = await fetch('/api/training').then(r => r.json())
      if (Array.isArray(data)) setDocs(data)
    } catch { /* ignore */ }
  }, [])

  const fetchQueue = useCallback(async () => {
    try {
      const data = await fetch('/api/training/queue').then(r => r.json())
      if (Array.isArray(data)) setQueue(data)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    fetchDocs(); fetchQueue()
    const t = setInterval(() => { fetchDocs(); fetchQueue() }, 8000)
    return () => clearInterval(t)
  }, [fetchDocs, fetchQueue])

  const handleFile = (f: File) => {
    if (!f.name.toLowerCase().endsWith('.pdf')) { setStatusMsg('Sadece PDF kabul edilir.'); return }
    setFile(f); setTitle(f.name.replace(/\.pdf$/i, '')); setStatusMsg(''); setUploadState('idle')
  }

  const handleUpload = async () => {
    if (!file) return
    setUploadState('extracting')
    setStatusMsg('PDF okunuyor — metin çıkarılıyor...')

    const fd = new FormData()
    fd.append('pdf', file)
    fd.append('title', title.trim() || file.name)

    try {
      const res = await fetch('/api/training/upload', { method: 'POST', body: fd })
      const data = await res.json()
      if (data.queued) {
        setUploadState('queued')
        setStatusMsg('Kuyruğa eklendi! Groq rate limit açılınca otomatik analiz edilecek.')
        setFile(null); setTitle('')
        if (fileInputRef.current) fileInputRef.current.value = ''
        fetchQueue()
      } else {
        setUploadState('error')
        setStatusMsg(data.error ?? 'Bir hata oluştu.')
      }
    } catch {
      setUploadState('error')
      setStatusMsg('Bağlantı hatası.')
    }
  }

  const handleDelete = async (id: string) => {
    if (!confirm('Bu dökümanı silmek istediğinizden emin misiniz?')) return
    try { await fetch(`/api/training?id=${id}`, { method: 'DELETE' }); setDocs(d => d.filter(x => x.id !== id)) }
    catch { /* ignore */ }
  }

  const pendingCount = queue.filter(q => q.status === 'pending' || q.status === 'processing').length

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      {/* Header */}
      <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/60">
        <div className="flex items-start gap-3">
          <span className="text-3xl leading-none">📚</span>
          <div className="flex-1">
            <h1 className="text-xl font-bold text-white">AI Eğitim Merkezi</h1>
            <p className="text-gray-400 text-sm mt-1">
              PDF&apos;leri yükleyin — metin hemen çıkarılır, Groq rate limit açılınca sırayla analiz edilir.
              Öğrenilen dökümanlar al/sat kararlarını destekler.
            </p>
          </div>
          {pendingCount > 0 && (
            <div className="flex items-center gap-2 bg-blue-900/30 border border-blue-700/40 rounded-lg px-3 py-2">
              <span className="inline-block w-2 h-2 bg-blue-400 rounded-full animate-pulse" />
              <span className="text-blue-400 text-xs font-semibold">{pendingCount} PDF sırada</span>
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-5">
        {/* LEFT — upload */}
        <div className="lg:col-span-2 space-y-4">
          <div className="border border-gray-800 rounded-xl p-5 bg-gray-900/60">
            <h2 className="text-white font-semibold text-sm mb-4">PDF Yükle</h2>

            <div
              className={`relative border-2 border-dashed rounded-xl p-6 text-center transition-all cursor-pointer
                ${dragging ? 'border-orange-500 bg-orange-500/5' : 'border-gray-700 hover:border-gray-600'}
                ${file ? 'bg-gray-800/40' : 'bg-gray-900/40'}`}
              onDragOver={e => { e.preventDefault(); setDragging(true) }}
              onDragLeave={() => setDragging(false)}
              onDrop={e => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files[0]; if (f) handleFile(f) }}
              onClick={() => fileInputRef.current?.click()}
            >
              <input ref={fileInputRef} type="file" accept=".pdf" className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f) }} />
              {file ? (
                <div className="space-y-2">
                  <div className="text-4xl">📄</div>
                  <p className="text-white text-sm font-semibold truncate">{file.name}</p>
                  <p className="text-gray-500 text-xs">{fileSize(file.size)}</p>
                  <button type="button" onClick={e => { e.stopPropagation(); setFile(null); setTitle(''); setUploadState('idle'); setStatusMsg('') }}
                    className="text-xs text-red-600 hover:text-red-400 transition-colors">Kaldır</button>
                </div>
              ) : (
                <div className="space-y-2">
                  <div className="text-4xl opacity-40">📁</div>
                  <p className="text-gray-400 text-sm">PDF sürükle veya tıkla</p>
                  <p className="text-gray-600 text-xs">Maksimum 20 MB</p>
                </div>
              )}
            </div>

            {file && (
              <div className="mt-3">
                <input type="text" value={title} onChange={e => setTitle(e.target.value)}
                  placeholder="Döküman başlığı..."
                  className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm
                             placeholder:text-gray-600 focus:outline-none focus:border-orange-500 transition-colors" />
              </div>
            )}

            {statusMsg && (
              <div className={`mt-3 rounded-lg px-3 py-2.5 text-xs leading-relaxed ${
                uploadState === 'queued' ? 'bg-green-900/40 border border-green-700/50 text-green-400'
                : uploadState === 'error' ? 'bg-red-900/40 border border-red-700/50 text-red-400'
                : 'bg-blue-900/40 border border-blue-700/50 text-blue-400'
              }`}>{statusMsg}</div>
            )}

            <button onClick={handleUpload} disabled={!file || uploadState === 'extracting'}
              className="mt-3 w-full bg-orange-500 hover:bg-orange-600 disabled:bg-gray-700 disabled:text-gray-500
                         text-white font-semibold rounded-lg py-2.5 text-sm transition-colors">
              {uploadState === 'extracting' ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Metin çıkarılıyor...
                </span>
              ) : 'Kuyruğa Ekle'}
            </button>
          </div>

          <div className="border border-blue-900/40 rounded-xl p-4 bg-blue-950/20">
            <h3 className="text-blue-400 text-xs font-semibold mb-2">Nasıl Çalışır?</h3>
            <ul className="text-gray-500 text-xs space-y-1.5">
              <li>• PDF yüklenir → metin anında çıkarılır → kuyruğa eklenir</li>
              <li>• agent_system her 60 saniyede kuyruğu kontrol eder</li>
              <li>• Groq rate limit açıksa Groq LLaMA 70B analiz eder</li>
              <li>• Rate limit doluysa bekler, açılınca devam eder</li>
              <li>• Öğrenilen PDF bir daha analiz edilmez</li>
              <li>• Tüm al/sat kararlarında bu bilgiler kullanılır</li>
            </ul>
          </div>
        </div>

        {/* RIGHT */}
        <div className="lg:col-span-3 space-y-4">
          {/* Queue */}
          {queue.length > 0 && (
            <div>
              <div className="flex items-center justify-between mb-2">
                <h2 className="text-white font-semibold text-sm">
                  İşlem Kuyruğu
                  <span className="ml-2 text-xs text-gray-600 font-normal">{queue.length} PDF</span>
                </h2>
                <button onClick={fetchQueue} className="text-xs text-gray-600 hover:text-gray-400">↺</button>
              </div>
              <div className="space-y-2">
                {queue.map(item => (
                  <div key={item.id} className="border border-gray-800 rounded-xl p-3 bg-gray-900/50 flex items-center gap-3">
                    <span className="text-xl shrink-0">📄</span>
                    <div className="flex-1 min-w-0">
                      <p className="text-white text-sm font-semibold truncate">{item.title}</p>
                      <p className="text-gray-600 text-xs">{item.filename} · {(item.text_length / 1000).toFixed(0)}K karakter · {timeAgo(item.created_at)}</p>
                      {item.error === 'rate_limit' && item.retry_after && (
                        <p className="text-yellow-600 text-xs mt-0.5">
                          Rate limit — {Math.max(0, Math.ceil((item.retry_after - Date.now() / 1000) / 60))} dk sonra tekrar denenecek
                        </p>
                      )}
                    </div>
                    <span className={`text-xs px-2 py-1 rounded border font-medium shrink-0 ${STATUS_COLOR[item.status] ?? STATUS_COLOR.pending}`}>
                      {item.status === 'processing' && (
                        <span className="inline-block w-2.5 h-2.5 border-2 border-blue-400 border-t-transparent rounded-full animate-spin mr-1 align-middle" />
                      )}
                      {STATUS_LABEL[item.status] ?? item.status}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Learned docs */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h2 className="text-white font-semibold text-sm">
                Öğrenilmiş Dökümanlar
                <span className="ml-2 text-xs text-gray-600 font-normal">{docs.length} döküman aktif</span>
              </h2>
              <button onClick={fetchDocs} className="text-xs text-gray-600 hover:text-gray-400">↺</button>
            </div>

            {docs.length === 0 ? (
              <div className="border border-gray-800 rounded-xl p-10 bg-gray-900/40 text-center">
                <p className="text-4xl mb-3 opacity-30">📂</p>
                <p className="text-gray-600 text-sm">Henüz öğrenilmiş döküman yok.</p>
                <p className="text-gray-700 text-xs mt-1">PDF yükleyin — kuyruktan işlenince burada görünür.</p>
              </div>
            ) : (
              <div className="space-y-2">
                {docs.map(doc => (
                  <div key={doc.id} className="border border-gray-800 rounded-xl bg-gray-900/50 overflow-hidden">
                    <div className="flex items-start gap-3 p-4">
                      <span className="text-xl shrink-0 mt-0.5">📄</span>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                          <span className="text-white font-semibold text-sm truncate">{doc.title}</span>
                          <span className="text-xs bg-green-900/40 text-green-400 border border-green-700/40 px-1.5 py-0.5 rounded shrink-0">Öğrenildi</span>
                          <span className="text-gray-700 text-xs shrink-0">{timeAgo(doc.created_at)}</span>
                        </div>
                        {doc.filename && <p className="text-gray-600 text-[11px] mb-1">{doc.filename}</p>}
                        <p className="text-gray-500 text-xs leading-relaxed line-clamp-2">{doc.preview}</p>
                      </div>
                      <div className="flex gap-1 shrink-0">
                        <button onClick={() => setExpandedId(expandedId === doc.id ? null : doc.id)}
                          className="text-xs text-gray-600 hover:text-gray-300 px-2 py-1 rounded hover:bg-gray-800 transition-colors">
                          {expandedId === doc.id ? '▲' : '▼'}
                        </button>
                        <button onClick={() => handleDelete(doc.id)}
                          className="text-xs text-red-800 hover:text-red-400 px-2 py-1 rounded hover:bg-red-900/20 transition-colors">
                          Sil
                        </button>
                      </div>
                    </div>
                    {expandedId === doc.id && (
                      <div className="border-t border-gray-800 px-4 pb-4 pt-3">
                        <pre className="text-gray-400 text-xs leading-relaxed whitespace-pre-wrap font-mono
                                        max-h-96 overflow-y-auto bg-gray-950/50 rounded p-3 border border-gray-800/60">
                          {doc.content}
                        </pre>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
