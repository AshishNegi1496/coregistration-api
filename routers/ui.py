from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse, JSONResponse

from api.config import settings
from api.utils import list_image_files

router = APIRouter(tags=["UI"])


def _file_choices(root):
    files = []
    for path in list_image_files(root, recursive=True):
        files.append({
            "label": str(path.relative_to(root)),
            "value": str(path.relative_to(root)),
        })
    return files


@router.get("/ui", response_class=HTMLResponse)
async def ui_page() -> HTMLResponse:
    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>Coregistration Test UI</title>
      <style>
        :root {{
          --bg: #f6f3eb;
          --card: #ffffff;
          --ink: #1f2937;
          --muted: #6b7280;
          --accent: #0f766e;
          --accent-2: #115e59;
          --line: #d1d5db;
          --soft: #ecfeff;
        }}
        * {{ box-sizing: border-box; }}
        body {{
          margin: 0;
          font-family: Arial, Helvetica, sans-serif;
          background: linear-gradient(135deg, #faf7f2 0%, #eef6f5 100%);
          color: var(--ink);
        }}
        .wrap {{
          max-width: 1100px;
          margin: 0 auto;
          padding: 32px 18px 48px;
        }}
        .hero {{
          display: grid;
          gap: 12px;
          margin-bottom: 24px;
        }}
        .hero h1 {{
          margin: 0;
          font-size: clamp(28px, 4vw, 44px);
          letter-spacing: -0.03em;
        }}
        .hero p {{
          margin: 0;
          max-width: 760px;
          color: var(--muted);
          line-height: 1.55;
        }}
        .grid {{
          display: grid;
          grid-template-columns: 1fr;
          gap: 18px;
        }}
        .card {{
          background: rgba(255,255,255,0.88);
          border: 1px solid rgba(17,24,39,0.08);
          border-radius: 20px;
          padding: 20px;
          box-shadow: 0 16px 48px rgba(15,23,42,0.08);
          backdrop-filter: blur(10px);
        }}
        .section-title {{
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          margin-bottom: 14px;
        }}
        .section-title h2 {{
          margin: 0;
          font-size: 18px;
        }}
        .badge {{
          font-size: 12px;
          color: var(--accent-2);
          background: var(--soft);
          border: 1px solid #bfe8e6;
          border-radius: 999px;
          padding: 6px 10px;
        }}
        label {{
          display: block;
          font-size: 13px;
          margin: 14px 0 8px;
          color: var(--muted);
        }}
        select, input {{
          width: 100%;
          padding: 12px 14px;
          border-radius: 12px;
          border: 1px solid var(--line);
          background: #fff;
          font-size: 14px;
          color: var(--ink);
        }}
        .actions {{
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          margin-top: 18px;
        }}
        button {{
          appearance: none;
          border: 0;
          border-radius: 999px;
          padding: 12px 18px;
          font-weight: 700;
          cursor: pointer;
        }}
        .primary {{
          background: var(--accent);
          color: white;
        }}
        .secondary {{
          background: #e5e7eb;
          color: var(--ink);
        }}
        .mono {{
          font-family: Consolas, "Courier New", monospace;
          font-size: 13px;
          background: #0f172a;
          color: #d1fae5;
          border-radius: 16px;
          padding: 14px;
          overflow: auto;
          min-height: 120px;
          white-space: pre-wrap;
        }}
        .hint {{
          font-size: 13px;
          color: var(--muted);
          margin-top: 8px;
        }}
        .status {{
          font-size: 13px;
          color: var(--accent-2);
          margin-top: 12px;
        }}
        .small {{
          font-size: 12px;
          color: var(--muted);
        }}
        .split {{
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 14px;
        }}
        @media (max-width: 900px) {{
          .split {{
            grid-template-columns: 1fr;
          }}
        }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <div class="hero">
          <h1>Coregistration Test UI</h1>
          <p>Scan folders, select one or more target files, and let the backend automatically match the right base image and run the pipeline in order.</p>
        </div>
        <div class="grid">
          <div class="card">
            <div class="section-title">
              <h2>Job Builder</h2>
              <span class="badge">Auto base matching</span>
            </div>

            <div class="split">
              <div>
                <label for="targetFile">Target files from TARGET_ROOT</label>
                <select id="targetFile" multiple size="10"></select>
                <div class="small">Select one file for a single run or many files for automatic sequential processing.</div>
              </div>
              <div>
                <label for="baseFiles">Base files from BASE_ROOT</label>
                <select id="baseFiles" multiple size="10" disabled></select>
                <div class="small">Base files are matched automatically by geospatial overlap.</div>
              </div>
            </div>

            <div class="actions">
              <button class="secondary" onclick="scanFolders()">Scan Folders</button>
              <button class="primary" onclick="startPipeline()">Start Pipeline</button>
              <button class="secondary" onclick="refreshData()">Refresh Lists</button>
            </div>

            <div class="status" id="jobStatus">Ready to create a job.</div>
          </div>
        </div>

        <div class="card" style="margin-top:18px;">
          <div class="section-title">
            <h2>Job Status</h2>
            <span class="badge">Sequential IDs</span>
          </div>
          <div id="jobsTable" class="mono">Loading...</div>
        </div>

        <div class="card" style="margin-top:18px;">
          <div class="section-title">
            <h2>API Response</h2>
            <span class="badge">Live result</span>
          </div>
          <div id="output" class="mono">Ready.</div>
        </div>
      </div>

      <script>
        function showOutput(value) {{
          document.getElementById("output").textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
        }}

        function setJobStatus(value) {{
          document.getElementById("jobStatus").textContent = value;
        }}

        function getSelectedValues(selectId) {{
          return Array.from(document.getElementById(selectId).selectedOptions).map(option => option.value).filter(Boolean);
        }}

        async function refreshData() {{
          try {{
            const res = await fetch("/api/ui/bootstrap");
            const data = await res.json();
            const target = document.getElementById("targetFile");
            target.innerHTML = data.target_files.length
              ? data.target_files.map(file => `<option value="${{file.value}}">${{file.label}}</option>`).join("")
              : '<option value="">No target files found</option>';
            const base = document.getElementById("baseFiles");
            base.innerHTML = data.base_files.length
              ? data.base_files.map(file => `<option value="${{file.value}}">${{file.label}}</option>`).join("")
              : '<option value="">No base files found</option>';
            if (base.options.length) {{
              base.selectedIndex = 0;
            }}
            setJobStatus(`Loaded ${{data.target_files.length}} target files.`);
            await refreshJobs();
          }} catch (err) {{
            setJobStatus("Failed to load UI data.");
            document.getElementById("jobsTable").textContent = String(err);
          }}
        }}

        async function refreshJobs() {{
          try {{
            const res = await fetch("/api/jobs");
            const jobs = await res.json();
            if (!jobs.length) {{
              document.getElementById("jobsTable").textContent = "No jobs yet.";
              return;
            }}

            const rows = jobs.map(job => `Job #${{job.job_no}} | ${{job.status}} | ${{job.stage || "-"}} | ${{job.sensor_name}} | ${{job.target_path}} -> ${{job.output_path || "-"}}`);
            document.getElementById("jobsTable").textContent = rows.join("\\n");
          }} catch (err) {{
            document.getElementById("jobsTable").textContent = `Could not load jobs: ${{err}}`;
          }}
        }}

        async function startPipeline() {{
          const targets = getSelectedValues("targetFile");

          if (!targets.length) {{
            setJobStatus("Select one or more target files.");
            return;
          }}

          const payload = {{
            target_paths: targets,
            priority: 5,
            publish_to_geoserver: false,
            cog_compression: "LZW",
            tags: {{
              source: "ui-auto"
            }}
          }};

          const res = await fetch("/api/jobs/auto-process", {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(payload)
          }});
          const data = await res.json();
          setJobStatus(`Processed ${{targets.length}} target file(s).`);
          showOutput(data);
          await refreshJobs();
        }}

        async function scanFolders() {{
          const res = await fetch("/api/ui/bootstrap");
          const data = await res.json();
          setJobStatus(`Scan complete. Found ${{data.target_files?.length || 0}} target files and ${{data.base_files?.length || 0}} base files.`);
          showOutput(data);
          await refreshData();
        }}

        refreshData().catch(err => showOutput(String(err)));
      </script>
    </body>
    </html>
    """
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@router.get("/api/ui/bootstrap")
async def ui_bootstrap():
    return JSONResponse({
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "target_root": str(settings.target_root),
        "base_root": str(settings.base_root),
        "output_root": str(settings.output_root),
        "target_files": _file_choices(settings.target_root),
        "base_files": _file_choices(settings.base_root),
    }, headers={"Cache-Control": "no-store"})
