import { AnimatePresence, motion } from 'framer-motion'
import { useAgentStore } from '@/store/agentStore'
import { LandingPage } from '@/components/layout/LandingPage'
import { AppShell } from '@/components/layout/AppShell'

export default function App() {
  const { page } = useAgentStore()

  return (
    <div className="w-screen h-screen overflow-hidden bg-bg">
      <AnimatePresence mode="wait">
        {page === 'landing' ? (
          <motion.div key="landing" className="w-full h-full overflow-y-auto">
            <LandingPage />
          </motion.div>
        ) : (
          <motion.div key="app" className="w-full h-full">
            <AppShell />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
