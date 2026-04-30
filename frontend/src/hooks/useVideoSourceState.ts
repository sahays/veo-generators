import { useEffect, useState } from 'react'

export type VideoSourceTab = 'productions' | 'past-uploads'

interface SourceLoaders<U, P> {
  loadUploads: () => Promise<U[]>
  loadProductions: () => Promise<P[]>
}

interface UseVideoSourceStateOptions {
  initialTab?: VideoSourceTab
  enabled?: boolean
}

/**
 * Shared scaffolding for the WorkPage video-source pickers (Promo, Reframe,
 * Thumbnails, KeyMoments, …). Owns the tab + selection + load state so each
 * page only deals with its feature-specific bits.
 */
export function useVideoSourceState<U, P>(
  loaders: SourceLoaders<U, P>,
  { initialTab = 'past-uploads', enabled = true }: UseVideoSourceStateOptions = {},
) {
  const [sourceTab, setSourceTab] = useState<VideoSourceTab>(initialTab)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [gcsUri, setGcsUri] = useState<string | null>(null)
  const [videoFilename, setVideoFilename] = useState('')
  const [productions, setProductions] = useState<P[]>([])
  const [uploads, setUploads] = useState<U[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!enabled) return
    setLoading(true)
    Promise.all([
      loaders.loadUploads().catch(() => [] as U[]),
      loaders.loadProductions().catch(() => [] as P[]),
    ])
      .then(([ups, prods]) => {
        setUploads(ups)
        setProductions(prods)
      })
      .finally(() => setLoading(false))
    // loaders is a config object; re-running on its identity would force every
    // caller to memoize. enabled is the gate that matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled])

  const select = (url: string | null, uri: string | null, name: string) => {
    setVideoUrl(url)
    setGcsUri(uri)
    setVideoFilename(name)
  }

  return {
    sourceTab,
    setSourceTab,
    videoUrl,
    gcsUri,
    videoFilename,
    setVideoFilename,
    productions,
    uploads,
    loading,
    select,
  }
}
