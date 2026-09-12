import { createClient } from '@insforge/sdk'

/**
 * Reads a public env var without caring which bundler is in front of it, so the
 * app and the website can share this module even if they end up on different
 * frameworks. Checks the Next.js names the InsForge CLI wrote into .env.local
 * first, then the Vite / Astro / CRA equivalents, then a bare name for Node.
 */
function readEnv(suffix: 'URL' | 'ANON_KEY'): string | undefined {
  const names = [
    `NEXT_PUBLIC_INSFORGE_${suffix}`,
    `VITE_INSFORGE_${suffix}`,
    `PUBLIC_INSFORGE_${suffix}`,
    `REACT_APP_INSFORGE_${suffix}`,
    `INSFORGE_${suffix}`,
  ]

  // import.meta.env for Vite/Astro; process.env for Next.js and Node.
  const meta = (import.meta as ImportMeta & { env?: Record<string, string> }).env
  const proc = typeof process !== 'undefined' ? process.env : undefined

  for (const name of names) {
    const value = meta?.[name] ?? proc?.[name]
    if (value) return value
  }
  return undefined
}

const baseUrl = readEnv('URL')
const anonKey = readEnv('ANON_KEY')

if (!baseUrl || !anonKey) {
  throw new Error(
    'InsForge is not configured. Copy .env.example to .env.local and fill in ' +
      'the project URL and anon key (npx -y @insforge/cli secrets get ANON_KEY).',
  )
}

/**
 * The user-scoped client. Safe to ship to the browser: every table it can reach
 * is gated by row level security, and the answer keys for scenarios and quizzes
 * are not reachable through it at all.
 */
export const insforge = createClient({ baseUrl, anonKey })

export const INSFORGE_URL = baseUrl
