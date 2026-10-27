# TraceFix — Production Deployment & Operation Guide

This document provides exact, verified deployment instructions for deploying TraceFix as a single-container web application.

---

## 1. Primary Recommended Host: Render Web Service

Render is the recommended hosting platform for TraceFix because it natively supports Docker multi-stage builds, provides automatic HTTPS, supports environment variables, and offers health check probes.

### Step-by-Step Render Deployment Guide

1. **Log in to Render:**
   - Navigate to [https://dashboard.render.com](https://dashboard.render.com).
   - Sign in with your GitHub account.

2. **Create New Web Service:**
   - Click **"New +"** in the top navigation bar and select **"Web Service"**.
   - Select **"Build and deploy from a Git repository"**.
   - Choose the `TraceFix` repository from your connected GitHub account.

3. **Configure Service Settings:**
   - **Name:** `tracefix` (or your preferred service name)
   - **Region:** Choose the region closest to your users (e.g., `Oregon (US West)` or `Frankfurt (EU Central)`).
   - **Branch:** `main`
   - **Runtime:** **Docker** (Render will automatically detect the root `Dockerfile`).
   - **Instance Type:** `Free` or `Starter` (0.5 CPU, 512 MB RAM is sufficient for the demo happy path with disk AST snapshots).

4. **Configure Environment Variables:**
   Under the **"Environment Variables"** section, set:

   | Variable | Value | Notes |
   | :--- | :--- | :--- |
   | `PORT` | `8000` | Render injects this port automatically. |
   | `TRACEFIX_READ_ONLY` | `true` | Restricts repository connections to the pre-packaged demo repository in public environments. |
   | `ANTHROPIC_API_KEY` | *(Optional)* | Only required if you want live LLM patch generation. When unset, the demo functions normally and truthfully marks repair as `UNAVAILABLE`. |
   | `FALKORDB_HOST` | *(Optional)* | Defaults to `localhost`. When offline, TraceFix uses the built-in disk AST snapshot. |

5. **Configure Health Check Path:**
   - In **Advanced Settings**, set **Health Check Path** to:
     ```text
     /api/health
     ```
   - Render's load balancer will poll this endpoint before routing traffic to a new deployment.

6. **Deploy:**
   - Click **"Create Web Service"**.
   - Render will clone the repository, run the multi-stage Docker build, and start the application.
   - Once deployed, your public URL will be `https://<service-name>.onrender.com`.

---

## 2. Operational Considerations

### Cold-Start Behavior
- **Free Tier Sleep:** On Render's Free tier, the service spins down after 15 minutes of inactivity. The first request after sleep will experience a cold-start latency of approximately 30–50 seconds while the container initializes.
- **Persistent Tier (Starter):** On the `Starter` plan ($7/mo), the container remains active 24/7 with zero cold starts.

### Memory & Storage Footprint
- **Memory Consumption:**
  - FastAPI + Uvicorn: ~70 MB RAM.
  - Ingested AST graph snapshot in memory: ~45 MB RAM.
  - Total working set: < 200 MB RAM (comfortably below the 512 MB free tier threshold).
- **Disk Storage:**
  - All demo artifacts (`data/repos/requests`, `artifacts/graphs/requests_84773555.json`) are bundled inside the Docker image. No external persistent volume is required for the public demo.

### Offline & Fallback Feasibility
- **FalkorDB Independence:** The deployed demo does **not** require a running FalkorDB Redis instance. When port 6379 fails to connect, TraceFix automatically activates `SnapshotNeighborhoodProvider` to traverse the AST property graph from disk artifacts without error.
- **LLM Independence:** Patch generation and sandbox execution are optional. Without an Anthropic API key, investigations execute fully (AST graph, ranked evidence, context budgeting, baseline comparison) and repair status is truthfully reported as `UNAVAILABLE`.

---

## 3. Post-Deployment Verification Checklist

Once your Render service displays `Live`:

1. **Verify Static Frontend:**
   - Open `https://<service-name>.onrender.com` in your browser.
   - Verify the warm cream (`#f3efe6`) 3-column workspace renders: Investigation, Dependency Graph, and Findings Summary.

2. **Verify Health Endpoint:**
   - Query `curl -s https://<service-name>.onrender.com/api/health`
   - Expected JSON response:
     ```json
     {
       "status": "degraded",
       "version": "0.0.1",
       "falkordb_connected": false,
       "redis_endpoint": "localhost:6379",
       "active_cases_count": 44,
       "persisted_graphs_count": 22,
       "connected_repos_count": 1
     }
     ```

3. **Verify Demo Investigation:**
   - On the web UI, click the `requests-1142` preset button.
   - Click **"Investigate Bug"**.
   - Confirm Panel 2 displays the dependency graph with the `Session.send` primary evidence card.
   - Confirm Panel 3 displays ranked files, 3.9k token budget usage, and truthful verification status.

4. **Verify Security Isolation:**
   - Confirm visitors cannot supply arbitrary server directory paths to inspect host secrets.
