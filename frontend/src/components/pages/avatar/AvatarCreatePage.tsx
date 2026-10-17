import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import { ArrowLeft, ImagePlus, Loader2, User, Zap, Film } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/UI'
import { api } from '@/hooks/useApiClient'
import { AvatarPresetGrid } from '@/components/pages/avatar/components/AvatarPresetGrid'
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

interface MethodTileProps {
  active: boolean
  icon: typeof Zap
  title: string
  subtitle: string
  onClick: () => void
}

const MethodTile = ({ active, icon: Icon, title, subtitle, onClick }: MethodTileProps) => (
  <Button
    type="button"
    variant="unstyled"
    onClick={onClick}
    className={`text-left p-3 rounded-[6px] border transition-colors block ${
      active ? 'border-accent/60 bg-accent/10' : 'border-border bg-muted/20 hover:border-accent/30'
    }`}
  >
    <div className="flex items-center gap-2 mb-1">
      <Icon size={14} className={active ? 'text-accent' : 'text-muted-foreground'} />
      <span className="text-sm font-medium">{title}</span>
    </div>
    <div className="text-xs text-muted-foreground leading-snug">{subtitle}</div>
  </Button>
)

const PortraitUploadSection = ({
  previewUrl,
  uploading,
  uploadProgress,
  onSelectFile,
}: {
  previewUrl: string | null
  uploading: boolean
  uploadProgress: number
  onSelectFile: (e: ChangeEvent<HTMLInputElement>) => void
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null)
  return (
    <div>
      <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">Portrait</label>
      <input ref={fileInputRef} type="file" accept="image/*" onChange={onSelectFile} className="hidden" />
      <Button
        type="button"
        variant="unstyled"
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
      </Button>
      {uploading && (
        <div className="mt-2 h-1 bg-muted rounded-full overflow-hidden max-w-[240px]">
          <div className="h-full bg-accent transition-all" style={{ width: `${uploadProgress}%` }} />
        </div>
      )}
    </div>
  )
}

interface V2PickerConfigProps {
  presetName: string
  setPresetName: (v: string) => void
  genderFilter: GenderFilter
  setGenderFilter: (v: GenderFilter) => void
  voice: AvatarVoice
  setVoice: (v: AvatarVoice) => void
  language: string
  setLanguage: (v: string) => void
  defaultGreeting: string
  setDefaultGreeting: (v: string) => void
  enableGrounding: boolean
  setEnableGrounding: (v: boolean) => void
}

const V2ExtraFields = ({
  defaultGreeting,
  setDefaultGreeting,
  enableGrounding,
  setEnableGrounding,
}: {
  defaultGreeting: string
  setDefaultGreeting: (v: string) => void
  enableGrounding: boolean
  setEnableGrounding: (v: boolean) => void
}) => (
  <>
    <div>
      <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">
        Default greeting (optional)
      </label>
      <Input
        type="text"
        value={defaultGreeting}
        onChange={(e) => setDefaultGreeting(e.target.value)}
        placeholder="e.g. Hi! I'm ready to help — what's on your mind?"
      />
      <p className="text-[11px] text-muted-foreground mt-1">Spoken first thing on connect, before any user input.</p>
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
          Lets the avatar look up live facts on the web for current events, prices, scores, etc.
        </span>
      </span>
    </label>
  </>
)

