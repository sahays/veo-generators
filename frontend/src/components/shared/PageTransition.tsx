import { motion } from 'framer-motion'
import { useLocation } from 'react-router-dom'

export const PageTransition = ({ children }: { children: React.ReactNode }) => {
  const location = useLocation()

  return (
    <>
      {/* Fixed YouTube-style top page navigation progress bar */}
      <div className="fixed top-0 left-0 right-0 z-[100] h-[3px] pointer-events-none overflow-hidden">
        <motion.div
          key={`yt-progress-${location.pathname}`}
          initial={{ width: '0%', opacity: 1 }}
          animate={{ width: ['0%', '72%', '100%'], opacity: [1, 1, 0] }}
          transition={{
            width: { duration: 0.48, times: [0, 0.45, 1], ease: [0.16, 1, 0.3, 1] },
            opacity: { duration: 0.65, times: [0, 0.72, 1], ease: 'easeOut' },
          }}
          className="h-full bg-gradient-to-r from-orange-700 via-orange-500 to-amber-400 shadow-[0_0_12px_rgba(249,115,22,0.85)]"
        />
      </div>

      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
        className="w-full"
      >
        {children}
      </motion.div>
    </>
  )
}
