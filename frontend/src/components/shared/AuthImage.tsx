import React, { useState, useEffect } from 'react'
import api from '@/lib/api'

const AuthImage: React.FC<React.ImgHTMLAttributes<HTMLImageElement>> = ({ src, alt, ...props }) => {
  const [blobUrl, setBlobUrl] = useState<string | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    setError(false)
    setBlobUrl(null)
    if (!src) return
    if (!src.startsWith('/api/')) {
      setBlobUrl(src)
      return
    }

    const apiPath = src.replace(/^\/api\/v1/, '')

    let revoke: string | null = null
    api.get(apiPath, { responseType: 'blob' })
      .then((res) => {
        const url = URL.createObjectURL(res.data)
        revoke = url
        setBlobUrl(url)
      })
      .catch(() => setError(true))

    return () => {
      if (revoke) URL.revokeObjectURL(revoke)
    }
  }, [src])

  if (error) return <span className="text-gray-500 text-sm">[图片加载失败]</span>
  if (!blobUrl) return <span className="text-gray-500 text-sm">加载中...</span>
  return <img src={blobUrl} alt={alt} {...props} />
}

export default AuthImage
