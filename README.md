# Virlo Exporter

Virlo Exporter is a native Windows desktop application for managing Virlo Content Research Agents, monitoring their runs, and exporting existing research into an AI-ready JSON package without hidden paid API calls.

## Install and run

Open PowerShell in this folder and run:

```powershell
.\setup_windows.ps1
```

The script creates `.venv`, installs dependencies, runs tests, builds the onedir production application, creates `Virlo Exporter.lnk` on the current user's Desktop, and launches the app. For development:

```powershell
.\.venv\Scripts\python.exe -m virlo_exporter.main
```

## Connect Virlo

Create an API key at `https://dev.virlo.ai/dashboard`; keys begin with `virlo_tkn_`. Paste it into the first-run Connect Virlo dialog. The production application stores it through `keyring` in Windows Credential Manager—not in SQLite or settings files. `VIRLO_API_KEY` is supported for development only.

## What the app uses

The integration targets `https://api.virlo.ai/v1` and the current unified Content Research Agent API:

- `POST /agents/suggest-keywords` — free keyword suggestions.
- `POST /agents` — paid creation and immediate first run.
- `GET /agents`, `GET /agents/:id`, `PUT /agents/:id`, `DELETE /agents/:id`.
- `GET /agents/:id/runs` and `GET /agents/:id/runs/:run_id`.
- Agent data reads for videos, slideshows, ads, creator outliers, analysis, trends, sounds, hashtags, benchmarks, affinity, activity, and proposals.
- `GET /agents/:id/hooks` only when Data Intelligence makes that read free.

Orbit and Comet endpoints are not used. Virlo currently documents no separate free balance REST endpoint, so the app shows `Balance unavailable` until a paid response supplies `X-Balance-Remaining` or `X-Credits-Remaining`.

## Billing safety

Creating research costs $0.50 per run. Data Intelligence adds $1.00 per run; Meta Ads is included. One-time research is charged when created. A recurring Agent is charged for each scheduled run, including its first. The app displays an explicit confirmation with the estimated total before `POST /agents`, never blindly retries an ambiguous paid request, and reports actual billing headers when Virlo provides them.

Agent/list/read/update/pause/soft-delete operations used by this app are free. Export is always free: it reads only persisted Agent resources and will never call global trends, global hooks, digests, Satellite enrichment, or another research job. Hooks are skipped when their Agent endpoint is not free.

## Exports

The default export folder is `exports` beside the source app (or beside the built executable). It can be changed in Settings. Every export creates a new directory:

```text
exports/<Agent>/Research_007/Export_001_<timestamp>/
├── VIRLO_AI_DATASET.json
├── RAW/
│   ├── agent.json
│   ├── run.json
│   ├── videos.json
│   └── ...
└── export.log
```

`RAW` preserves complete retrieved records and unknown fields. `VIRLO_AI_DATASET.json` is a curated post-analysis package: Virlo analysis and intelligence, trends, hooks where free, outliers, ads, supporting resources, deduplicated high-signal evidence videos, and a deterministic baseline sample. No media is downloaded and no ZIP/PDF is created.

Most Agent data endpoints represent the current full Agent corpus rather than one historical run. The dataset therefore marks these resources as `scope: agent` and stores the selected run separately as `scope: run`; it never silently claims corpus data is run-specific.

## Build and test

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
.\build.ps1
```

The built application is `dist\Virlo Exporter\Virlo Exporter.exe`. Local state is kept under the Windows per-user application data directory in `virlo-exporter.db`; the API key is not stored there.

