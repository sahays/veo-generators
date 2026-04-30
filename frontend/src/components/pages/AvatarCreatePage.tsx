import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, ImagePlus, Loader2, User, Zap, Film } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { Select } from '@/components/UI'
import { api } from '@/lib/api'
import { AvatarPresetGrid } from '@/components/pages/avatar/AvatarPresetGrid'
import {
  LANGUAGE_OPTIONS,
  PRESET_CATALOG,
  STYLE_LABELS,
  VOICE_CATALOG,
  type AvatarStyle,
  type AvatarVersion,
  type AvatarVoice,
  type Gender,
} from '@/types/avatar'

const STYLE_OPTIONS: { value: AvatarStyle; label: string; description: string }[] = [
  { value: 'to_the_point', label: STYLE_LABELS.to_the_point, description: 'Minimal words, direct, no preamble' },
  { value: 'talkative', label: STYLE_LABELS.talkative, description: 'Friendly, warm, expressive' },
  { value: 'funny', label: STYLE_LABELS.funny, description: 'Light, playful, a touch of humor' },
  { value: 'serious', label: STYLE_LABELS.serious, description: 'Measured, factual, no jokes' },
  { value: 'cynical', label: STYLE_LABELS.cynical, description: 'Wry, slightly skeptical, dry tone' },
]

type GenderFilter = 'all' | Gender

