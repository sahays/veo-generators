import { motion, AnimatePresence } from 'framer-motion'
import { useProjectStore } from '@/store/useProjectStore'
import { ProjectList } from '@/components/ads/ProjectList'
import { ProjectForm } from '@/components/ads/ProjectForm'

export const AdsGenerationPage = () => {
  const view = useProjectStore((s) => s.view)

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -12 }}
      transition={{ duration: 0.25 }}
      className="max-w-5xl mx-auto"
    >
      <AnimatePresence mode="wait">
        {view === 'list' ? (
          <motion.div
            key="list"
            initial={{ opacity: 0, x: -20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -20 }}
            transition={{ duration: 0.2 }}
          >
            <ProjectList />
          </motion.div>
        ) : (
          <motion.div
            key="form"
            initial={{ opacity: 0, x: 20 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: 20 }}
            transition={{ duration: 0.2 }}
          >
            <ProjectForm />
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
