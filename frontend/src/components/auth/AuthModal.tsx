import React, { useState, useEffect, useRef } from 'react'
import {
  LogIn,
  UserPlus,
  Eye,
  EyeOff,
  ArrowRight,
  X,
  AlertCircle,
  CheckCircle2,
  Loader2,
  ShieldCheck,
  MailCheck,
} from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'

// ── Lightweight AI Neural Orb Canvas for Auth Modal ──
const AuthNeuralOrb: React.FC = () => {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    // Check prefers-reduced-motion
    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (mediaQuery.matches) {
      // Draw static glowing sphere
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      const grad = ctx.createRadialGradient(40, 40, 2, 40, 40, 36)
      grad.addColorStop(0, 'rgba(6, 182, 212, 0.8)')
      grad.addColorStop(0.6, 'rgba(147, 51, 234, 0.4)')
      grad.addColorStop(1, 'transparent')
      ctx.fillStyle = grad
      ctx.beginPath()
      ctx.arc(40, 40, 32, 0, Math.PI * 2)
      ctx.fill()
      return
    }

    let animId: number
    let angle = 0

    const nodes = Array.from({ length: 18 }, (_, i) => ({
      theta: (i / 18) * Math.PI * 2,
      phi: Math.acos((2 * (i + 0.5)) / 18 - 1),
      radius: 28,
      speed: 0.02 + (i % 3) * 0.005,
    }))

    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      const cx = canvas.width / 2
      const cy = canvas.height / 2
      angle += 0.02

      // Central core glow
      const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, 32)
      coreGrad.addColorStop(0, 'rgba(6, 182, 212, 0.35)')
      coreGrad.addColorStop(0.5, 'rgba(168, 85, 247, 0.18)')
      coreGrad.addColorStop(1, 'transparent')
      ctx.fillStyle = coreGrad
      ctx.beginPath()
      ctx.arc(cx, cy, 32, 0, Math.PI * 2)
      ctx.fill()

      // Rotating nodes & connecting arcs
      const projectedNodes: { x: number; y: number; z: number }[] = []

      nodes.forEach((node) => {
        const curTheta = node.theta + angle * node.speed * 20
        const x = node.radius * Math.sin(node.phi) * Math.cos(curTheta)
        const y = node.radius * Math.cos(node.phi)
        const z = node.radius * Math.sin(node.phi) * Math.sin(curTheta)

        // 3D perspective projection
        const scale = 1 + z / 80
        const px = cx + x * scale
        const py = cy + y * scale
        projectedNodes.push({ x: px, y: py, z })
      })

      // Connections between nearby nodes
      ctx.strokeStyle = 'rgba(6, 182, 212, 0.25)'
      ctx.lineWidth = 0.8
      for (let i = 0; i < projectedNodes.length; i++) {
        for (let j = i + 1; j < projectedNodes.length; j++) {
          const dx = projectedNodes[i].x - projectedNodes[j].x
          const dy = projectedNodes[i].y - projectedNodes[j].y
          const dist = Math.sqrt(dx * dx + dy * dy)
          if (dist < 22) {
            ctx.beginPath()
            ctx.moveTo(projectedNodes[i].x, projectedNodes[i].y)
            ctx.lineTo(projectedNodes[j].x, projectedNodes[j].y)
            ctx.stroke()
          }
        }
      }

      // Draw node particles
      projectedNodes.forEach((pt) => {
        const alpha = Math.max(0.2, (pt.z + 28) / 56)
        ctx.fillStyle = pt.z > 0 ? `rgba(34, 211, 238, ${alpha})` : `rgba(192, 132, 252, ${alpha * 0.7})`
        ctx.beginPath()
        ctx.arc(pt.x, pt.y, pt.z > 0 ? 1.8 : 1.2, 0, Math.PI * 2)
        ctx.fill()
      })

      animId = requestAnimationFrame(render)
    }

    render()
    return () => cancelAnimationFrame(animId)
  }, [])

  return (
    <canvas
      ref={canvasRef}
      width={80}
      height={80}
      className="w-20 h-20 pointer-events-none drop-shadow-[0_0_15px_rgba(6,182,212,0.4)]"
      aria-hidden="true"
    />
  )
}

