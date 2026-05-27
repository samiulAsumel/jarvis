#!/usr/bin/env bash
# Vercel build script — injects API keys from environment variables into index.html
# Set these in Vercel Dashboard → Project → Settings → Environment Variables:
#   JARVIS_GROQ_KEY   = gsk_...
#   JARVIS_OR_KEY     = sk-or-v1-...

set -e

mkdir -p dist
cp -r web/* dist/

# Inject keys if env vars are set (placeholders → actual values)
GROQ="${JARVIS_GROQ_KEY:-}"
OR="${JARVIS_OR_KEY:-}"

if [ -n "$GROQ" ]; then
  sed -i "s|const _DEFAULT_GROQ_KEY = '';   // gsk_\.\.\.|const _DEFAULT_GROQ_KEY = '${GROQ}';|g" dist/index.html
  echo "✅ Groq key injected"
else
  echo "ℹ️  No JARVIS_GROQ_KEY set — users will enter via Settings"
fi

if [ -n "$OR" ]; then
  sed -i "s|const _DEFAULT_OR_KEY   = '';   // sk-or-v1-\.\.\.|const _DEFAULT_OR_KEY   = '${OR}';|g" dist/index.html
  echo "✅ OpenRouter key injected"
else
  echo "ℹ️  No JARVIS_OR_KEY set — users will enter via Settings"
fi

echo "✅ Build complete → dist/"
