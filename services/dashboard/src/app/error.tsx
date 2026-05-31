'use client'
import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error('GlobalError:', error)
  }, [error])

  return (
    <div className="flex flex-col items-center justify-center min-h-screen gap-6 p-8 text-center">
      <div className="text-4xl">⚠️</div>
      <div className="space-y-2">
        <h2 className="text-white font-bold text-lg">Sayfa yüklenirken bir hata oluştu</h2>
        <p className="text-gray-500 text-sm max-w-md">
          {error.message || 'Beklenmedik bir hata oluştu. Sayfayı yenilemeyi deneyin.'}
        </p>
        {error.digest && (
          <p className="text-gray-700 text-xs font-mono">Hata kodu: {error.digest}</p>
        )}
      </div>
      <button
        onClick={reset}
        className="px-4 py-2 bg-orange-500 hover:bg-orange-400 text-white font-semibold rounded-lg text-sm transition-colors"
      >
        Yeniden Dene
      </button>
    </div>
  )
}