// ── Password Strength Evaluation ──
interface PasswordCriteria {
  minLen: boolean
  hasLetter: boolean
  hasNumber: boolean
  hasSpecial: boolean
}

function evaluatePassword(pwd: string): { score: number; label: string; color: string; criteria: PasswordCriteria } {
  const criteria = {
    minLen: pwd.length >= 8,
    hasLetter: /[A-Za-z]/.test(pwd),
    hasNumber: /\d/.test(pwd),
    hasSpecial: /[^A-Za-z0-9]/.test(pwd),
  }

  let score = 0
  if (pwd.length >= 8) score++
  if (pwd.length >= 12) score++
  if (criteria.hasLetter && (criteria.hasNumber || criteria.hasSpecial)) score++
  if (criteria.hasNumber && criteria.hasSpecial && criteria.hasLetter) score++

  if (!pwd) return { score: 0, label: '', color: 'bg-slate-700', criteria }
  if (score <= 1) return { score: 1, label: 'Weak', color: 'bg-red-500', criteria }
  if (score === 2) return { score: 2, label: 'Fair', color: 'bg-amber-500', criteria }
  if (score === 3) return { score: 3, label: 'Good', color: 'bg-emerald-400', criteria }
  return { score: 4, label: 'Godlevel Strong', color: 'bg-cyan-400', criteria }
}

const getUrlToken = (): string => {
  if (typeof window === 'undefined') return ''
  try {
    const url = new URL(window.location.href)
    return url.searchParams.get('token') || ''
  } catch {
    return ''
  }
}

