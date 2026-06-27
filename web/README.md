# Aristotle Web

Vite + React + TypeScript + Tailwind frontend for Aristotle.

The browser talks only to the Aristotle Agent API.

## Local Run

```sh
npm install
npm run dev
```

## Environment

```text
VITE_AGENT_HTTP_BASE_URL=https://bukunmi2108-aristotle-api.hf.space
VITE_AGENT_WS_BASE_URL=wss://bukunmi2108-aristotle-api.hf.space
```

## Deploy

Use Vercel with:

```text
Root Directory: web
Build Command: npm run build
Output Directory: dist
```
