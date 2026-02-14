import { Card, Button } from '@/components/Common'
import { Plus, Video, Sparkles } from 'lucide-react'
import { motion } from 'framer-motion'

export const DashboardPage = () => {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.25 }}
      className="max-w-4xl mx-auto space-y-8"
    >
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1">
          <h2 className="text-2xl font-heading text-foreground tracking-tight">Welcome back</h2>
          <p className="text-sm text-muted-foreground">Select a tool from the sidebar to start creating.</p>
        </div>
      </div>

      <Card
        title="Ready to Generate?"
        icon={Sparkles}
        actions={<Button icon={Plus}>Start New Generation</Button>}
      >
        <div className="py-10 flex flex-col items-center justify-center text-center space-y-6">
          <div className="w-16 h-16 bg-accent/20 text-accent-dark rounded-full flex items-center justify-center shadow-inner">
            <Video size={32} />
          </div>
          <div className="space-y-2">
            <h4 className="text-lg font-bold font-heading text-foreground">No active projects</h4>
            <p className="text-sm text-muted-foreground max-w-sm mx-auto">
              Transform your video content with AI-powered ads, highlights, and thumbnails.
            </p>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card title="Documentation" icon={Sparkles}>
          <p className="text-sm">Learn how to master the cinematic prompts for the best results.</p>
        </Card>
        <Card title="Quick Setup" icon={Sparkles}>
          <p className="text-sm">Configure your default camera angles and director styles.</p>
        </Card>
      </div>
    </motion.div>
  )
}
