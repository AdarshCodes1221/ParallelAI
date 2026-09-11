import { useEffect } from 'react'
import { AnimatePresence, motion } from 'framer-motion'
import { Cpu, Loader2 } from 'lucide-react'
import { useAgentStore } from '@/store/agentStore'
import { LandingPage } from '@/components/layout/LandingPage'
import { AppShell } from '@/components/layout/AppShell'
import { AuthModal } from '@/components/auth/AuthModal'

export default function App() {
  const { page, authStatus, checkAuth, setAuthMode, setAuthModalOpen } = useAgentStore()

  useEffect(() => {
    // 1. Restore authenticated session from HttpOnly cookie
    checkAuth()

    // 2. Handle URL parameters and deep links (e.g. password reset emails)
    try {
      const url = new URL(window.location.href)
      const token = url.searchParams.get('token')
      const pathname = window.location.pathname.toLowerCase()

      if (token || pathname === '/reset-password') {
        setAuthMode('reset')
        setAuthModalOpen(true)
      } else if (pathname === '/login') {
        setAuthMode('login')
        setAuthModalOpen(true)
      } else if (pathname === '/signup') {
        setAuthMode('signup')
        setAuthModalOpen(true)
      } else if (pathname === '/forgot-password') {
        setAuthMode('forgot')
        setAuthModalOpen(true)
      }
    } catch {
      // Ignore URL parsing errors on restricted environments
    }
  }, [checkAuth, setAuthMode, setAuthModalOpen])

  // Flicker prevention: render sleek loading state while verifying initial session
  if (authStatus === 'loading') {
    return (
      <div className="w-screen h-screen flex flex-col items-center justify-center bg-slate-950 text-slate-100 overflow-hidden relative selection:bg-cyan-500 selection:text-black">
        <div className="absolute w-72 h-72 bg-cyan-500/10 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute w-72 h-72 bg-purple-600/10 rounded-full blur-3xl pointer-events-none" />
        
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 0.3 }}
          className="flex flex-col items-center gap-4 z-10"
        >
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-cyan-500 to-purple-600 flex items-center justify-center shadow-xl shadow-cyan-500/20">
            <Cpu className="w-6 h-6 text-slate-950" />
          </div>
          <div className="text-center">
            <h1 className="font-display font-bold text-lg tracking-wide bg-gradient-to-r from-cyan-400 to-purple-400 bg-clip-text text-transparent">
              Parallel AI
            </h1>
            <p className="text-xs text-slate-500 font-mono mt-0.5">Initializing Secure Session</p>
          </div>
          <Loader2 className="w-4 h-4 animate-spin text-cyan-400 mt-2" />
        </motion.div>
      </div>
    )
  }

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
      <AuthModal />
    </div>
  )
}