const V2PickerConfig = (props: V2PickerConfigProps) => {
  const { presetName, setPresetName, genderFilter, setGenderFilter, voice, setVoice, language, setLanguage } = props
  const filteredPresets = useMemo(
    () => (genderFilter === 'all' ? PRESET_CATALOG : PRESET_CATALOG.filter((p) => p.gender === genderFilter)),
    [genderFilter],
  )
  const filteredVoices = useMemo(
    () => (genderFilter === 'all' ? VOICE_CATALOG : VOICE_CATALOG.filter((v) => v.gender === genderFilter)),
    [genderFilter],
  )

  useEffect(() => {
    if (genderFilter === 'all') return
    if (filteredPresets.length && !filteredPresets.find((p) => p.id === presetName)) setPresetName(filteredPresets[0].id)
    if (filteredVoices.length && !filteredVoices.find((v) => v.id === voice)) setVoice(filteredVoices[0].id)
  }, [genderFilter, filteredPresets, filteredVoices, presetName, voice, setPresetName, setVoice])

  const voiceOpts = filteredVoices.map((v) => ({ value: v.id, label: v.id, description: `${v.description} · ${v.gender}` }))
  const langOpts = LANGUAGE_OPTIONS.map((l) => ({ value: l.value, label: l.label, description: l.value }))
  return (
    <>
      <AvatarPresetGrid presetName={presetName} setPresetName={setPresetName} genderFilter={genderFilter} setGenderFilter={setGenderFilter} filteredPresets={filteredPresets} />
      <Select label={`Voice (${filteredVoices.length} available)`} value={voice} onChange={(v) => setVoice(v as AvatarVoice)} options={voiceOpts} />
      <Select label="Language" value={language} onChange={setLanguage} options={langOpts} />
      <V2ExtraFields defaultGreeting={props.defaultGreeting} setDefaultGreeting={props.setDefaultGreeting} enableGrounding={props.enableGrounding} setEnableGrounding={props.setEnableGrounding} />
    </>
  )
}

function buildAvatarPayload(params: {
  name: string
  style: AvatarStyle
  persona: string
  version: AvatarVersion
  voice: AvatarVoice
  presetName: string
  language: string
  defaultGreeting: string
  enableGrounding: boolean
  imageGcsUri: string | null
}): Parameters<typeof api.avatars.create>[0] {
  const payload: Parameters<typeof api.avatars.create>[0] = {
    name: params.name.trim(),
    style: params.style,
    persona_prompt: params.persona.trim(),
    version: params.version,
  }
  if (params.version === 'v2') {
    payload.voice = params.voice
    payload.preset_name = params.presetName
    payload.language = params.language
    if (params.defaultGreeting.trim()) payload.default_greeting = params.defaultGreeting.trim()
    payload.enable_grounding = params.enableGrounding
  } else {
    payload.image_gcs_uri = params.imageGcsUri ?? ''
  }
  return payload
}

function usePortraitUpload(setError: (msg: string | null) => void) {
  const [imageGcsUri, setImageGcsUri] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [uploading, setUploading] = useState(false)

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
  return { imageGcsUri, previewUrl, uploadProgress, uploading, handleFile }
}

const AvatarCreateHeader = ({ isV2, onBack }: { isV2: boolean; onBack: () => void }) => (
  <>
    <Button variant="ghost" size="sm" icon={ArrowLeft} onClick={onBack} className="text-muted-foreground hover:text-foreground -ml-2">
      Back to Avatars
    </Button>
    <div>
      <h2 className="text-2xl font-heading text-foreground tracking-tight">New Avatar</h2>
      <p className="text-sm text-muted-foreground mt-1">
        {isV2
          ? 'Pick an avatar and a voice. The avatar streams live audio + video — type or speak to it.'
          : 'Upload a portrait and pick a tone. The avatar will reply to questions as a short lip-synced video.'}
      </p>
    </div>
  </>
)

const MethodSelectorRow = ({ version, setVersion }: { version: AvatarVersion; setVersion: (v: AvatarVersion) => void }) => (
  <div>
    <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">Method</label>
    <div className="grid grid-cols-2 gap-2">
      <MethodTile active={version === 'v1'} icon={Film} title="v1 — High Accuracy" subtitle="Per-turn lip-synced video. Higher quality, ~minute latency." onClick={() => setVersion('v1')} />
      <MethodTile active={version === 'v2'} icon={Zap} title="v2 — Low Latency" subtitle="Real-time fixed avatar. Streams audio + video instantly." onClick={() => setVersion('v2')} />
    </div>
  </div>
)

