import type { Metadata } from 'next'
import '@/index.css'

export const metadata: Metadata = {
  title: 'VeoGen | AI Video Generation & Creative Studio',
  description:
    'Enterprise AI Video Production, Smart Reframing, Promos, Multi-Ratio Adapts, and Live Dubbing powered by Google Veo & Gemini.',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" className="dark" suppressHydrationWarning>
      <body className="bg-background text-foreground antialiased selection:bg-accent/20 selection:text-accent">
        {children}
      </body>
    </html>
  )
}
