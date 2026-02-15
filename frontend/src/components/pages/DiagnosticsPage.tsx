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

  const handleUpload = async () => {
    if (!file) return
    setIsLoading(true)
    try {
      const data = await api.assets.upload(file)
      setResult(data)
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
            onChange={(e) => setFile(e.target.files?.[0] || null)}
            className="text-xs file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-[10px] file:font-semibold file:bg-accent/10 file:text-accent-dark hover:file:bg-accent/20 transition-all cursor-pointer"
          />
          {file && (
            <p className="text-[10px] text-muted-foreground italic px-1">
              Selected: <span className="font-bold text-foreground">{file.name}</span>
            </p>
          )}
        </div>
        {result && (
          <div className="p-3 bg-accent/5 border border-accent/20 rounded-lg space-y-2">
            <p className="text-[10px] font-mono break-all">{result.gcs_uri}</p>
            <a 
              href={result.signed_url} 
              target="_blank" 
              className="text-accent-dark text-[10px] font-bold flex items-center gap-1"
            >
              View Uploaded Asset <ExternalLink size={10} />
            </a>
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

  const handleTest = async () => {
    setIsLoading(true)
    try {
      const data = await api.diagnostics.generateVideo({ prompt })
      setResult(data)
    } catch (err) {
      console.error(err)
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <Card 
      title="Veo 3.1: Video Scene (8s)" 
      icon={Video}
      actions={
        <Button onClick={handleTest} disabled={isLoading} icon={Video}>
          {isLoading ? 'Rendering...' : 'Render Scene'}
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
          <div className="p-3 bg-accent/5 border border-accent/20 rounded-lg">
            <p className="text-[10px] font-mono break-all mb-2">{result.video_uri}</p>
            <a 
              href={result.signed_url} 
              target="_blank" 
              className="text-accent-dark text-[10px] font-bold flex items-center gap-1"
            >
              Download Scene <ExternalLink size={10} />
            </a>
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