export const AvatarCreatePage = () => {
  const navigate = useNavigate()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [version, setVersion] = useState<AvatarVersion>('v2')
  const [name, setName] = useState('')
  const [style, setStyle] = useState<AvatarStyle>('to_the_point')
  const [persona, setPersona] = useState('')

  // v2 picker state
  const [genderFilter, setGenderFilter] = useState<GenderFilter>('all')
  const [presetName, setPresetName] = useState<string>('Kira')
  const [voice, setVoice] = useState<AvatarVoice>('Kore')
  const [language, setLanguage] = useState<string>('en-US')
  const [defaultGreeting, setDefaultGreeting] = useState<string>('')
  const [enableGrounding, setEnableGrounding] = useState<boolean>(false)

  // v1 upload state
  const [imageGcsUri, setImageGcsUri] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploading, setUploading] = useState(false)

  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const isV2 = version === 'v2'

  const filteredPresets = useMemo(
    () =>
      genderFilter === 'all'
        ? PRESET_CATALOG
        : PRESET_CATALOG.filter((p) => p.gender === genderFilter),
    [genderFilter],
  )
  const filteredVoices = useMemo(
    () =>
      genderFilter === 'all'
        ? VOICE_CATALOG
        : VOICE_CATALOG.filter((v) => v.gender === genderFilter),
    [genderFilter],
  )

  // When the gender chip changes, snap selections to the filtered set.
  useEffect(() => {
    if (!isV2 || genderFilter === 'all') return
    if (filteredPresets.length && !filteredPresets.find((p) => p.id === presetName)) {
      setPresetName(filteredPresets[0].id)
    }
    if (filteredVoices.length && !filteredVoices.find((v) => v.id === voice)) {
      setVoice(filteredVoices[0].id)
    }
  }, [isV2, genderFilter, filteredPresets, filteredVoices, presetName, voice])

  const handleFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    setUploading(true)
    setUploadProgress(0)
    setPreviewUrl(URL.createObjectURL(file))
    try {
      const { promise } = api.assets.directUpload(file, setUploadProgress)
      const result = await promise
      setImageGcsUri(result.gcs_uri)
      setPreviewUrl(result.signed_url || URL.createObjectURL(file))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
      setImageGcsUri(null)
    } finally {
      setUploading(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setError('Name is required.')
      return
    }
    if (!isV2 && !imageGcsUri) {
      setError('Portrait image is required for v1.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      const payload: Parameters<typeof api.avatars.create>[0] = {
        name: name.trim(),
        style,
        persona_prompt: persona.trim(),
        version,
      }
      if (isV2) {
        payload.voice = voice
        payload.preset_name = presetName
        payload.language = language
        if (defaultGreeting.trim()) {
          payload.default_greeting = defaultGreeting.trim()
        }
        payload.enable_grounding = enableGrounding
      } else {
        payload.image_gcs_uri = imageGcsUri ?? ''
      }
      const created = await api.avatars.create(payload)
      navigate(`/avatars/${created.id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Create failed')
      setSubmitting(false)
    }
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="max-w-2xl mx-auto space-y-6"
    >
      <button
        onClick={() => navigate('/avatars')}
        className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft size={14} /> Back to Avatars
      </button>

      <div>
        <h2 className="text-2xl font-heading text-foreground tracking-tight">New Avatar</h2>
        <p className="text-sm text-muted-foreground mt-1">
          {isV2
            ? 'Pick an avatar and a voice. The avatar streams live audio + video — type or speak to it.'
            : 'Upload a portrait and pick a tone. The avatar will reply to questions as a short lip-synced video.'}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card className="p-5 space-y-5">
          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">
              Method
            </label>
            <div className="grid grid-cols-2 gap-2">
              <MethodTile
                active={version === 'v1'}
                icon={Film}
                title="v1 — High Accuracy"
                subtitle="Per-turn lip-synced video. Higher quality, ~minute latency."
                onClick={() => setVersion('v1')}
              />
              <MethodTile
                active={version === 'v2'}
                icon={Zap}
                title="v2 — Low Latency"
                subtitle="Real-time fixed avatar. Streams audio + video instantly."
                onClick={() => setVersion('v2')}
              />
            </div>
          </div>

          {!isV2 && (
            <div>
              <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">
                Portrait
              </label>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                onChange={handleFile}
                className="hidden"
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="w-full aspect-[3/4] max-w-[240px] rounded-lg border-2 border-dashed border-border hover:border-accent/50 transition-colors bg-muted/20 flex items-center justify-center overflow-hidden cursor-pointer disabled:cursor-wait"
              >
                {previewUrl ? (
                  <img src={previewUrl} alt="" className="w-full h-full object-cover" />
                ) : (
                  <div className="flex flex-col items-center gap-2 text-muted-foreground">
                    <ImagePlus size={28} />
                    <span className="text-xs">Click to upload</span>
                  </div>
                )}
              </button>
              {uploading && (
                <div className="mt-2 h-1 bg-muted rounded-full overflow-hidden max-w-[240px]">
                  <div
                    className="h-full bg-accent transition-all"
                    style={{ width: `${uploadProgress}%` }}
                  />
                </div>
              )}
            </div>
          )}

          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Aanya"
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 text-sm"
              required
            />
          </div>

          {isV2 && (
            <>
              <AvatarPresetGrid
                presetName={presetName}
                setPresetName={setPresetName}
                genderFilter={genderFilter}
                setGenderFilter={setGenderFilter}
                filteredPresets={filteredPresets}
              />

              <div>
                <Select
                  label={`Voice (${filteredVoices.length} available)`}
                  value={voice}
                  onChange={(v) => setVoice(v as AvatarVoice)}
                  options={filteredVoices.map((v) => ({
                    value: v.id,
                    label: v.id,
                    description: `${v.description} · ${v.gender}`,
                  }))}
                />
              </div>

              <div>
                <Select
                  label="Language"
                  value={language}
                  onChange={(v) => setLanguage(v)}
                  options={LANGUAGE_OPTIONS.map((l) => ({
                    value: l.value,
                    label: l.label,
                    description: l.value,
                  }))}
                />
              </div>

              <div>
                <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">
                  Default greeting (optional)
                </label>
                <input
                  type="text"
                  value={defaultGreeting}
                  onChange={(e) => setDefaultGreeting(e.target.value)}
                  placeholder="e.g. Hi! I'm ready to help — what's on your mind?"
                  className="w-full px-3 py-2 rounded-lg bg-muted border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 text-sm"
                />
                <p className="text-[11px] text-muted-foreground mt-1">
                  Spoken first thing on connect, before any user input.
                </p>
              </div>

              <label className="flex items-start gap-3 cursor-pointer">
                <input
                  type="checkbox"
                  checked={enableGrounding}
                  onChange={(e) => setEnableGrounding(e.target.checked)}
                  className="mt-0.5 h-4 w-4 rounded border-border text-accent focus:ring-2 focus:ring-accent/30"
                />
                <span className="text-sm">
                  <span className="font-medium">Enable Google Search grounding</span>
                  <span className="block text-[11px] text-muted-foreground mt-0.5">
                    Lets the avatar look up live facts on the web for current
                    events, prices, scores, etc.
                  </span>
                </span>
              </label>
            </>
          )}

          {!isV2 && (
            <div>
              <Select
                label="Tone"
                value={style}
                onChange={(v) => setStyle(v as AvatarStyle)}
                options={STYLE_OPTIONS}
              />
            </div>
          )}

          <div>
            <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">
              Persona note (optional)
            </label>
            <textarea
              value={persona}
              onChange={(e) => setPersona(e.target.value)}
              rows={3}
              placeholder="e.g. A senior product manager at a tech startup who answers questions about AI."
              className="w-full px-3 py-2 rounded-lg bg-muted border border-border focus:outline-none focus:ring-2 focus:ring-accent/30 text-sm resize-y"
            />
          </div>
        </Card>

        {error && (
          <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-3">
          <Button
            type="submit"
            icon={submitting ? Loader2 : User}
            disabled={
              submitting || uploading || !name.trim() || (!isV2 && !imageGcsUri)
            }
          >
            {submitting ? 'Creating…' : 'Create Avatar'}
          </Button>
        </div>
      </form>
    </motion.div>
  )
}

interface MethodTileProps {
  active: boolean
  icon: typeof Zap
  title: string
  subtitle: string
  onClick: () => void
}

const MethodTile = ({ active, icon: Icon, title, subtitle, onClick }: MethodTileProps) => (
  <button
    type="button"
    onClick={onClick}
    className={`text-left p-3 rounded-lg border transition-colors ${
      active
        ? 'border-accent/60 bg-accent/10'
        : 'border-border bg-muted/20 hover:border-accent/30'
    }`}
  >
    <div className="flex items-center gap-2 mb-1">
      <Icon size={14} className={active ? 'text-accent' : 'text-muted-foreground'} />
      <span className="text-sm font-medium">{title}</span>
    </div>
    <div className="text-xs text-muted-foreground leading-snug">{subtitle}</div>
  </button>
)

