# Kiln — Embodied Carbon Intelligence

A frontend for the Conceptual Carbon Calculator API — every workstream (00–13) covered:
tiered Phase 1 project intake + calculate/substitute/refine, Phase 2 BOQ & Work Order
carbon calculators (with a substitution catalog), company onboarding review, a
versioned emission-factor explorer, and Phase 3 tracking (baseline recording, bill
uploads, a running-carbon-vs-baseline dashboard, and a natural-language what-if chat).

## Setup

This folder is meant to sit next to your `backend` folder:

```
project/
  backend/
  frontend/   <- this
```

1. Install dependencies:

   ```bash
   cd frontend
   npm install
   ```

2. Configure the API base URL:

   ```bash
   cp .env.example .env.local
   ```

   `.env.local` sets `VITE_API_BASE_URL`. It defaults to `http://localhost:8000` if you
   leave it unset, which matches a locally-running backend started the usual way (e.g.
   `uvicorn app.main:app --port 8000`).

3. Run the dev server:

   ```bash
   npm run dev
   ```

   Opens on `http://localhost:5173`.

### CORS note

The backend's `app/main.py` already allow-lists `http://localhost:5173` in its
`CORSMiddleware` config, so local dev works out of the box. If you ever serve this
frontend from a different origin (a different port, a domain, or a future desktop-
wrapper build), add that origin to the backend's CORS allow-list too.

## Company scoping

The API scopes everything by `company_id`, but there's no discovery/listing endpoint
for it, so it's a free-text field in the top bar (defaults to `provident`, persisted
to `localStorage`). Change it there to switch companies.

## Build

```bash
npm run build
```

Type-checks with `tsc -b` then builds a production bundle with Vite into `dist/`.

## Stack

Vite + React 19 + TypeScript, Tailwind CSS v4, react-router-dom, TanStack Query,
axios, framer-motion, recharts, lucide-react.

## Design

Dark, neumorphic, coral-accented "fintech-for-construction" aesthetic — reinterpreted
from a textual description of the Paymark landing-page template (the page itself
couldn't be fetched with pixel-level detail, only a design-token summary: dark theme,
coral accent, neumorphic pill buttons, tight-tracking display type). If you have
reference screenshots of the original template, share them and the visual details
(spacing, exact colors, component shapes) can be tightened to match more closely.
