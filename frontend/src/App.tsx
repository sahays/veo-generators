import { Navbar, Sidebar } from './components/Layout'
import { Card, Button } from './components/Common'
import { Plus, Video, Sparkles } from 'lucide-react'

function App() {
  return (
    <div className="flex h-screen bg-background">
      <Sidebar />
      <div className="flex-1 flex flex-col overflow-hidden">
        <Navbar />
        <main className="flex-1 overflow-x-hidden overflow-y-auto p-6 md:p-8">
          <div className="max-w-4xl mx-auto space-y-8">
            
            {/* Header Section */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-1">
                <h2 className="text-2xl font-heading text-foreground tracking-tight">Welcome back</h2>
                <p className="text-sm text-muted-foreground">Select a tool from the sidebar to start creating.</p>
              </div>
            </div>

            {/* Main Feature Area */}
            <Card 
              title="Ready to Generate?" 
              icon={Sparkles}
              actions={
                <Button icon={Plus}>Start New Generation</Button>
              }
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

            {/* Secondary Grid Example */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <Card title="Documentation" icon={Sparkles}>
                <p className="text-sm">Learn how to master the cinematic prompts for the best results.</p>
              </Card>
              <Card title="Quick Setup" icon={Sparkles}>
                <p className="text-sm">Configure your default camera angles and director styles.</p>
              </Card>
            </div>

          </div>
        </main>
      </div>
    </div>
  )
}

export default App
