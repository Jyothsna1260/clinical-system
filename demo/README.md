# Automated demo

`record-demo.mjs` drives the real application in a browser, end to end, and records a narrated
walkthrough. A visible cursor, click ripples, chapter badges and captions are drawn on top of the
page so the video explains itself. Every outcome you see is produced live by the backend. Nothing
is mocked, and all data is synthetic.

## What it records

| # | Scene | What it shows |
|---|---|---|
| 1 | Sign in | Login page, one-click demo account |
| 2 | Dashboard | Animated stats, outcome bar, outcome filter chips, patient search |
| 3 | Themes | Light → Dark → System (follows the OS live) → Light |
| 4 | Upload a protocol | Uploads `protocol_cardio.pdf`, shows the extracted, page-cited criteria |
| 5 | Add a patient | Imports a synthetic profile from JSON, saves it, sees data-quality flags |
| 6 | Six agents at work | Live agent workflow with parallel inclusion / exclusion matching |
| 7 | Results | Verdict hero, silent exclusion trigger, criteria table, evidence drawer, section navigation, dark mode |
| 8 | The renal case | The 69-year-old / eGFR 28 acceptance case and its page-3 citation |

Outputs, written to `demo/output/`:

- `demo.mp4`: H.264 video, plays everywhere. This needs `ffmpeg` on `PATH` or `FFMPEG_PATH`.
- `demo.webm`: the raw recording.
- `screenshots/`: 12 PNGs covering desktop light/dark and mobile.

## Run it

You need three terminals.

1. **Backend**, from `backend/`:
   ```bash
   uvicorn app.main:app --port 8000
   python -m scripts.seed --api-url http://localhost:8000 --analyze   # demo user + 4 protocols + 10 patients + 9 runs
   ```
2. **Frontend**, from `frontend/`:
   ```bash
   npm ci && npm run build && npm run preview -- --port 5173 --strictPort
   ```
3. **Demo**, from `demo/`:
   ```bash
   npm install
   npm run install-ffmpeg     # once: Playwright's video encoder
   npm run demo               # headless recording, about 2.5 minutes
   npm run demo:watch         # same, in a visible browser window
   ```

The script uses an installed Microsoft Edge by default (`DEMO_BROWSER_CHANNEL=msedge`). Set it to
`chrome` to use Google Chrome. Set it to `chromium` to use a Playwright-managed Chromium, which needs
`npx playwright-core install chromium` first.

## Options

| Variable | Default | Purpose |
|---|---|---|
| `DEMO_BASE_URL` | `http://localhost:5173` | Frontend to drive. It can be the deployed Render URL. |
| `DEMO_API_URL` | `http://localhost:8000` | Backend health check before starting |
| `DEMO_BROWSER_CHANNEL` | `msedge` | `msedge`, `chrome` or `chromium` |
| `DEMO_PACE` | `1` | Pause multiplier: `1.5` is slower and easier to narrate, `0.6` is a quick check |
| `DEMO_OUT` | `demo/output` | Output folder |
| `DEMO_EMAIL` / `DEMO_PASSWORD` | demo account | Account to sign in with |
| `FFMPEG_PATH` | `ffmpeg` | ffmpeg binary for the MP4 conversion |

Each run uploads one more copy of the synthetic heart-failure protocol and creates one more
synthetic walk-in patient. Their names are time-stamped so runs don't collide. To start clean,
stop the backend, delete `backend/data/`, start it again and re-run the seed.

If a step fails, the script saves `output/failure.png`, keeps the partial video and exits non-zero.
That makes it usable as a smoke test of the whole user journey.