export const AuthModal: React.FC = () => {
  const {
    authModalOpen,
    authMode,
    setAuthModalOpen,
    setAuthMode,
    login,
    signup,
    forgotPassword,
    resetPassword,
    changePassword,
  } = useAgentStore()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [name, setName] = useState('')
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')

  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [capsLockActive, setCapsLockActive] = useState(false)

  const isSubmittingRef = useRef(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)

  // Detect Caps Lock
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.getModifierState && typeof e.getModifierState === 'function') {
      setCapsLockActive(e.getModifierState('CapsLock'))
    }
  }

  const handleKeyUp = (e: React.KeyboardEvent) => {
    if (e.getModifierState && typeof e.getModifierState === 'function') {
      setCapsLockActive(e.getModifierState('CapsLock'))
    }
  }

  const preserveSuccessRef = useRef(false)

  // Clean form fields and feedback whenever auth mode changes
  useEffect(() => {
    const timer = setTimeout(() => {
      setPassword('')
      setConfirmPassword('')
      setNewPassword('')
      setCurrentPassword('')
      setError(null)
      if (preserveSuccessRef.current) {
        preserveSuccessRef.current = false
      } else {
        setSuccessMessage(null)
      }
      setShowPassword(false)
      setShowConfirmPassword(false)
      if (authMode === 'reset' || authMode === 'change_password') {
        setEmail('')
        setName('')
      }
    }, 0)
    return () => clearTimeout(timer)
  }, [authMode])

  if (!authModalOpen) return null

  const handleClose = () => {
    setError(null)
    setSuccessMessage(null)
    setPassword('')
    setConfirmPassword('')
    setNewPassword('')
    setCurrentPassword('')
    setEmail('')
    setName('')
    isSubmittingRef.current = false
    setLoading(false)
    setAuthModalOpen(false)
  }

  const activePasswordForStrength = authMode === 'signup' ? password : authMode === 'reset' || authMode === 'change_password' ? newPassword : ''
  const strength = evaluatePassword(activePasswordForStrength)
  const urlToken = getUrlToken()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (isSubmittingRef.current || loading) return
    isSubmittingRef.current = true
    setLoading(true)
    setError(null)
    setSuccessMessage(null)

    try {
      if (authMode === 'login') {
        if (!email.trim() || !password) {
          setError('Please enter your email and password.')
          return
        }
        await login(email.trim(), password)
        handleClose()
      } else if (authMode === 'signup') {
        if (!email.trim() || !password) {
          setError('Please enter your email and password.')
          return
        }
        if (password.length < 8) {
          setError('Password must be at least 8 characters long.')
          return
        }
        if (!confirmPassword) {
          setError('Please confirm your password.')
          return
        }
        if (password !== confirmPassword) {
          setError('Passwords do not match.')
          return
        }
        const res = await signup(email.trim(), password, name.trim() || undefined)
        preserveSuccessRef.current = true
        setPassword('')
        setConfirmPassword('')
        setSuccessMessage(res?.message || 'Account created successfully. Please sign in.')
        setAuthMode('login')
        return
      } else if (authMode === 'forgot') {
        if (!email.trim()) {
          setError('Please enter your account email.')
          return
        }
        await forgotPassword(email.trim())
        setSuccessMessage("If an account with that email exists, we've sent a password reset link.")
        setEmail('')
      } else if (authMode === 'reset') {
        if (!urlToken) {
          setError('That password reset link is invalid or has expired. Please request a new one.')
          return
        }
        if (!newPassword) {
          setError('Please enter your new password.')
          return
        }
        if (newPassword.length < 8) {
          setError('Password must be at least 8 characters long.')
          return
        }
        if (!confirmPassword) {
          setError('Please confirm your new password.')
          return
        }
        if (newPassword !== confirmPassword) {
          setError('Passwords do not match.')
          return
        }
        try {
          await resetPassword(urlToken, newPassword)
        } catch {
          setError('That password reset link is invalid or has expired. Please request a new one.')
          return
        }
        
        // Clean URL to remove raw token from history/address bar
        try {
          const cleanUrl = window.location.origin + window.location.pathname.replace(/\/reset-password\/?$/, '/')
          window.history.replaceState({}, document.title, cleanUrl)
        } catch {
          // ignore
        }

        preserveSuccessRef.current = true
        setPassword('')
        setNewPassword('')
        setConfirmPassword('')
        setSuccessMessage('Password reset successfully! Please sign in with your new password.')
        setAuthMode('login')
        return
      } else if (authMode === 'change_password') {
        if (!currentPassword || !newPassword) {
          setError('Please enter both your current and new password.')
          return
        }
        if (confirmPassword && newPassword !== confirmPassword) {
          setError('Passwords do not match.')
          return
        }
        await changePassword(currentPassword, newPassword)
        setSuccessMessage('Password successfully updated.')
        setTimeout(() => handleClose(), 1500)
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Authentication error. Please try again.')
    } finally {
      isSubmittingRef.current = false
      setLoading(false)
    }
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="auth-modal-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/80 backdrop-blur-md animate-in fade-in duration-200"
    >
      <div className="relative w-full max-w-md bg-slate-950/95 border border-cyan-500/30 rounded-2xl shadow-2xl shadow-cyan-950/60 p-6 sm:p-8 overflow-hidden text-slate-100">
        {/* Glow ambient background highlights */}
        <div className="absolute -top-24 -right-24 w-52 h-52 bg-cyan-500/15 rounded-full blur-3xl pointer-events-none" />
        <div className="absolute -bottom-24 -left-24 w-52 h-52 bg-purple-600/15 rounded-full blur-3xl pointer-events-none" />

        {/* Close button */}
        <button
          onClick={handleClose}
          className="absolute top-4 right-4 p-2 text-slate-400 hover:text-white hover:bg-slate-800/60 rounded-xl transition focus:outline-none focus:ring-2 focus:ring-cyan-500"
          aria-label="Close modal"
        >
          <X className="w-5 h-5" />
        </button>

        {/* Header with animated AI core orb */}
        <div className="flex flex-col items-center text-center mb-6">
          <div className="mb-2">
            <AuthNeuralOrb />
          </div>
          <h2
            id="auth-modal-title"
            className="text-2xl font-bold tracking-tight bg-gradient-to-r from-cyan-400 via-blue-400 to-purple-400 bg-clip-text text-transparent"
          >
            {authMode === 'login' && 'Welcome Back'}
            {authMode === 'signup' && 'Create Account'}
            {authMode === 'forgot' && 'Forgot Password'}
            {authMode === 'reset' && 'Set New Password'}
            {authMode === 'change_password' && 'Change Password'}
          </h2>
          <p className="text-xs sm:text-sm text-slate-400 mt-1 max-w-xs">
            {authMode === 'login' && 'Sign in to access your secure multimodal workspace'}
            {authMode === 'signup' && 'Argon2id secured private sessions and persistent RAG'}
            {authMode === 'forgot' && 'Enter the email address associated with your account.'}
            {authMode === 'reset' && 'Enter your new secure password'}
            {authMode === 'change_password' && 'Update your account credentials'}
          </p>
        </div>

        {/* Mode switcher tabs */}
        {(authMode === 'login' || authMode === 'signup') && (
          <div className="flex rounded-xl bg-slate-900/80 p-1 mb-5 border border-slate-800" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={authMode === 'login'}
              onClick={() => {
                setAuthMode('login')
                setError(null)
                setSuccessMessage(null)
              }}
              className={`flex-1 py-2 text-xs font-semibold rounded-lg transition flex items-center justify-center gap-1.5 ${
                authMode === 'login'
                  ? 'bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/25'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <LogIn className="w-3.5 h-3.5" />
              <span>Sign In</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={authMode === 'signup'}
              onClick={() => {
                setAuthMode('signup')
                setError(null)
                setSuccessMessage(null)
              }}
              className={`flex-1 py-2 text-xs font-semibold rounded-lg transition flex items-center justify-center gap-1.5 ${
                authMode === 'signup'
                  ? 'bg-cyan-500 text-slate-950 shadow-md shadow-cyan-500/25'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <UserPlus className="w-3.5 h-3.5" />
              <span>Sign Up</span>
            </button>
          </div>
        )}

        {/* Error / Success Feedback Banners */}
        {error && (
          <div
            role="alert"
            aria-live="polite"
            className="flex items-start gap-2.5 p-3 mb-4 rounded-xl bg-red-950/50 border border-red-500/40 text-red-300 text-xs"
          >
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-red-400" />
            <span className="font-medium">{error}</span>
          </div>
        )}
        {successMessage && (
          <div
            role="status"
            aria-live="polite"
            className="flex items-start gap-2.5 p-3 mb-4 rounded-xl bg-emerald-950/50 border border-emerald-500/40 text-emerald-300 text-xs"
          >
            {authMode === 'forgot' ? (
              <MailCheck className="w-4 h-4 mt-0.5 shrink-0 text-emerald-400" />
            ) : (
              <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0 text-emerald-400" />
            )}
            <span className="font-medium">{successMessage}</span>
          </div>
        )}

        {/* Token missing warning for reset mode */}
        {authMode === 'reset' && !urlToken && !error && (
          <div className="flex items-start gap-2.5 p-3 mb-4 rounded-xl bg-amber-950/50 border border-amber-500/40 text-amber-300 text-xs">
            <AlertCircle className="w-4 h-4 mt-0.5 shrink-0 text-amber-400" />
            <span>That password reset link is invalid or has expired. Please request a new one.</span>
          </div>
        )}

        {/* Caps Lock Indicator */}
        {capsLockActive && (
          <div className="flex items-center gap-2 px-3 py-1.5 mb-3 rounded-lg bg-amber-950/50 border border-amber-500/30 text-amber-300 text-[11px]">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            <span>Caps Lock is ON</span>
          </div>
        )}

        {/* Auth Form */}
        <form onSubmit={handleSubmit} onKeyDown={handleKeyDown} onKeyUp={handleKeyUp} className="space-y-4">
          {authMode === 'signup' && (
            <div>
              <label htmlFor="auth-name" className="block text-xs font-medium text-slate-300 mb-1">
                Full Name (Optional)
              </label>
              <input
                id="auth-name"
                type="text"
                autoComplete="name"
                placeholder="Ada Lovelace"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-slate-900/90 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition"
              />
            </div>
          )}

          {(authMode === 'login' || authMode === 'signup' || authMode === 'forgot') && (
            <div>
              <label htmlFor="auth-email" className="block text-xs font-medium text-slate-300 mb-1">
                Email Address
              </label>
              <input
                id="auth-email"
                type="email"
                required
                autoComplete="email"
                placeholder="name@example.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-3.5 py-2.5 bg-slate-900/90 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition"
              />
            </div>
          )}

          {authMode === 'change_password' && (
            <div>
              <label htmlFor="auth-curr-pwd" className="block text-xs font-medium text-slate-300 mb-1">
                Current Password
              </label>
              <div className="relative">
                <input
                  id="auth-curr-pwd"
                  type={showPassword ? 'text' : 'password'}
                  required
                  autoComplete="current-password"
                  placeholder="••••••••"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  className="w-full px-3.5 py-2.5 pr-10 bg-slate-900/90 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
          )}

          {(authMode === 'login' || authMode === 'signup') && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <label htmlFor="auth-password" className="text-xs font-medium text-slate-300">
                  Password
                </label>
                {authMode === 'login' && (
                  <button
                    type="button"
                    onClick={() => {
                      setAuthMode('forgot')
                      setError(null)
                      setSuccessMessage(null)
                    }}
                    className="text-xs text-cyan-400 hover:text-cyan-300 transition"
                  >
                    Forgot Password?
                  </button>
                )}
              </div>
              <div className="relative">
                <input
                  id="auth-password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  autoComplete={authMode === 'login' ? 'current-password' : 'new-password'}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-3.5 py-2.5 pr-10 bg-slate-900/90 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
          )}

          {(authMode === 'reset' || authMode === 'change_password') && (
            <div>
              <label htmlFor="auth-new-password" className="block text-xs font-medium text-slate-300 mb-1">
                New Password
              </label>
              <div className="relative">
                <input
                  id="auth-new-password"
                  type={showPassword ? 'text' : 'password'}
                  required
                  autoComplete="new-password"
                  placeholder="••••••••"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  className="w-full px-3.5 py-2.5 pr-10 bg-slate-900/90 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
            </div>
          )}

          {/* Password Strength Indicator Widget for Signup, Reset, and Change Password */}
          {(authMode === 'signup' || authMode === 'reset' || authMode === 'change_password') &&
            activePasswordForStrength.length > 0 && (
              <div className="p-2.5 rounded-xl bg-slate-900/60 border border-slate-800/80 space-y-2 text-xs">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">Security Score:</span>
                  <span className="font-semibold text-slate-200">{strength.label}</span>
                </div>
                {/* 4-bar strength progress */}
                <div className="grid grid-cols-4 gap-1.5 h-1.5">
                  {[1, 2, 3, 4].map((step) => (
                    <div
                      key={step}
                      className={`h-full rounded-full transition-all duration-300 ${
                        step <= strength.score ? strength.color : 'bg-slate-800'
                      }`}
                    />
                  ))}
                </div>
                {/* Requirements checklist */}
                <div className="grid grid-cols-2 gap-1 text-[10px] text-slate-400 pt-1">
                  <div className={`flex items-center gap-1 ${strength.criteria.minLen ? 'text-emerald-400' : ''}`}>
                    <ShieldCheck className="w-3 h-3" />
                    <span>8+ characters</span>
                  </div>
                  <div className={`flex items-center gap-1 ${strength.criteria.hasLetter ? 'text-emerald-400' : ''}`}>
                    <ShieldCheck className="w-3 h-3" />
                    <span>Letters</span>
                  </div>
                  <div className={`flex items-center gap-1 ${strength.criteria.hasNumber ? 'text-emerald-400' : ''}`}>
                    <ShieldCheck className="w-3 h-3" />
                    <span>Numbers</span>
                  </div>
                  <div className={`flex items-center gap-1 ${strength.criteria.hasSpecial ? 'text-emerald-400' : ''}`}>
                    <ShieldCheck className="w-3 h-3" />
                    <span>Special symbol</span>
                  </div>
                </div>
              </div>
            )}

          {/* Password confirmation on Signup, Reset, and Change Password */}
          {(authMode === 'signup' || authMode === 'reset' || authMode === 'change_password') && (
            <div>
              <label htmlFor="auth-confirm-pwd" className="block text-xs font-medium text-slate-300 mb-1">
                Confirm Password
              </label>
              <div className="relative">
                <input
                  id="auth-confirm-pwd"
                  type={showConfirmPassword ? 'text' : 'password'}
                  required
                  autoComplete="new-password"
                  placeholder="••••••••"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  className="w-full px-3.5 py-2.5 pr-10 bg-slate-900/90 border border-slate-800 rounded-xl text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500 transition"
                />
                <button
                  type="button"
                  onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200"
                  aria-label={showConfirmPassword ? 'Hide confirmation password' : 'Show confirmation password'}
                >
                  {showConfirmPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                </button>
              </div>
              {confirmPassword && confirmPassword !== activePasswordForStrength && (
                <p className="text-[10px] text-red-400 mt-1">Passwords do not match yet</p>
              )}
            </div>
          )}

          {/* Submit Button */}
          <button
            type="submit"
            disabled={loading || (authMode === 'reset' && !urlToken)}
            className="w-full mt-2 py-3 px-4 rounded-xl bg-gradient-to-r from-cyan-500 via-blue-500 to-purple-600 hover:from-cyan-400 hover:to-purple-500 text-slate-950 font-bold text-sm shadow-lg shadow-cyan-500/25 transition transform active:scale-[0.99] flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin text-slate-950" />
                <span>Processing Secure Request...</span>
              </>
            ) : (
              <>
                <span>
                  {authMode === 'login' && 'Sign In to Workspace'}
                  {authMode === 'signup' && 'Create Secure Account'}
                  {authMode === 'forgot' && 'Send Reset Link'}
                  {authMode === 'reset' && 'Save New Password'}
                  {authMode === 'change_password' && 'Update Password'}
                </span>
                <ArrowRight className="w-4 h-4 text-slate-950" />
              </>
            )}
          </button>
        </form>

        {/* Footer switchers */}
        <div className="mt-5 text-center text-xs text-slate-400">
          {authMode === 'forgot' || authMode === 'reset' || authMode === 'change_password' ? (
            <button
              type="button"
              onClick={() => {
                setAuthMode('login')
                setError(null)
                setSuccessMessage(null)
              }}
              className="text-cyan-400 hover:text-cyan-300 underline font-medium"
            >
              Back to Sign In
            </button>
          ) : (
            <span>
              {authMode === 'login' ? "Don't have an account? " : 'Already registered? '}
              <button
                type="button"
                onClick={() => {
                  setAuthMode(authMode === 'login' ? 'signup' : 'login')
                  setError(null)
                  setSuccessMessage(null)
                }}
                className="text-cyan-400 hover:text-cyan-300 underline font-semibold ml-1"
              >
                {authMode === 'login' ? 'Sign up' : 'Sign in'}
              </button>
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
