"""
NEXUS — Demo Dashboard
Provides a lightweight, server-rendered and live-refreshing HTML/CSS/JS frontend
presenting equal-weight side-by-side views of Published and Rejected editorial decisions.
"""

from typing import Any, Optional
import json
from app.persona import PERSONA
from app.config import settings


def render_dashboard_html(initial_agent_id: str = "nexus-001") -> str:
    """
    Generate the complete standalone single-page dashboard HTML.
    Includes embedded CSS styling and vanilla JS for live polling and interactive trigger actions.
    """
    persona_dict = {
        "name": PERSONA.name,
        "role": PERSONA.role,
        "niche": PERSONA.niche,
        "voice": PERSONA.voice,
        "standing_opinions": PERSONA.standing_opinions,
        "hard_rules": PERSONA.hard_rules,
    }

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>NEXUS — Autonomous AI Technology Analyst Dashboard</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-base: #090d16;
      --bg-card: rgba(18, 26, 43, 0.75);
      --bg-card-hover: rgba(25, 36, 58, 0.9);
      --bg-header: rgba(10, 15, 29, 0.85);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-focus: rgba(99, 102, 241, 0.4);
      --text-primary: #f1f5f9;
      --text-secondary: #94a3b8;
      --text-muted: #64748b;
      --pub-accent: #10b981;
      --pub-bg: rgba(16, 185, 129, 0.12);
      --pub-border: rgba(16, 185, 129, 0.35);
      --rej-accent: #f43f5e;
      --rej-bg: rgba(244, 63, 94, 0.12);
      --rej-border: rgba(244, 63, 94, 0.35);
      --warn-accent: #f59e0b;
      --warn-bg: rgba(245, 158, 11, 0.12);
      --warn-border: rgba(245, 158, 11, 0.35);
      --info-accent: #38bdf8;
      --info-bg: rgba(56, 189, 248, 0.12);
      --radius-sm: 6px;
      --radius-md: 10px;
      --radius-lg: 16px;
      --font-sans: 'Inter', system-ui, -apple-system, sans-serif;
      --font-mono: 'JetBrains Mono', monospace;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      background: var(--bg-base);
      background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.25) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.15) 0px, transparent 50%),
        radial-gradient(at 100% 0%, rgba(244, 63, 94, 0.15) 0px, transparent 50%);
      background-size: 200% 200%;
      animation: gradientMove 15s ease infinite;
      background-attachment: fixed;
      color: var(--text-primary);
      font-family: var(--font-sans);
      min-height: 100vh;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }}

    @keyframes gradientMove {{
      0% {{ background-position: 0% 50%; }}
      50% {{ background-position: 100% 50%; }}
      100% {{ background-position: 0% 50%; }}
    }}

    @keyframes fadeUp {{
      from {{ opacity: 0; transform: translateY(20px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    .animate-fade-up {{
      animation: fadeUp 0.6s cubic-bezier(0.16, 1, 0.3, 1) forwards;
      opacity: 0;
    }}

    /* Top Navigation */
    header.topbar {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: var(--bg-header);
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      border-bottom: 1px solid var(--border-subtle);
      padding: 0.85rem 1.5rem;
    }}

    .topbar-content {{
      max-width: 1440px;
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 1rem;
    }}

    .brand {{
      display: flex;
      align-items: center;
      gap: 0.85rem;
    }}

    .brand-logo {{
      width: 36px;
      height: 36px;
      background: linear-gradient(135deg, #6366f1, #38bdf8);
      border-radius: 8px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: 800;
      font-size: 1.1rem;
      color: #ffffff;
      box-shadow: 0 0 20px rgba(99, 102, 241, 0.4);
    }}

    .brand-title {{
      font-size: 1.45rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      background: linear-gradient(135deg, #ffffff 0%, #cbd5e1 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }}

    .brand-subtitle {{
      font-size: 0.75rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-weight: 600;
    }}

    .status-pill {{
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      padding: 0.25rem 0.65rem;
      border-radius: 9999px;
      font-size: 0.75rem;
      font-weight: 600;
      background: var(--pub-bg);
      border: 1px solid var(--pub-border);
      color: var(--pub-accent);
    }}

    .pulse-dot {{
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background-color: var(--pub-accent);
      box-shadow: 0 0 8px var(--pub-accent);
      animation: pulse 2s infinite ease-in-out;
    }}

    @keyframes pulse {{
      0%, 100% {{ opacity: 1; transform: scale(1); }}
      50% {{ opacity: 0.4; transform: scale(0.85); }}
    }}

    .controls {{
      display: flex;
      align-items: center;
      gap: 0.75rem;
      flex-wrap: wrap;
    }}

    .btn {{
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      padding: 0.5rem 0.95rem;
      border-radius: var(--radius-sm);
      font-size: 0.825rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease-in-out;
      border: 1px solid transparent;
      outline: none;
      font-family: inherit;
    }}

    .btn:disabled {{
      opacity: 0.6;
      cursor: not-allowed;
    }}

    .btn-primary {{
      background: linear-gradient(135deg, #4f46e5, #6366f1);
      color: #ffffff;
      box-shadow: 0 2px 10px rgba(79, 70, 229, 0.35);
    }}

    .btn-primary:hover:not(:disabled) {{
      background: linear-gradient(135deg, #4338ca, #4f46e5);
      transform: translateY(-1px);
      box-shadow: 0 4px 14px rgba(79, 70, 229, 0.45);
    }}

    .btn-secondary {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-primary);
    }}

    .btn-secondary:hover:not(:disabled) {{
      background: rgba(255, 255, 255, 0.1);
      border-color: rgba(255, 255, 255, 0.2);
    }}

    /* Main Container */
    main.container {{
      max-width: 1440px;
      margin: 1.5rem auto;
      padding: 0 1.5rem 3rem 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1.5rem;
    }}

    /* Telemetry & Persona Strip */
    .telemetry-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1rem;
    }}

    .telemetry-card {{
      background: var(--bg-card);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: var(--radius-md);
      padding: 1.15rem 1.35rem;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
      box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.25);
      transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}

    .telemetry-card:hover {{
      transform: translateY(-2px);
      box-shadow: 0 12px 40px 0 rgba(0, 0, 0, 0.35);
      border-color: rgba(255, 255, 255, 0.15);
    }}

    .telemetry-label {{
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}

    .telemetry-value {{
      font-size: 1.35rem;
      font-weight: 700;
      color: #ffffff;
      font-family: var(--font-mono);
    }}

    .telemetry-sub {{
      font-size: 0.75rem;
      color: var(--text-secondary);
    }}

    /* Persona Stance Banner */
    .persona-card {{
      background: var(--bg-card);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: var(--radius-md);
      padding: 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.25);
    }}

    .persona-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 0.5rem;
    }}

    .persona-title {{
      font-size: 0.95rem;
      font-weight: 700;
      color: var(--info-accent);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }}

    .persona-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1rem;
    }}

    @media (max-width: 900px) {{
      .persona-grid {{
        grid-template-columns: 1fr;
      }}
    }}

    .persona-section-title {{
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--text-secondary);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.35rem;
    }}

    .rule-item {{
      font-size: 0.8rem;
      color: var(--text-secondary);
      margin-bottom: 0.25rem;
      display: flex;
      align-items: flex-start;
      gap: 0.4rem;
    }}

    .rule-bullet {{
      color: var(--info-accent);
      font-weight: bold;
    }}

    /* Equal Weight Columns Header */
    .dual-stream-banner {{
      text-align: center;
      padding: 0.5rem 0;
    }}

    .dual-stream-banner h2 {{
      font-size: 1.15rem;
      font-weight: 700;
      letter-spacing: -0.01em;
      color: #ffffff;
    }}

    .dual-stream-banner p {{
      font-size: 0.825rem;
      color: var(--text-secondary);
    }}

    /* Equal-Weight Dual Columns */
    .decision-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 1.5rem;
      align-items: start;
    }}

    @media (max-width: 1024px) {{
      .decision-grid {{
        grid-template-columns: 1fr;
      }}
    }}

    .column-wrapper {{
      display: flex;
      flex-direction: column;
      gap: 1rem;
    }}

    .column-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.85rem 1.25rem;
      border-radius: var(--radius-md);
      font-weight: 700;
      font-size: 0.95rem;
      backdrop-filter: blur(12px);
    }}

    .column-header.published {{
      background: var(--pub-bg);
      border: 1px solid var(--pub-border);
      color: var(--pub-accent);
    }}

    .column-header.rejected {{
      background: var(--rej-bg);
      border: 1px solid var(--rej-border);
      color: var(--rej-accent);
    }}

    .column-count-badge {{
      background: rgba(0, 0, 0, 0.4);
      padding: 0.15rem 0.6rem;
      border-radius: 9999px;
      font-size: 0.8rem;
      font-family: var(--font-mono);
    }}

    /* Decision Cards */
    .decision-card {{
      background: var(--bg-card);
      backdrop-filter: blur(24px);
      -webkit-backdrop-filter: blur(24px);
      border-radius: var(--radius-md);
      padding: 1.35rem;
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
      transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
      border: 1px solid rgba(255, 255, 255, 0.08);
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
    }}

    .decision-card:hover {{
      background: var(--bg-card-hover);
      border-color: rgba(255, 255, 255, 0.2);
      transform: translateY(-6px) scale(1.01);
      box-shadow: 0 12px 40px rgba(0, 0, 0, 0.4);
    }}

    .decision-card.pub-card {{
      border-left: 4px solid var(--pub-accent);
    }}

    .decision-card.rej-card {{
      border-left: 4px solid var(--rej-accent);
    }}

    .card-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      flex-wrap: wrap;
    }}

    .card-badges {{
      display: flex;
      align-items: center;
      gap: 0.4rem;
      flex-wrap: wrap;
    }}

    .badge {{
      font-size: 0.7rem;
      font-weight: 700;
      padding: 0.2rem 0.5rem;
      border-radius: var(--radius-sm);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}

    .badge-publish {{
      background: var(--pub-bg);
      color: var(--pub-accent);
      border: 1px solid var(--pub-border);
    }}

    .badge-reject {{
      background: var(--rej-bg);
      color: var(--rej-accent);
      border: 1px solid var(--rej-border);
    }}

    .badge-stage {{
      background: rgba(255, 255, 255, 0.06);
      color: var(--text-secondary);
      border: 1px solid var(--border-subtle);
    }}

    .card-score {{
      font-family: var(--font-mono);
      font-size: 0.875rem;
      font-weight: 700;
      padding: 0.15rem 0.5rem;
      border-radius: var(--radius-sm);
      background: rgba(0, 0, 0, 0.35);
      border: 1px solid var(--border-subtle);
    }}

    .card-score.high {{
      color: var(--pub-accent);
      border-color: var(--pub-border);
    }}

    .card-score.low {{
      color: var(--rej-accent);
      border-color: var(--rej-border);
    }}

    .card-title {{
      font-size: 1rem;
      font-weight: 700;
      color: #ffffff;
      line-height: 1.35;
    }}

    .card-timestamp {{
      font-size: 0.725rem;
      color: var(--text-muted);
      font-family: var(--font-mono);
    }}

    /* Score Breakdown Matrix */
    .factors-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
      gap: 0.4rem;
      background: rgba(0, 0, 0, 0.25);
      padding: 0.6rem;
      border-radius: var(--radius-sm);
      border: 1px solid rgba(255, 255, 255, 0.04);
    }}

    .factor-item {{
      display: flex;
      flex-direction: column;
      gap: 0.15rem;
    }}

    .factor-name {{
      font-size: 0.65rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
    }}

    .factor-val {{
      font-size: 0.775rem;
      font-weight: 700;
      font-family: var(--font-mono);
      color: var(--text-primary);
    }}

    .factor-val.floor-breach {{
      color: var(--rej-accent);
      font-weight: 800;
    }}

    /* Content Body */
    .post-body {{
      font-size: 0.85rem;
      color: #cbd5e1;
      white-space: pre-line;
      line-height: 1.6;
    }}

    /* Rejection Callout Box */
    .rejection-box {{
      background: var(--rej-bg);
      border: 1px solid var(--rej-border);
      border-radius: var(--radius-sm);
      padding: 0.75rem 0.9rem;
      display: flex;
      flex-direction: column;
      gap: 0.35rem;
    }}

    .rejection-header {{
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--rej-accent);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      display: flex;
      align-items: center;
      gap: 0.35rem;
    }}

    .rejection-text {{
      font-size: 0.825rem;
      color: #fecdd3;
      line-height: 1.45;
    }}

    /* Rationale Callout */
    .rationale-box {{
      background: rgba(99, 102, 241, 0.08);
      border: 1px solid rgba(99, 102, 241, 0.2);
      border-radius: var(--radius-sm);
      padding: 0.75rem 0.9rem;
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
    }}

    .rationale-item {{
      font-size: 0.775rem;
      color: #e2e8f0;
      line-height: 1.4;
    }}

    .rationale-label {{
      font-weight: 700;
      color: #a5b4fc;
      margin-right: 0.35rem;
    }}

    /* Sources */
    .sources-list {{
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
      font-size: 0.75rem;
    }}

    .source-link {{
      color: var(--info-accent);
      text-decoration: none;
      word-break: break-all;
      display: inline-flex;
      align-items: center;
      gap: 0.3rem;
    }}

    .source-link:hover {{
      text-decoration: underline;
    }}

    /* Empty State */
    .empty-state {{
      text-align: center;
      padding: 3rem 1.5rem;
      background: var(--bg-card);
      border: 1px dashed var(--border-subtle);
      border-radius: var(--radius-md);
      color: var(--text-muted);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 0.65rem;
    }}

    /* Toast Notification */
    #toast {{
      position: fixed;
      bottom: 24px;
      right: 24px;
      padding: 0.85rem 1.25rem;
      border-radius: var(--radius-md);
      font-size: 0.85rem;
      font-weight: 600;
      background: #1e293b;
      color: #ffffff;
      border: 1px solid var(--border-subtle);
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.5);
      z-index: 1000;
      display: flex;
      align-items: center;
      gap: 0.5rem;
      transform: translateY(100px);
      opacity: 0;
      transition: all 0.25s ease-out;
      pointer-events: none;
    }}

    #toast.show {{
      transform: translateY(0);
      opacity: 1;
    }}

    #toast.success {{
      border-color: var(--pub-border);
      background: rgba(15, 23, 42, 0.95);
      color: var(--pub-accent);
    }}

    #toast.error {{
      border-color: var(--rej-border);
      background: rgba(15, 23, 42, 0.95);
      color: var(--rej-accent);
    }}

    /* Loading Spinner */
    .spinner {{
      width: 14px;
      height: 14px;
      border: 2px solid rgba(255, 255, 255, 0.2);
      border-top-color: #ffffff;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }}

    @keyframes spin {{
      to {{ transform: rotate(360deg); }}
    }}
  </style>
</head>
<body>

  <!-- Top Navbar -->
  <header class="topbar">
    <div class="topbar-content">
      <div class="brand">
        <div class="brand-logo">N</div>
        <div>
          <div class="brand-title">
            NEXUS
            <span class="status-pill" id="agent-status-pill">
              <span class="pulse-dot"></span>
              <span id="agent-status-text">Autonomous Active</span>
            </span>
          </div>
          <div class="brand-subtitle">Autonomous AI Technology Analyst</div>
        </div>
      </div>

      <div class="controls">
        <button id="btn-trigger-rss" class="btn btn-primary" onclick="triggerCycle(false)">
          <span>⚡</span>
          <span>Trigger Cycle (Live RSS)</span>
        </button>
        <button id="btn-trigger-demo" class="btn btn-secondary" onclick="triggerCycle(true)">
          <span>🧪</span>
          <span>Trigger Demo Cycle</span>
        </button>
      </div>
    </div>
  </header>

  <!-- Main Container -->
  <main class="container">

    <!-- Telemetry Cards -->
    <section class="telemetry-grid">
      <div class="telemetry-card">
        <div class="telemetry-label">Agent ID & Status</div>
        <div class="telemetry-value" id="val-agent-id">{initial_agent_id}</div>
        <div class="telemetry-sub" id="val-agent-sub">Autonomous Loop Online</div>
      </div>
      <div class="telemetry-card">
        <div class="telemetry-label">Next Autonomous Cycle</div>
        <div class="telemetry-value" id="val-next-cycle">--:--</div>
        <div class="telemetry-sub" id="val-interval">Every 300s (5 mins)</div>
      </div>
      <div class="telemetry-card">
        <div class="telemetry-label">Cycles Executed</div>
        <div class="telemetry-value" id="val-cycle-count">0</div>
        <div class="telemetry-sub" id="val-cycle-sub">Autonomous & Dry-Run</div>
      </div>
      <div class="telemetry-card">
        <div class="telemetry-label">LLM Engine</div>
        <div class="telemetry-value" id="val-llm-model" style="font-size: 1.1rem;">gemini-2.0-flash</div>
        <div class="telemetry-sub" id="val-llm-status">API Key Configured</div>
      </div>
    </section>

    <!-- Persona & Editorial Philosophy Banner -->
    <section class="persona-card">
      <div class="persona-header">
        <div class="persona-title">
          <span>🛡️</span>
          <span>NEXUS Editorial Stance & Operational Philosophy</span>
        </div>
        <span class="status-pill" style="background: var(--info-bg); border-color: var(--border-focus); color: var(--info-accent);">
          Domain: AI Infrastructure & Multi-Agent Systems
        </span>
      </div>
      <div class="persona-grid">
        <div>
          <div class="persona-section-title">Hard Editorial Rules (Zero Compromise)</div>
          <div class="rule-item"><span class="rule-bullet">✕</span> <span><strong>Hard Evidence Floor:</strong> Force REJECT if Evidence Quality &lt; 40, regardless of composite score.</span></div>
          <div class="rule-item"><span class="rule-bullet">✕</span> <span><strong>Anti-Hype Mandate:</strong> Reject secondary press releases, buzzword claims, and unverified benchmarks.</span></div>
          <div class="rule-item"><span class="rule-bullet">✓</span> <span><strong>Strict Grounding:</strong> Never fabricate facts; every claim must be traceable to primary repository artifacts.</span></div>
        </div>
        <div>
          <div class="persona-section-title">Core Analytical Stances</div>
          <div class="rule-item"><span class="rule-bullet">•</span> <span>Favors native, first-party framework implementations over thin wrapper layers.</span></div>
          <div class="rule-item"><span class="rule-bullet">•</span> <span>Treats state persistence and human-in-the-loop recovery as essential for production agents.</span></div>
          <div class="rule-item"><span class="rule-bullet">•</span> <span>Demands reproducible benchmarks and transparent architectural trade-offs.</span></div>
        </div>
      </div>
    </section>

    <!-- Dual Stream Headline Banner -->
    <div class="dual-stream-banner">
      <h2>⚖️ Editorial Decision Stream — Equal Visual Weight</h2>
      <p>NEXUS does not simply generate content — it exercises independent judgment on what deserves to be published and what deserves rejection.</p>
    </div>

    <!-- Equal-Weight Decision Stream: Left = Published, Right = Rejected -->
    <section class="decision-grid">

      <!-- Column 1: Published Articles (Emerald Glow) -->
      <div class="column-wrapper">
        <div class="column-header published">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span>✨</span>
            <span>PUBLISHED TECHNICAL POSTS</span>
          </div>
          <span class="column-count-badge" id="count-published">0 POSTS</span>
        </div>
        <div id="stream-published" style="display: flex; flex-direction: column; gap: 1rem;">
          <div class="empty-state">
            <span>📡</span>
            <div>No published posts yet</div>
            <span style="font-size: 0.75rem;">Trigger a cycle above to run discovery & scoring.</span>
          </div>
        </div>
      </div>

      <!-- Column 2: Rejected Decisions (Crimson Glow - EQUAL WEIGHT) -->
      <div class="column-wrapper">
        <div class="column-header rejected">
          <div style="display: flex; align-items: center; gap: 0.5rem;">
            <span>🛡️</span>
            <span>REJECTED CANDIDATES & REASONS</span>
          </div>
          <span class="column-count-badge" id="count-rejected">0 REJECTED</span>
        </div>
        <div id="stream-rejected" style="display: flex; flex-direction: column; gap: 1rem;">
          <div class="empty-state">
            <span>🔍</span>
            <div>No rejected candidates yet</div>
            <span style="font-size: 0.75rem;">Rejections will appear here with full scoring rationales.</span>
          </div>
        </div>
      </div>

    </section>

    <!-- Discovered Candidates Stream -->
    <section class="persona-card" style="margin-top: 1rem;">
      <div class="persona-header">
        <div class="persona-title" style="color: var(--text-primary);">
          <span>📥</span>
          <span>Recently Discovered Candidates in Active Memory Window</span>
        </div>
        <span class="column-count-badge" id="count-seen">0 SEEN</span>
      </div>
      <div id="stream-seen" style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 0.75rem;">
        <div class="empty-state" style="grid-column: 1 / -1; padding: 1.5rem;">
          <span>Discovery memory is waiting for the next cycle.</span>
        </div>
      </div>
    </section>

  </main>

  <!-- Toast Notification -->
  <div id="toast"></div>

  <!-- Client-Side Vanilla JS -->
  <script>
    const AGENT_ID = "{initial_agent_id}";
    let nextRunDate = null;
    let countdownInterval = null;

    function showToast(message, type = "success") {{
      const toast = document.getElementById("toast");
      toast.textContent = message;
      toast.className = `show ${{type}}`;
      setTimeout(() => {{
        toast.className = "";
      }}, 4000);
    }}

    function formatDate(isoStr) {{
      if (!isoStr) return "";
      try {{
        const d = new Date(isoStr);
        return d.toLocaleTimeString([], {{ hour: '2-digit', minute: '2-digit', second: '2-digit' }}) + ' UTC (' + d.toISOString().slice(0, 10) + ')';
      }} catch (e) {{
        return isoStr;
      }}
    }}

    function startCountdown(isoStr) {{
      if (!isoStr) {{
        document.getElementById("val-next-cycle").textContent = "--:--";
        return;
      }}
      nextRunDate = new Date(isoStr);
      if (countdownInterval) clearInterval(countdownInterval);

      function update() {{
        const now = new Date();
        const diffSec = Math.floor((nextRunDate - now) / 1000);
        if (diffSec <= 0) {{
          document.getElementById("val-next-cycle").textContent = "Executing...";
          return;
        }}
        const mins = Math.floor(diffSec / 60).toString().padStart(2, '0');
        const secs = (diffSec % 60).toString().padStart(2, '0');
        document.getElementById("val-next-cycle").textContent = `${{mins}}:${{secs}}`;
      }}
      update();
      countdownInterval = setInterval(update, 1000);
    }}

    async function fetchDashboardData() {{
      try {{
        const res = await fetch(`/api/agent/dashboard-data?agentId=${{AGENT_ID}}`);
        if (!res.ok) return;
        const data = await res.json();
        renderDashboard(data);
      }} catch (err) {{
        console.error("Dashboard poll failed:", err);
      }}
    }}

    function renderDashboard(data) {{
      // 1. Telemetry
      const sched = data.scheduler || {{}};
      document.getElementById("val-agent-id").textContent = sched.agent_id || AGENT_ID;
      document.getElementById("val-cycle-count").textContent = sched.cycle_count || 0;
      document.getElementById("val-llm-model").textContent = sched.llm_model || "gemini-2.0-flash";
      document.getElementById("val-interval").textContent = `Every ${{sched.interval_seconds || 300}}s (${{Math.round((sched.interval_seconds || 300)/60)}} mins)`;
      
      if (sched.is_cycle_executing) {{
        document.getElementById("agent-status-text").textContent = "Cycle in Progress...";
        document.getElementById("agent-status-pill").style.background = "var(--warn-bg)";
        document.getElementById("agent-status-pill").style.color = "var(--warn-accent)";
        document.getElementById("agent-status-pill").style.borderColor = "var(--warn-border)";
      }} else if (sched.running) {{
        document.getElementById("agent-status-text").textContent = "Autonomous Active";
        document.getElementById("agent-status-pill").style.background = "var(--pub-bg)";
        document.getElementById("agent-status-pill").style.color = "var(--pub-accent)";
        document.getElementById("agent-status-pill").style.borderColor = "var(--pub-border)";
      }}

      if (sched.next_run_time) {{
        startCountdown(sched.next_run_time);
      }}

      // 2. Published Posts
      const published = data.published_posts || [];
      document.getElementById("count-published").textContent = `${{published.length}} POST${{published.length === 1 ? '' : 'S'}}`;
      const pubContainer = document.getElementById("stream-published");
      if (published.length === 0) {{
        pubContainer.innerHTML = `
          <div class="empty-state">
            <span>📡</span>
            <div>No published posts yet</div>
            <span style="font-size: 0.75rem;">Trigger a cycle above to run discovery & scoring.</span>
          </div>
        `;
      }} else {{
        pubContainer.innerHTML = published.map(post => {{
          const rat = post.rationale || {{}};
          const factors = rat.factor_scores || {{}};
          const score = Math.round(post.editorial_score || rat.editorial_score || 0);
          const sources = post.sources || [];
          
          return `
            <article class="decision-card pub-card animate-fade-up">
              <div class="card-top">
                <div class="card-badges">
                  <span class="badge badge-publish">PUBLISH</span>
                  <span class="badge badge-stage">Editorial Score ${{score}}/100</span>
                </div>
                <span class="card-timestamp">${{formatDate(post.created_at || post.createdAt)}}</span>
              </div>

              <h3 class="card-title">${{post.topic || 'Published Technical Analysis'}}</h3>

              <div class="factors-grid">
                <div class="factor-item"><span class="factor-name">Relevance</span><span class="factor-val">${{factors.relevance || '--'}}</span></div>
                <div class="factor-item"><span class="factor-name">Novelty</span><span class="factor-val">${{factors.novelty || '--'}}</span></div>
                <div class="factor-item"><span class="factor-name">Tech Impact</span><span class="factor-val">${{factors.technical_impact || '--'}}</span></div>
                <div class="factor-item"><span class="factor-name">Evidence</span><span class="factor-val" style="color: var(--pub-accent);">${{factors.evidence_quality || '--'}}</span></div>
                <div class="factor-item"><span class="factor-name">Timeliness</span><span class="factor-val">${{factors.timeliness || '--'}}</span></div>
              </div>

              <div class="post-body">${{post.generated_text || post.text || post.summary || ''}}</div>

              <div class="rationale-box">
                <div class="rationale-item"><span class="rationale-label">Why Selected:</span>${{rat.why_selected || 'Scored above threshold with verified primary evidence.'}}</div>
                <div class="rationale-item"><span class="rationale-label">Why Relevant Now:</span>${{rat.why_relevant_now || 'Recent technical release.'}}</div>
                ${{rat.evidence_quality_note ? `<div class="rationale-item"><span class="rationale-label">Evidence Note:</span>${{rat.evidence_quality_note}}</div>` : ''}}
              </div>

              ${{sources.length > 0 ? `
                <div class="sources-list">
                  <span style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Verified Primary Sources:</span>
                  ${{sources.map(s => `<a href="${{s}}" target="_blank" rel="noopener noreferrer" class="source-link">🔗 ${{s}}</a>`).join('')}}
                </div>
              ` : ''}}
            </article>
          `;
        }}).join('');
      }}

      // 3. Rejected Topics (Equal visual weight)
      const rejected = data.rejected_posts || [];
      document.getElementById("count-rejected").textContent = `${{rejected.length}} REJECTED`;
      const rejContainer = document.getElementById("stream-rejected");
      if (rejected.length === 0) {{
        rejContainer.innerHTML = `
          <div class="empty-state">
            <span>🛡️</span>
            <div>No rejected candidates yet</div>
            <span style="font-size: 0.75rem;">Rejections will appear here with full scoring rationales.</span>
          </div>
        `;
      }} else {{
        rejContainer.innerHTML = rejected.map(rej => {{
          const rat = rej.rationale || {{}};
          const factors = rat.factor_scores || {{}};
          const score = (rej.editorial_score != null) ? rej.editorial_score.toFixed(1) : (rat.editorial_score || '--');
          const stage = rat.stage || (score &lt; 40 ? 'Stage A: Evidence Floor' : 'Stage A: Editorial Rubric');
          const reason = rat.rejection_reason || rat.reason || rej.summary || 'Failed editorial criteria.';
          const sources = rej.sources || [];

          return `
            <article class="decision-card rej-card animate-fade-up">
              <div class="card-top">
                <div class="card-badges">
                  <span class="badge badge-reject">REJECTED</span>
                  <span class="badge badge-stage">${{stage}}</span>
                </div>
                <span class="card-score low">Score: ${{score}}/100</span>
              </div>

              <h3 class="card-title" style="color: #f87171;">${{rej.topic || 'Candidate Topic'}}</h3>
              <div class="card-timestamp">${{formatDate(rej.created_at || rej.createdAt)}}</div>

              ${{factors.relevance != null ? `
                <div class="factors-grid">
                  <div class="factor-item"><span class="factor-name">Relevance</span><span class="factor-val">${{factors.relevance}}</span></div>
                  <div class="factor-item"><span class="factor-name">Novelty</span><span class="factor-val">${{factors.novelty}}</span></div>
                  <div class="factor-item"><span class="factor-name">Tech Impact</span><span class="factor-val">${{factors.technical_impact}}</span></div>
                  <div class="factor-item"><span class="factor-name">Evidence</span><span class="factor-val ${{factors.evidence_quality &lt; 40 ? 'floor-breach' : ''}}">${{factors.evidence_quality}} ${{factors.evidence_quality &lt; 40 ? '(FLOOR 40)' : ''}}</span></div>
                  <div class="factor-item"><span class="factor-name">Timeliness</span><span class="factor-val">${{factors.timeliness}}</span></div>
                </div>
              ` : ''}}

              <div class="rejection-box">
                <div class="rejection-header">
                  <span>🛑</span>
                  <span>Editorial Rejection Rationale</span>
                </div>
                <div class="rejection-text">${{reason}}</div>
              </div>

              ${{rej.summary ? `
                <div style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.4;">
                  <strong>Candidate Snippet:</strong> ${{rej.summary}}
                </div>
              ` : ''}}

              ${{sources.length > 0 ? `
                <div class="sources-list">
                  <span style="font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; font-weight: 600;">Original Candidate Source:</span>
                  ${{sources.map(s => `<a href="${{s}}" target="_blank" rel="noopener noreferrer" class="source-link" style="color: #f87171;">🔗 ${{s}}</a>`).join('')}}
                </div>
              ` : ''}}
            </article>
          `;
        }}).join('');
      }}

      // 4. Seen Topics
      const seen = data.seen_topics || [];
      document.getElementById("count-seen").textContent = `${{seen.length}} SEEN`;
      const seenContainer = document.getElementById("stream-seen");
      if (seen.length === 0) {{
        seenContainer.innerHTML = `
          <div class="empty-state" style="grid-column: 1 / -1; padding: 1.5rem;">
            <span>Discovery memory is waiting for the next cycle.</span>
          </div>
        `;
      }} else {{
        seenContainer.innerHTML = seen.slice(0, 12).map(t => `
          <div class="animate-fade-up" style="background: rgba(0,0,0,0.25); border: 1px solid var(--border-subtle); border-radius: var(--radius-sm); padding: 0.65rem 0.85rem; display: flex; flex-direction: column; gap: 0.25rem;">
            <div style="font-size: 0.825rem; font-weight: 600; color: #ffffff; line-height: 1.3;">${{t.title}}</div>
            <div style="font-size: 0.7rem; color: var(--text-muted);">${{formatDate(t.discovered_at)}}</div>
            <a href="${{t.source_url}}" target="_blank" rel="noopener noreferrer" class="source-link" style="font-size: 0.7rem;">🔗 ${{t.source_url}}</a>
          </div>
        `).join('');
      }}
    }}

    async function triggerCycle(isDemo) {{
      const btn = isDemo ? document.getElementById("btn-trigger-demo") : document.getElementById("btn-trigger-rss");
      const origHtml = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = `<span class="spinner"></span> <span>Running Cycle...</span>`;

      showToast(`Triggering ${{isDemo ? 'demo fixtures' : 'live RSS'}} editorial cycle...`, "info");

      try {{
        const res = await fetch(`/api/agent/trigger-cycle?agentId=${{AGENT_ID}}&demo=${{isDemo}}`, {{
          method: 'POST'
        }});
        const data = await res.json();
        if (res.ok) {{
          const pubCount = data.summary?.published || 0;
          const rejCount = data.summary?.rejected || 0;
          showToast(`Cycle complete: ${{pubCount}} published, ${{rejCount}} rejected.`, "success");
          await fetchDashboardData();
        }} else {{
          showToast(`Cycle failed: ${{data.detail || 'Server error'}}`, "error");
        }}
      }} catch (err) {{
        showToast(`Trigger error: ${{err.message}}`, "error");
      }} finally {{
        btn.disabled = false;
        btn.innerHTML = origHtml;
      }}
    }}

    // Initial Load & Auto-Polling
    fetchDashboardData();
    setInterval(fetchDashboardData, 8000);
  </script>
</body>
</html>"""