function useAvatarCreateFormState() {
  const [version, setVersion] = useState<AvatarVersion>('v2')
  const [name, setName] = useState('')
  const [style, setStyle] = useState<AvatarStyle>('to_the_point')
  const [persona, setPersona] = useState('')
  const [genderFilter, setGenderFilter] = useState<GenderFilter>('all')
  const [presetName, setPresetName] = useState<string>('Kira')
  const [voice, setVoice] = useState<AvatarVoice>('Kore')
  const [language, setLanguage] = useState<string>('en-US')
  const [defaultGreeting, setDefaultGreeting] = useState<string>('')
  const [enableGrounding, setEnableGrounding] = useState<boolean>(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const upload = usePortraitUpload(setError)

  return {
    version, setVersion, name, setName, style, setStyle, persona, setPersona,
    genderFilter, setGenderFilter, presetName, setPresetName, voice, setVoice,
    language, setLanguage, defaultGreeting, setDefaultGreeting,
    enableGrounding, setEnableGrounding, submitting, setSubmitting, error, setError,
    ...upload,
  }
}

type FormState = ReturnType<typeof useAvatarCreateFormState>

const AvatarFormCard = ({ s }: { s: FormState }) => {
  const isV2 = s.version === 'v2'
  return (
    <Card className="p-5 space-y-5">
      <MethodSelectorRow version={s.version} setVersion={s.setVersion} />
      {!isV2 && <PortraitUploadSection previewUrl={s.previewUrl} uploading={s.uploading} uploadProgress={s.uploadProgress} onSelectFile={s.handleFile} />}
      <div>
        <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">Name</label>
        <Input type="text" value={s.name} onChange={(e) => s.setName(e.target.value)} placeholder="e.g. Aanya" required />
      </div>
      {isV2 ? (
        <V2PickerConfig presetName={s.presetName} setPresetName={s.setPresetName} genderFilter={s.genderFilter} setGenderFilter={s.setGenderFilter} voice={s.voice} setVoice={s.setVoice} language={s.language} setLanguage={s.setLanguage} defaultGreeting={s.defaultGreeting} setDefaultGreeting={s.setDefaultGreeting} enableGrounding={s.enableGrounding} setEnableGrounding={s.setEnableGrounding} />
      ) : (
        <Select label="Tone" value={s.style} onChange={(v) => s.setStyle(v as AvatarStyle)} options={STYLE_OPTIONS} />
      )}
      <div>
        <label className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2 block">Persona note (optional)</label>
        <Textarea value={s.persona} onChange={(e) => s.setPersona(e.target.value)} rows={3} placeholder="e.g. A senior product manager at a tech startup who answers questions about AI." />
      </div>
    </Card>
  )
}

export const AvatarCreatePage = () => {
  const navigate = useNavigate()
  const s = useAvatarCreateFormState()
  const isV2 = s.version === 'v2'

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!s.name.trim() || (!isV2 && !s.imageGcsUri)) {
      s.setError(!s.name.trim() ? 'Name is required.' : 'Portrait image is required for v1.')
      return
    }
    s.setSubmitting(true); s.setError(null)
    try {
      const created = await api.avatars.create(buildAvatarPayload(s))
      navigate(`/avatars/${created.id}`)
    } catch (err) {
      s.setError(err instanceof Error ? err.message : 'Create failed'); s.setSubmitting(false)
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} className="max-w-2xl mx-auto space-y-6">
      <AvatarCreateHeader isV2={isV2} onBack={() => navigate('/avatars')} />
      <form onSubmit={handleSubmit} className="space-y-6">
        <AvatarFormCard s={s} />
        {s.error && <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-500 text-xs">{s.error}</div>}
        <div className="flex justify-end gap-3">
          <Button type="submit" icon={s.submitting ? Loader2 : User} disabled={s.submitting || s.uploading || !s.name.trim() || (!isV2 && !s.imageGcsUri)}>{s.submitting ? 'Creating…' : 'Create Avatar'}</Button>
        </div>
      </form>
    </motion.div>
  )
}

