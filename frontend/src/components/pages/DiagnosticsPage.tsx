import { useState } from 'react'
import { motion } from 'framer-motion'
import { Upload, Sparkles, ImageIcon, Video, Loader2, ExternalLink, Cpu, DollarSign } from 'lucide-react'
import { Button, Card } from '@/components/Common'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

export const DiagnosticsPage = () => {
  return (
    <div className="max-w-5xl mx-auto space-y-8 pb-20">
      <div className="space-y-1">
        <h2 className="text-2xl font-heading text-foreground tracking-tight">System Diagnostics</h2>
        <p className="text-sm text-muted-foreground">Test core infrastructure: GCS Storage and Generative AI Models.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <StorageTest />
        <PromptOptimizationTest />
        <ImageGenerationTest />
        <VideoGenerationTest />
      </div>
    </div>
  )
}

const StorageTest = () => {
  const [file, setFile] = useState<File | null>(null)
  const [result, setResult] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [uploadSuccess, setUploadSuccess] = useState(false)

  const handleUpload = async () => {
    if (!file) return
    setIsLoading(true)
    setUploadSuccess(false)
    setResult(null)
    try {
      const data = await api.assets.upload(file)
      setResult(data)
      setUploadSuccess(true)
    } catch (err) {
      console.error(err)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card 
      title="GCS Storage Test" 
      icon={Upload}
      actions={
        <Button 
          onClick={handleUpload} 
          disabled={!file || isLoading}
          icon={Upload}
        >
          {isLoading ? 'Uploading...' : 'Upload Asset'}
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="space-y-2">
          <input 
            type="file" 
            onChange={(e) => {
              setFile(e.target.files?.[0] || null)
              setUploadSuccess(false)
              setResult(null)
            }}
            className="text-xs file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-[10px] file:font-semibold file:bg-accent/10 file:text-accent-dark hover:file:bg-accent/20 transition-all cursor-pointer"
          />
          {file && (
            <p className="text-[10px] text-muted-foreground italic px-1">
              Selected: <span className="font-bold text-foreground">{file.name}</span>
            </p>
          )}
        </div>

        {isLoading && (
           <div className="flex items-center gap-2 p-3 bg-muted/30 rounded-lg">
             <Loader2 className="animate-spin text-accent-dark" size={16} />
             <span className="text-xs text-muted-foreground">Uploading to Google Cloud Storage...</span>
           </div>
        )}

        {uploadSuccess && result && (
          <div className="p-4 bg-green-500/10 border border-green-500/20 rounded-lg space-y-3">
            <div className="flex items-center gap-2 text-green-600 dark:text-green-400 font-bold text-xs">
              <Sparkles size={14} /> Upload Successful!
            </div>
            
            <div className="space-y-1">
              <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-bold">GCS URI</p>
              <p className="text-[10px] font-mono break-all bg-background/50 p-1.5 rounded border border-border/50 select-all">
                {result.gcs_uri}
              </p>
            </div>

            <div className="pt-2">
              <a 
                href={result.signed_url} 
                target="_blank" 
                rel="noreferrer"
                className="inline-flex items-center gap-2 px-4 py-2 bg-accent text-accent-foreground text-xs font-bold rounded-md hover:bg-accent/90 transition-colors"
              >
                <ExternalLink size={14} /> Download / View File
              </a>
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

const PromptOptimizationTest = () => {
  const [concept, setConcept] = useState('A futuristic car driving through a neon city.')
  const [result, setResult] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleTest = async () => {
    setIsLoading(true)
    try {
      const data = await api.diagnostics.optimizePrompt({ concept, length: '16', orientation: '16:9' })
      setResult(data)
    } catch (err) {
      console.error(err)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card 
      title="Gemini 3 Pro: Script Analysis" 
      icon={Sparkles}
      actions={
        <Button onClick={handleTest} disabled={isLoading} icon={Sparkles}>
          {isLoading ? 'Analyzing...' : 'Optimize Script'}
        </Button>
      }
    >
      <div className="space-y-4">
        <textarea 
          value={concept}
          onChange={(e) => setConcept(e.target.value)}
          className="w-full h-24 p-3 rounded-lg bg-muted/30 border border-border text-xs outline-none focus:ring-2 focus:ring-accent/30 transition-all"
        />
        {result && (
          <div className="space-y-3">
            <div className="p-3 bg-muted/50 border border-border rounded-lg max-h-40 overflow-auto">
              <pre className="text-[9px] font-mono">{JSON.stringify(result.data, null, 2)}</pre>
            </div>
            <UsageBadge usage={result.usage} />
          </div>
        )}
      </div>
    </Card>
  )
}

const ImageGenerationTest = () => {
  const [prompt, setPrompt] = useState('Cinematic wide shot of Tokyo at night, neon lights.')
  const [result, setResult] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleTest = async () => {
    setIsLoading(true)
    try {
      const data = await api.diagnostics.generateImage({ prompt, orientation: '16:9' })
      setResult(data)
    } catch (err) {
      console.error(err)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card 
      title="Imagen 3: Storyboard Frame" 
      icon={ImageIcon}
      actions={
        <Button onClick={handleTest} disabled={isLoading} icon={ImageIcon}>
          {isLoading ? 'Painting...' : 'Generate Frame'}
        </Button>
      }
    >
      <div className="space-y-4">
        <textarea 
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          className="w-full h-20 p-3 rounded-lg bg-muted/30 border border-border text-xs outline-none focus:ring-2 focus:ring-accent/30 transition-all"
        />
        {result && (
          <div className="space-y-3">
            <div className="aspect-video rounded-lg overflow-hidden border border-border">
              <img src={result.data} className="w-full h-full object-cover" alt="Generated" />
            </div>
            <UsageBadge usage={result.usage} />
          </div>
        )}
      </div>
    </Card>
  )
}

const VideoGenerationTest = () => {
  const [prompt, setPrompt] = useState('A slow tracking shot of coffee being poured.')
  const [result, setResult] = useState<any>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [status, setStatus] = useState<string>('idle')

  const pollStatus = async (operationName: string) => {
    const interval = setInterval(async () => {
      try {
        // Encoding the operation name is crucial as it contains slashes
        const encodedName = encodeURIComponent(operationName)
        const response = await fetch(`/api/v1/diagnostics/operations/${operationName}`)
        const data = await response.json()
        
        if (data.status === 'completed') {
          setResult({ video_uri: data.video_uri, signed_url: data.signed_url })
          setStatus('completed')
          setIsLoading(false)
          clearInterval(interval)
        } else if (data.status === 'failed' || data.status === 'error') {
          console.error(data.error || data.message)
          setStatus('failed')
          setIsLoading(false)
          clearInterval(interval)
        }
        // If processing, continue polling
      } catch (err) {
        console.error("Polling error", err)
        // Don't stop polling on transient network errors
      }
    }, 5000) // Poll every 5 seconds
  }

  const handleTest = async () => {
    setIsLoading(true)
    setStatus('starting')
    setResult(null)
    try {
      const data = await api.diagnostics.generateVideo({ prompt })
      
      if (data.operation_name) {
        setStatus('processing')
        pollStatus(data.operation_name)
      } else if (data.video_uri) {
        // Immediate return (unlikely for video but good fallback)
        setResult(data)
        setStatus('completed')
        setIsLoading(false)
      }
    } catch (err) {
      console.error(err)
      setStatus('failed')
      setIsLoading(false)
    }
  }

  return (
    <Card 
      title="Veo 3.1: Video Scene (8s)" 
      icon={Video}
      actions={
        <Button onClick={handleTest} disabled={isLoading} icon={Video}>
          {isLoading ? 'Processing...' : 'Render Scene'}
        </Button>
      }
    >
      <div className="space-y-4">
        <textarea 
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          className="w-full h-20 p-3 rounded-lg bg-muted/30 border border-border text-xs outline-none focus:ring-2 focus:ring-accent/30 transition-all"
        />
        
        {status === 'processing' && (
          <div className="flex items-center gap-2 p-3 bg-muted/30 rounded-lg">
            <Loader2 className="animate-spin text-accent-dark" size={16} />
            <span className="text-xs text-muted-foreground">Generating video... this may take a minute.</span>
          </div>
        )}

        {result && status === 'completed' && (
          <div className="p-3 bg-accent/5 border border-accent/20 rounded-lg">
            {result.signed_url && (
              <video 
                src={result.signed_url} 
                controls 
                className="w-full rounded-lg mb-2 shadow-sm aspect-video bg-black"
              />
            )}
            <p className="text-[10px] font-mono break-all mb-2 opacity-70">{result.video_uri}</p>
            <a 
              href={result.signed_url} 
              target="_blank" 
              rel="noreferrer"
              className="text-accent-dark text-[10px] font-bold flex items-center gap-1 hover:underline"
            >
              Download Scene <ExternalLink size={10} />
            </a>
          </div>
        )}

        {status === 'failed' && (
           <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-500">
             Video generation failed. Check console/logs.
           </div>
        )}
      </div>
    </Card>
  )
}

const UsageBadge = ({ usage }: { usage: any }) => (
  <div className="flex items-center gap-4 p-2 px-3 bg-muted rounded-full w-fit border border-border">
    <div className="flex items-center gap-1.5 text-[9px] font-bold text-muted-foreground uppercase tracking-widest">
      <Cpu size={10} /> {usage.model_name}
    </div>
    <div className="w-px h-3 bg-border" />
    <div className="flex items-center gap-1 text-[10px] font-mono font-bold text-accent-dark">
      <DollarSign size={10} /> {usage.cost_usd.toFixed(4)}
    </div>
  </div>
)
