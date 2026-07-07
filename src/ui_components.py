# -*- coding: utf-8 -*-
"""
SurakshaAI v3.0 — UI Components & Design System
Centralized
Centralized styling, reusable components, and design tokens
"""

from typing import Dict, List, Optional, Any
from datetime import datetime
import streamlit as st

ZONE_LABELS_MAP = {
    'Zone_A': 'Battery-4',
    'Zone_B': 'Battery-5',
    'Zone_C': 'Battery-6',
    'Reactor_Area': 'Reactor Block',
    'Storage_Area': 'Storage Area',
    'Control_Room': 'Control Room'
}

def clean_html(html: str) -> str:
    """Helper to strip leading/trailing whitespace and collapse HTML into a single continuous line to prevent markdown parser code-block formatting"""
    return "".join(line.strip() for line in html.strip().split("\n"))

# ═══════════════════════════════════════════════════════════════════════════════
# DESIGN TOKENS
# ═══════════════════════════════════════════════════════════════════════════════

class Colors:
    """Semantic color palette"""
    # Backgrounds
    BG = "#050B16"
    BG2 = "#0B1526"
    BG3 = "#111827"
    BG4 = "#1a2740"
    GLASS = "rgba(17, 24, 39, 0.8)"

    # Borders
    BORDER = "#1e2d45"
    BORDER2 = "#243447"
    BORDER3 = "rgba(59, 130, 246, 0.2)"

    # Text
    TEXT = "#F8FAFC"
    TEXT2 = "#CBD5E1"
    MUTED = "#94A3B8"
    FAINT = "#64748B"

    # Semantic
    CYAN = "#00D4FF"
    BLUE = "#3B82F6"
    GREEN = "#22C55E"
    AMBER = "#F59E0B"
    RED = "#EF4444"
    ORANGE = "#F97316"
    PURPLE = "#A78BFA"

    # Severity mapping
    SEVERITY = {
        "CRITICAL": RED,
        "HIGH": ORANGE,
        "MEDIUM": AMBER,
        "LOW": GREEN,
        "SAFE": GREEN,
        "CLEAR": GREEN,
    }

    SEVERITY_BG = {
        "CRITICAL": "rgba(239, 68, 68, 0.08)",
        "HIGH": "rgba(249, 115, 22, 0.08)",
        "MEDIUM": "rgba(245, 158, 11, 0.08)",
        "LOW": "rgba(34, 197, 94, 0.08)",
        "SAFE": "rgba(34, 197, 94, 0.08)",
        "CLEAR": "rgba(34, 197, 94, 0.08)",
    }

    SEVERITY_BORDER = {
        "CRITICAL": "rgba(239, 68, 68, 0.4)",
        "HIGH": "rgba(249, 115, 22, 0.4)",
        "MEDIUM": "rgba(245, 158, 11, 0.4)",
        "LOW": "rgba(34, 197, 94, 0.3)",
        "SAFE": "rgba(34, 197, 94, 0.3)",
        "CLEAR": "rgba(34, 197, 94, 0.3)",
    }

    SEVERITY_ICON = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢",
        "SAFE": "🟢",
        "CLEAR": "🟢",
    }

    SEVERITY_LABEL_ICON = {
        "CRITICAL": "🚨",
        "HIGH": "⚠️",
        "MEDIUM": "⚠️",
        "LOW": "ℹ️",
        "SAFE": "✅",
        "CLEAR": "✅",
    }

    STATUS = {
        "ACTIVE": ("rgba(239, 68, 68, 0.15)", "#EF4444", "rgba(239, 68, 68, 0.3)"),
        "TRIGGERED": ("rgba(239, 68, 68, 0.15)", "#EF4444", "rgba(239, 68, 68, 0.3)"),
        "ACKNOWLEDGED": ("rgba(245, 158, 11, 0.15)", "#F59E0B", "rgba(245, 158, 11, 0.3)"),
        "RESOLVED": ("rgba(34, 197, 94, 0.15)", "#22C55E", "rgba(34, 197, 94, 0.3)"),
        "PENDING": ("rgba(59, 130, 246, 0.15)", "#3B82F6", "rgba(59, 130, 246, 0.3)"),
        "ESCALATED": ("rgba(239, 68, 68, 0.15)", "#EF4444", "rgba(239, 68, 68, 0.3)"),
    }


class Radius:
    SM = "8px"
    MD = "12px"
    LG = "16px"
    XL = "20px"
    FULL = "9999px"


class Shadow:
    SM = "0 2px 8px rgba(0,0,0,0.4)"
    MD = "0 4px 20px rgba(0,0,0,0.55)"
    LG = "0 8px 40px rgba(0,0,0,0.7)"


class Spacing:
    XS = "4px"
    SM = "8px"
    MD = "12px"
    LG = "16px"
    XL = "24px"


class Typography:
    FONT_PRIMARY = "'Outfit', -apple-system, BlinkMacSystemFont, sans-serif"
    FONT_MONO = "'JetBrains Mono', 'Fira Code', monospace"
    FONT_SYSTEM = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif"

    SIZE_XS = "9px"
    SIZE_SM = "10px"
    SIZE_BASE = "11px"
    SIZE_LG = "12px"
    SIZE_XL = "13px"
    SIZE_2XL = "15px"
    SIZE_3XL = "20px"
    SIZE_4XL = "34px"
    SIZE_5XL = "38px"


class ZIndex:
    NAVBAR = 999
    MODAL = 1000
    TOAST = 1100
    FOOTER = 9999


# ═══════════════════════════════════════════════════════════════════════════════
# GLOBAL CSS INJECTION
# ═══════════════════════════════════════════════════════════════════════════════

def get_global_css() -> str:
    """Returns the complete global CSS as a single string"""
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;600&family=Outfit:wght@400;500;600;700;800;900&display=swap');

/* CSS CUSTOM PROPERTIES (Design Tokens) */
:root {{
  --bg: {Colors.BG};
  --bg2: {Colors.BG2};
  --bg3: {Colors.BG3};
  --bg4: {Colors.BG4};
  --glass: {Colors.GLASS};
  --border: {Colors.BORDER};
  --border2: {Colors.BORDER2};
  --border3: {Colors.BORDER3};
  --shadow-sm: {Shadow.SM};
  --shadow-md: {Shadow.MD};
  --shadow-lg: {Shadow.LG};
  --text: {Colors.TEXT};
  --text2: {Colors.TEXT2};
  --muted: {Colors.MUTED};
  --faint: {Colors.FAINT};
  --cyan: {Colors.CYAN};
  --blue: {Colors.BLUE};
  --green: {Colors.GREEN};
  --amber: {Colors.AMBER};
  --red: {Colors.RED};
  --orange: {Colors.ORANGE};
  --purple: {Colors.PURPLE};
  --radius-sm: {Radius.SM};
  --radius: {Radius.MD};
  --radius-lg: {Radius.LG};
  --radius-xl: {Radius.XL};
  --font-primary: {Typography.FONT_PRIMARY};
  --font-mono: {Typography.FONT_MONO};
  --font-system: {Typography.FONT_SYSTEM};
}}

/* BASE RESET */
html, body, [class*="css"], .stApp {{
  font-family: var(--font-system) !important;
  color: var(--text) !important;
  background: var(--bg) !important;
  -webkit-font-smoothing: antialiased;
}}
.stApp {{ background: var(--bg) !important; }}
#MainMenu, footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ display: none !important; }}
.block-container {{ padding: 0 !important; max-width: 100% !important; }}
.stMarkdown {{ margin: 0 !important; }}
section[data-testid="stSidebar"] > div {{ padding-top: 0 !important; }}

/* SCROLLBAR */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-track {{ background: var(--bg); }}
::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: var(--blue); }}

/* LAYOUT UTILITIES */
.main-content {{
  padding: 0px 18px 110px 18px;
  margin-top: -45px !important;
}}
.block-container {{ padding-top: 0 !important; padding-bottom: 0 !important; margin-top: 0 !important; }}
section.main > div:first-child {{ padding-top: 0 !important; }}
div[data-testid="stVerticalBlock"] > div {{ margin-top: 0px !important; gap: 0.35rem !important; }}
div[data-testid="stHorizontalBlock"] {{ gap: 0.5rem !important; align-items: stretch !important; }}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] {{ display: flex !important; flex-direction: column !important; }}
div[data-testid="stHorizontalBlock"] > div[data-testid="column"] > div[data-testid="stVerticalBlock"] {{ display: flex !important; flex-direction: column !important; flex: 1 1 auto !important; }}
.element-container {{ margin-bottom: 0.2rem !important; }}

/* SIDEBAR */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, var(--bg2) 0%, #0A1220 100%) !important;
  border-right: 1px solid var(--border2) !important;
}}
[data-testid="stSidebar"] .block-container {{ padding: 12px !important; }}

/* GLASS CARD BASE */
.glass-card {{
  background: linear-gradient(145deg, rgba(17,24,39,0.95) 0%, rgba(11,21,38,0.9) 100%);
  border: 1px solid var(--border2);
  border-top: 1px solid rgba(255,255,255,0.08);
  border-radius: var(--radius-lg);
  padding: 18px 20px;
  box-shadow: var(--shadow-md), inset 0 1px 0 rgba(255,255,255,0.05);
  transition: all 0.25s ease;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}}
.glass-card::before {{
  content: '';
  position: absolute; top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(59,130,246,0.3), transparent);
}}
.glass-card:hover {{
  transform: translateY(-3px);
  box-shadow: var(--shadow-lg), inset 0 1px 0 rgba(255,255,255,0.07);
  border-color: var(--border3);
}}
.glass-card-critical {{
  border-color: rgba(239,68,68,0.4) !important;
  animation: critBorder 1.8s ease-in-out infinite;
}}
@keyframes critBorder {{
  0%,100% {{ box-shadow: 0 0 8px rgba(239,68,68,0.2), var(--shadow-md); }}
  50%     {{ box-shadow: 0 0 24px rgba(239,68,68,0.5), var(--shadow-md); }}
}}

/* TYPOGRAPHY UTILITIES */
.metric-label {{
  color: var(--muted);
  font-size: {Typography.SIZE_XS};
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
}}
.metric-value {{
  font-size: {Typography.SIZE_4XL};
  font-weight: 800;
  letter-spacing: -1.5px;
  margin: 2px 0;
  line-height: 1;
}}
.metric-sub {{
  color: var(--muted);
  font-size: {Typography.SIZE_BASE};
  font-weight: 500;
  margin-top: 4px;
}}
.section-header {{
  font-size: {Typography.SIZE_BASE};
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--muted);
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}}

/* STATUS INDICATORS */
.dot {{ width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex-shrink: 0; }}
.dot-critical {{ background: #EF4444; box-shadow: 0 0 8px #EF4444; animation: dotPulse 1.2s ease infinite alternate; }}
.dot-high     {{ background: #F59E0B; box-shadow: 0 0 6px #F59E0B; animation: dotPulse 1.8s ease infinite alternate; }}
.dot-medium   {{ background: #EAB308; box-shadow: 0 0 5px #EAB308; }}
.dot-safe, .dot-low {{ background: #22C55E; box-shadow: 0 0 5px #22C55E; }}
@keyframes dotPulse {{ 0% {{ transform: scale(0.8); opacity: 0.7; }} 100% {{ transform: scale(1.4); opacity: 1; }} }}

/* Severity text colors */
.risk-critical {{ color: #EF4444 !important; font-weight: 800; animation: critText 1.5s ease-in-out infinite alternate; }}
.risk-high     {{ color: #F59E0B !important; font-weight: 700; }}
.risk-medium   {{ color: #EAB308 !important; font-weight: 700; }}
.risk-safe, .risk-low {{ color: #22C55E !important; font-weight: 700; }}
@keyframes critText {{
  0%   {{ text-shadow: 0 0 8px rgba(239,68,68,0.3); }}
  100% {{ text-shadow: 0 0 22px rgba(239,68,68,0.8); }}
}}

/* BANNERS */
.status-banner {{
  border-radius: var(--radius);
  padding: 12px 20px;
  text-align: center;
  font-size: {Typography.SIZE_LG};
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  margin: 0 0 12px 0;
  border: 1px solid;
  backdrop-filter: blur(8px);
}}
.emergency-banner {{
  background: linear-gradient(135deg, #2D0A0A 0%, #4A0E0E 50%, #2D0A0A 100%);
  border: 1.5px solid rgba(239,68,68,0.6);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  margin: 4px 0 14px 0;
  animation: emergPulse 2.5s ease-in-out infinite;
  backdrop-filter: blur(12px);
}}
@keyframes emergPulse {{
  0%,100% {{ box-shadow: 0 0 15px rgba(239,68,68,0.3), inset 0 0 30px rgba(239,68,68,0.03); }}
  50%     {{ box-shadow: 0 0 40px rgba(239,68,68,0.6), inset 0 0 50px rgba(239,68,68,0.07); }}
}}

/* ANIMATIONS */
@keyframes pulse-red   {{ 0%,100%{{opacity:1;}} 50%{{opacity:0.35;}} }}
@keyframes pulse-green {{ 0%,100%{{opacity:1;}} 50%{{opacity:0.5;}} }}
@keyframes pulse-blue  {{ 0%,100%{{opacity:1;}} 50%{{opacity:0.4;}} }}
@keyframes fadeIn      {{ from{{opacity:0;transform:translateY(6px);}} to{{opacity:1;transform:translateY(0);}} }}
.pulse-red   {{ animation: pulse-red 1.2s ease infinite; }}
.pulse-green {{ animation: pulse-green 2s ease infinite; }}
.pulse-blue  {{ animation: pulse-blue 2s ease infinite; }}
.fade-in     {{ animation: fadeIn 0.4s ease both; }}
.stApp       {{ animation: fadeIn 0.4s ease; }}

/* ALERT ROWS */
.alert-row-crit {{ border-left: 3px solid #EF4444; background: rgba(239,68,68,0.06); border-radius: 0 8px 8px 0; }}
.alert-row-high {{ border-left: 3px solid #F97316; background: rgba(249,115,22,0.06); border-radius: 0 8px 8px 0; }}
.alert-row-med  {{ border-left: 3px solid #F59E0B; background: rgba(245,158,11,0.06); border-radius: 0 8px 8px 0; }}
.alert-row-low  {{ border-left: 3px solid #22C55E; background: rgba(34,197,94,0.06); border-radius: 0 8px 8px 0; }}

/* NOTIFICATION CHANNEL CARDS */
.channel-card-active {{ background: rgba(20,83,45,0.4) !important; border-color: #22C55E !important; }}
.channel-card-alert  {{ background: rgba(69,10,10,0.5) !important; border-color: #EF4444 !important; }}

/* SIM CONTROLS BAR */
.sim-bar {{
  background: linear-gradient(90deg, var(--bg2) 0%, #0A1626 100%);
  border-top: 1px solid var(--border2);
  padding: 7px 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-system);
  font-size: {Typography.SIZE_BASE};
  box-shadow: 0 -4px 20px rgba(0,0,0,0.5);
}}

/* BUTTONS */
div.stButton > button[kind="primary"] {{
  background: linear-gradient(135deg, #B91C1C 0%, #DC2626 100%) !important;
  color: #fff !important;
  font-weight: 700 !important;
  font-size: {Typography.SIZE_BASE} !important;
  border: none !important;
  border-radius: var(--radius-sm) !important;
  padding: 8px 16px !important;
  text-transform: uppercase !important;
  letter-spacing: 0.5px !important;
  animation: btnGlow 2.5s ease-in-out infinite;
  transition: all 0.2s ease !important;
  box-shadow: 0 4px 14px rgba(220,38,38,0.4) !important;
}}
div.stButton > button[kind="primary"]:hover {{
  transform: translateY(-1px) !important;
  box-shadow: 0 6px 24px rgba(239,68,68,0.65) !important;
}}
@keyframes btnGlow {{
  0%,100% {{ box-shadow: 0 4px 14px rgba(220,38,38,0.4); }}
  50%     {{ box-shadow: 0 4px 24px rgba(239,68,68,0.75); }}
}}
div.stButton > button[kind="secondary"] {{
  border-radius: var(--radius-sm) !important;
  font-weight: 600 !important;
  font-size: {Typography.SIZE_BASE} !important;
  background: rgba(255,255,255,0.05) !important;
  color: var(--text2) !important;
  border: 1px solid var(--border2) !important;
  transition: all 0.2s ease !important;
}}
div.stButton > button[kind="secondary"]:hover {{
  background: rgba(59,130,246,0.1) !important;
  border-color: rgba(59,130,246,0.4) !important;
  color: #fff !important;
  transform: translateY(-1px) !important;
}}

/* DOWNLOAD BUTTON */
[data-testid="stDownloadButton"] > button {{
  background: linear-gradient(135deg, rgba(30,42,65,0.9), rgba(20,30,50,0.9)) !important;
  border: 1px solid var(--border2) !important;
  color: var(--text) !important;
  border-radius: var(--radius-sm) !important;
  font-size: {Typography.SIZE_BASE} !important;
  font-weight: 600 !important;
  width: 100% !important;
  transition: all 0.2s ease !important;
  box-shadow: var(--shadow-sm) !important;
}}
[data-testid="stDownloadButton"] > button:hover {{
  border-color: var(--blue) !important;
  background: rgba(59,130,246,0.1) !important;
}}

/* INPUTS / SELECTS */
div[data-testid="stSelectbox"] > div > div {{
  background: var(--bg3) !important;
  border: 1px solid var(--border2) !important;
  border-radius: var(--radius-sm) !important;
  color: var(--text) !important;
  font-size: {Typography.SIZE_BASE} !important;
}}
div[data-testid="stSelectbox"] svg {{ color: var(--muted) !important; }}

/* TOGGLE */
div[data-testid="stToggle"] > label {{ font-size: {Typography.SIZE_BASE} !important; color: var(--text2) !important; }}

/* FILTER PILLS */
div[data-testid="stRadio"] > div {{
  display: flex; flex-direction: row; gap: 5px; flex-wrap: nowrap;
}}
div[data-testid="stRadio"] label {{
  background: rgba(255,255,255,0.04);
  border: 1px solid var(--border2);
  border-radius: 20px; padding: 3px 12px;
  font-size: {Typography.SIZE_XS}; font-weight: 600; cursor: pointer;
  transition: all 0.2s ease;
  color: var(--muted);
}}
div[data-testid="stRadio"] label:has(input:checked) {{
  background: rgba(59,130,246,0.12);
  border-color: var(--blue);
  color: #60A5FA;
}}

/* EXPANDER */
div[data-testid="stExpander"] {{
  border: 1px solid var(--border2) !important;
  border-radius: var(--radius) !important;
  background: var(--bg3) !important;
}}
div[data-testid="stExpander"] summary {{
  font-size: {Typography.SIZE_BASE} !important;
  font-weight: 600 !important;
  color: var(--text2) !important;
}}

/* CHECKBOXES */
div[data-testid="stCheckbox"] label {{
  font-size: {Typography.SIZE_BASE} !important;
  color: var(--text2) !important;
}}

/* TABS */
div[data-testid="stTabs"] button[role="tab"] {{
  font-size: {Typography.SIZE_BASE} !important;
  font-weight: 600 !important;
  color: var(--muted) !important;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0 !important;
}}
div[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
  color: var(--blue) !important;
  border-bottom-color: var(--blue) !important;
}}

/* IFRAME (Heatmap) */
iframe {{
  border-radius: var(--radius) !important;
  border: 1px solid var(--border2) !important;
  background: var(--bg3) !important;
}}

/* IMAGE (CCTV) */
div[data-testid="stImage"] {{
  margin: 0 !important;
  padding: 0 !important;
  line-height: 0 !important;
}}
div[data-testid="stImage"] img {{
  border: none !important;
  border-left: 1px solid #1e3a5f !important;
  border-right: 1px solid #1e3a5f !important;
  border-radius: 0 !important;
  display: block !important;
  width: 100% !important;
  margin: 0 !important;
}}

/* VIDEO (disabled controls) */
video::-webkit-media-controls {{ display: none !important; }}
video {{ pointer-events: none !important; }}

/* PLOTLY CHART */
div[data-testid="stPlotlyChart"] {{
  border-radius: var(--radius) !important;
}}

/* TOAST */
div[data-testid="stToast"] {{
  background: var(--bg3) !important;
  border: 1px solid var(--border2) !important;
  border-radius: var(--radius) !important;
  color: var(--text) !important;
}}

/* ── SURAKSHA NAVBAR ── */
.suraksha-navbar {{
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: {ZIndex.NAVBAR};
  height: 52px;
  background: linear-gradient(90deg,
    rgba(5,11,22,0.97) 0%,
    rgba(11,21,38,0.96) 50%,
    rgba(5,11,22,0.97) 100%);
  backdrop-filter: blur(20px) saturate(180%);
  -webkit-backdrop-filter: blur(20px) saturate(180%);
  border-bottom: 1px solid rgba(59,130,246,0.18);
  box-shadow: 0 2px 24px rgba(0,0,0,0.55), 0 1px 0 rgba(255,255,255,0.04) inset;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  font-family: var(--font-primary);
}}
.suraksha-navbar::after {{
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg,
    transparent 0%, rgba(59,130,246,0.5) 30%,
    rgba(99,102,241,0.4) 70%, transparent 100%);
}}

/* Brand section */
.suraksha-navbar-brand {{
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
}}
.suraksha-navbar-logo {{
  width: 30px; height: 30px;
  background: linear-gradient(135deg,#1d4ed8 0%,#3b82f6 50%,#60a5fa 100%);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 15px;
  box-shadow: 0 0 14px rgba(59,130,246,0.45);
  flex-shrink: 0;
}}
.suraksha-navbar-title {{
  font-size: 15px;
  font-weight: 800;
  letter-spacing: 0.4px;
  background: linear-gradient(135deg,#e2e8f0 0%,#94a3b8 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  white-space: nowrap;
}}
.suraksha-navbar-subtitle {{
  font-size: 9px;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  white-space: nowrap;
}}

/* Nav links */
.suraksha-navbar-links {{
  display: flex;
  align-items: center;
  gap: 4px;
}}
.suraksha-navbar-link {{
  position: relative;
  color: #64748b;
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.3px;
  padding: 6px 13px;
  border-radius: 6px;
  text-decoration: none;
  text-transform: uppercase;
  letter-spacing: 0.6px;
  transition: color 0.2s ease, background 0.2s ease;
  cursor: default;
}}
.suraksha-navbar-link:hover {{
  color: #e2e8f0;
  background: rgba(255,255,255,0.05);
}}
.suraksha-navbar-link.active {{
  color: #60a5fa;
  background: rgba(59,130,246,0.1);
}}
.suraksha-navbar-link.active::after {{
  content: '';
  position: absolute;
  bottom: -1px; left: 16px; right: 16px;
  height: 2px;
  background: linear-gradient(90deg,transparent,#3b82f6,transparent);
  border-radius: 2px;
}}
.suraksha-navbar-divider {{
  width: 1px; height: 18px;
  background: rgba(255,255,255,0.08);
  margin: 0 6px;
}}

/* Status pill */
.suraksha-navbar-status {{
  display: flex;
  align-items: center;
  gap: 8px;
}}
.suraksha-status-pill {{
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 20px;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  border: 1px solid;
  white-space: nowrap;
}}
.suraksha-status-pill.secure {{
  background: rgba(34,197,94,0.08);
  border-color: rgba(34,197,94,0.3);
  color: #22c55e;
}}
.suraksha-status-pill.elevated {{
  background: rgba(245,158,11,0.08);
  border-color: rgba(245,158,11,0.3);
  color: #f59e0b;
}}
.suraksha-status-pill.critical {{
  background: rgba(239,68,68,0.1);
  border-color: rgba(239,68,68,0.4);
  color: #ef4444;
  animation: critBorder 1.8s ease-in-out infinite;
}}
.suraksha-status-dot {{
  width: 7px; height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}}
.suraksha-status-dot.secure {{
  background: #22c55e;
  box-shadow: 0 0 6px #22c55e;
  animation: safePulse 2.5s ease-in-out infinite;
}}
.suraksha-status-dot.elevated {{
  background: #f59e0b;
  box-shadow: 0 0 6px #f59e0b;
  animation: safePulse 2s ease-in-out infinite;
}}
.suraksha-status-dot.critical {{
  background: #ef4444;
  box-shadow: 0 0 8px #ef4444;
  animation: critPulse 0.9s ease-in-out infinite;
}}
@keyframes safePulse {{
  0%,100% {{ opacity:1; transform:scale(1); }}
  50%       {{ opacity:0.6; transform:scale(0.85); }}
}}
@keyframes critPulse {{
  0%,100% {{ opacity:1; box-shadow:0 0 8px #ef4444; }}
  50%      {{ opacity:0.7; box-shadow:0 0 16px #ef4444; }}
}}

/* Time badge */
.suraksha-navbar-time {{
  font-family: var(--font-mono);
  font-size: 10.5px;
  color: #475569;
  font-weight: 600;
  letter-spacing: 0.5px;
  background: rgba(255,255,255,0.03);
  padding: 3px 8px;
  border-radius: 5px;
  border: 1px solid rgba(255,255,255,0.05);
}}

/* Push page content below navbar */
.main-content,
section.main > div:first-child,
.block-container {{
  padding-top: 62px !important;
}}

/* AI Explainability Redesign Animations */
@keyframes slideInStep {{
  from {{ opacity: 0; transform: translateY(6px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
.timeline-step {{
  animation: slideInStep 0.4s ease-out forwards;
}}

@keyframes rulePassFlash {{
  0% {{ background-color: rgba(34, 197, 94, 0.15); }}
  100% {{ background-color: rgba(34, 197, 94, 0.02); }}
}}
.rule-pass-row {{
  animation: rulePassFlash 1s ease-out forwards;
}}

@keyframes ruleFailPulse {{
  0%, 100% {{ border-color: rgba(239, 68, 68, 0.15); box-shadow: inset 0 0 3px rgba(239, 68, 68, 0.05); }}
  50% {{ border-color: rgba(239, 68, 68, 0.4); box-shadow: inset 0 0 8px rgba(239, 68, 68, 0.15); }}
}}
.rule-fail-row {{
  animation: ruleFailPulse 1.8s infinite ease-in-out;
  background-color: rgba(239, 68, 68, 0.03) !important;
}}

@keyframes scoreGrow {{
  from {{ width: 0%; }}
  to {{ width: 100%; }}
}}
.score-bar-fill {{
  animation: scoreGrow 0.8s cubic-bezier(0.4, 0, 0.2, 1) forwards;
}}

@keyframes notifCheck {{
  from {{ transform: scale(0.6); opacity: 0; }}
  to {{ transform: scale(1); opacity: 1; }}
}}
.notif-checked {{
  display: inline-block;
  animation: notifCheck 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275) forwards;
}}

.detections-feed-container {{
  max-height: 110px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 9.5px;
  border: 1px solid var(--border2);
  border-radius: 8px;
  background: rgba(10, 22, 40, 0.5) !important;
  padding: 6px 10px;
}}
.detection-entry {{
  padding: 3px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.03);
  display: flex;
  justify-content: space-between;
  align-items: center;
}}
.detection-entry:last-child {{
  border-bottom: none;
}}
</style>
"""


def inject_global_css():
    """Inject global CSS into the Streamlit app"""
    st.markdown(get_global_css(), unsafe_allow_html=True)


def render_navbar(risk_level: str = "LOW", active_tab: str = "dashboard") -> None:
    """
    Render the SurakshaAI glassmorphism top navbar using responsive columns & native buttons
    to support seamless, refresh-free page state transitions.
    """
    rl = (risk_level or "LOW").upper()
    if rl == "CRITICAL":
        pill_cls = "critical"
        pill_label = "⚡ CRITICAL ALERT"
    elif rl in ("HIGH",):
        pill_cls = "elevated"
        pill_label = "▲ ELEVATED RISK"
    elif rl in ("MEDIUM",):
        pill_cls = "elevated"
        pill_label = "◆ MEDIUM RISK"
    else:
        pill_cls = "secure"
        pill_label = "● SYSTEM SECURE"

    now_str = datetime.now().strftime("%H:%M:%S")

    # Inject navbar overrides for buttons
    st.markdown("""
    <style>
    /* Styling Streamlit buttons to blend into glassmorphic navbar style */
    div.stButton > button {
        background: transparent !important;
        border: none !important;
        color: #6b7d94 !important;
        font-family: 'Outfit', sans-serif !important;
        font-size: 11.5px !important;
        font-weight: 600 !important;
        text-transform: uppercase !important;
        letter-spacing: 0.5px !important;
        padding: 6px 12px !important;
        transition: all 0.2s ease !important;
    }
    div.stButton > button:hover {
        color: #00d4ff !important;
        background: rgba(0, 212, 255, 0.08) !important;
        border-radius: 6px !important;
    }
    div.stButton > button[kind="primary"], div.stButton > button[class*="primary"] {
        color: #fff !important;
        background: rgba(0, 212, 255, 0.15) !important;
        border: 1px solid rgba(0, 212, 255, 0.3) !important;
        border-radius: 6px !important;
        box-shadow: 0 0 10px rgba(0, 212, 255, 0.1) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    col_brand, col_nav, col_status = st.columns([1.6, 3.8, 2.6])
    
    with col_brand:
        st.markdown(f"""
        <div class="suraksha-navbar-brand" style="display:flex; align-items:center; gap:8px; margin-top:4px;">
          <div class="suraksha-navbar-logo" style="font-size:22px;">🛡️</div>
          <div>
            <div class="suraksha-navbar-title" style="font-weight:bold; font-size:14px; color:#fff; font-family:'Outfit',sans-serif; line-height:1.2;">SurakshaAI</div>
            <div class="suraksha-navbar-subtitle" style="font-size:9.5px; color:#6b7d94; font-family:'Outfit',sans-serif; line-height:1.0;">Industrial Safety Platform</div>
          </div>
        </div>
        """, unsafe_allow_html=True)
        
    with col_nav:
        col_t1, col_t2, col_t3, col_t4 = st.columns(4)
        if col_t1.button("🖥  Live Monitor", key="nav_dashboard", width='stretch', type="primary" if active_tab == "dashboard" else "secondary"):
            st.session_state.active_tab = "dashboard"
            st.query_params["tab"] = "dashboard"
            st.rerun()
        if col_t2.button("📊 Analytics", key="nav_analytics", width='stretch', type="primary" if active_tab == "analytics" else "secondary"):
            st.session_state.active_tab = "analytics"
            st.query_params["tab"] = "analytics"
            st.rerun()
        if col_t3.button("🗺  Zone Map", key="nav_zones", width='stretch', type="primary" if active_tab == "zones" else "secondary"):
            st.session_state.active_tab = "zones"
            st.query_params["tab"] = "zones"
            st.rerun()
        if col_t4.button("⚙  Settings", key="nav_settings", width='stretch', type="primary" if active_tab == "settings" else "secondary"):
            st.session_state.active_tab = "settings"
            st.query_params["tab"] = "settings"
            st.rerun()
            
    with col_status:
        st.markdown(f"""
        <div class="suraksha-navbar-status" style="display:flex; align-items:center; gap:10px; justify-content:flex-end; width:100%; margin-top:4px; font-family:'Outfit',sans-serif;">
          <a href="?show_modal=1" target="_top" style="text-decoration:none;">
            <span style="background:rgba(0,212,255,0.12); border:1px solid rgba(0,212,255,0.3); border-radius:6px; color:#00d4ff; padding:5px 12px; font-size:10px; font-weight:bold; cursor:pointer;">🧠 AI Console</span>
          </a>
          <span class="suraksha-navbar-time" id="suraksha-clock" style="color:#6b7d94; font-family:monospace; font-size:11.5px; margin-top:2px;">{now_str}</span>
          <div class="suraksha-navbar-divider" style="width:1px; height:12px; background:rgba(255,255,255,0.1); margin:0 2px;"></div>
          <div class="suraksha-status-pill {pill_cls}" style="margin:0;">
            <div class="suraksha-status-dot {pill_cls}"></div>
            {pill_label}
          </div>
        </div>
        """, unsafe_allow_html=True)
        
        # Lightweight client-side clock script
        st.markdown("""
        <script>
        (function(){
          function tick(){
            var el=document.getElementById("suraksha-clock");
            if(el){var n=new Date();
              el.textContent=[n.getHours(),n.getMinutes(),n.getSeconds()]
                .map(function(v){return String(v).padStart(2,"0");}).join(":");
            }
            setTimeout(tick,1000);
          }
          tick();
        })();
        </script>
        """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# REUSABLE COMPONENT FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def render_metric_card(
    label: str,
    value: str,
    subtext: str = "",
    icon: str = "",
    border_color: str = "#3B82F6",
    value_color: str = "#60A5FA",
    sparkline_svg: str = "",
    height: str = "162px",
    critical: bool = False,
    extra_html: str = "",
) -> str:
    """Render a metric KPI card with consistent styling"""
    card_class = "glass-card glass-card-critical" if critical else "glass-card"
    border_style = f"border-top: 2px solid {border_color};"

    icon_html = f'<span style="font-size: 14px; margin-right: 6px;">{icon}</span>' if icon else ""
    
    clean_sparkline = clean_html(sparkline_svg) if sparkline_svg else ""
    clean_extra = clean_html(extra_html) if extra_html else ""

    return clean_html(f"""
    <div class="{card_class}" style="{border_style} height: {height};">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;">
        <div class="metric-label" style="color:#94A3B8;">{icon_html}{label}</div>
        {clean_sparkline}
      </div>
      <div class="metric-value" style="color:{value_color};">{value}</div>
      {f'<div style="font-size:11px;color:#F8FAFC;font-weight:600;margin-top:2px;">{subtext}</div>' if subtext else ''}
      <div class="metric-sub" style="margin-top:4px;">{clean_extra if clean_extra else 'Overall plant safety state'}</div>
    </div>
    """)


def render_alert_card(
    alert: Any,
    sim_start_time: Optional[datetime] = None,
) -> str:
    """
    Render an alert card using centralized styling and semantic tokens.
    Supports both old dashboard alerts and new SafetyAlert/Incident architecture.
    """
    # 1. Extract severity / risk level
    severity_name = "LOW"
    if hasattr(alert, "risk_level"):
        severity_name = alert.risk_level
    elif hasattr(alert, "severity"):
        severity_name = getattr(alert.severity, "name", str(alert.severity))
    elif isinstance(alert, dict) and "severity" in alert:
        severity_name = alert["severity"]
    elif isinstance(alert, dict) and "risk_level" in alert:
        severity_name = alert["risk_level"]
    
    severity_name = severity_name.upper()

    # Get style tokens
    color = Colors.SEVERITY.get(severity_name, Colors.BLUE)
    bg = Colors.SEVERITY_BG.get(severity_name, "rgba(59, 130, 246, 0.08)")
    border_color = Colors.SEVERITY_BORDER.get(severity_name, "rgba(59, 130, 246, 0.4)")
    icon = Colors.SEVERITY_ICON.get(severity_name, "🔵")

    # 2. Extract zone
    zone = ""
    if hasattr(alert, "zone"):
        zone = alert.zone
    elif isinstance(alert, dict) and "zone" in alert:
        zone = alert["zone"]

    zone_lbl = ZONE_LABELS_MAP.get(zone, zone)

    # 3. Extract message
    message = ""
    if hasattr(alert, "message"):
        message = alert.message
    elif isinstance(alert, dict) and "message" in alert:
        message = alert["message"]

    # 4. Extract time/duration
    time_str = ""
    if hasattr(alert, "duration"):
        dur = int(alert.duration)
        time_str = f"{dur // 60:02d}:{dur % 60:02d}s"
    elif hasattr(alert, "timestamp"):
        now = datetime.now()
        if sim_start_time:
            delta_s = max(0, int((now - sim_start_time).total_seconds()))
            if delta_s < 60:
                time_str = f'{delta_s} sec ago'
            else:
                time_str = f'{delta_s // 60} min ago'
        else:
            time_str = alert.timestamp.strftime('%H:%M:%S')
    elif isinstance(alert, dict) and "timestamp" in alert:
        time_str = str(alert["timestamp"])

    # 5. Extract status / acknowledgment
    status_label = "ACTIVE"
    is_ack = False
    alert_id = None

    if hasattr(alert, "status"):
        status_val = getattr(alert.status, "value", str(alert.status))
        status_label = status_val.upper()
        is_ack = status_label in ("ACKNOWLEDGED", "ACK")
    elif isinstance(alert, dict) and "status" in alert:
        status_label = str(alert["status"]).upper()
        is_ack = status_label in ("ACKNOWLEDGED", "ACK")
    
    if hasattr(alert, "alert_id"):
        alert_id = alert.alert_id
    elif isinstance(alert, dict) and "alert_id" in alert:
        alert_id = alert["alert_id"]
    elif isinstance(alert, dict) and "id" in alert:
        alert_id = alert["id"]

    # Status pill styles
    status_tuple = Colors.STATUS.get(status_label, ("rgba(239, 68, 68, 0.15)", "#EF4444", "rgba(239, 68, 68, 0.3)"))
    status_bg, status_color, status_border = status_tuple

    # Acknowledge button html
    if is_ack:
        ack_btn = f"""<span style="background: rgba(34,197,94,0.15); color: #22c55e; border: 1px solid rgba(34,197,94,0.3); border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 800; text-transform: uppercase;">✔ ACKNOWLEDGED</span>"""
    elif alert_id:
        ack_btn = f"""<a href="?ack_alert={alert_id}" target="_self" style="text-decoration: none;"><span style="background: {color}; color: #fff; border-radius: 4px; padding: 2px 8px; font-size: 10px; font-weight: 800; cursor: pointer; text-transform: uppercase;">ACKNOWLEDGE</span></a>"""
    else:
        ack_btn = f"""<span style="background: rgba(255,255,255,0.08); color: #64748b; border: 1px solid rgba(255,255,255,0.1); border-radius: 4px; padding: 2px 8px; font-size: 10px;">Acknowledge</span>"""

    # Extra details (sensor data, score etc.) if available
    extra_details = []
    if hasattr(alert, "risk_score"):
        extra_details.append(f"Score: {int(alert.risk_score)}/20")
    
    sensor_parts = []
    if hasattr(alert, "sensor_data") and alert.sensor_data:
        sd = alert.sensor_data
        def gsv(key):
            if key in sd: return float(sd[key])
            for k, v in sd.items():
                if k.endswith(key): return float(v)
            return None
        
        gas = gsv('gas_ppm')
        temp = gsv('temperature_c')
        workers = gsv('worker_count')
        
        if gas is not None:
            sensor_parts.append(f"Gas: {gas:.1f}ppm")
        if temp is not None:
            sensor_parts.append(f"Temp: {temp:.1f}°C")
        if workers is not None:
            sensor_parts.append(f"Workers: {int(workers)}")

    if sensor_parts:
        extra_details.append("  |  ".join(sensor_parts))

    extra_str = " | ".join(extra_details) if extra_details else ""

    # Check for critical pulse class
    card_class = "glass-card glass-card-critical" if severity_name == "CRITICAL" else "glass-card"

    html = f"""
    <div class="{card_class}" style="background: {bg}; border-left: 4px solid {color}; border-top: 1px solid {border_color}; border-right: 1px solid {border_color}; border-bottom: 1px solid {border_color}; border-radius: var(--radius); padding: 12px 14px; margin-bottom: 8px; font-family: var(--font-primary);">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
        <span style="display: flex; align-items: center; gap: 4px; font-weight: 800; color: {color}; font-size: {Typography.SIZE_BASE}; letter-spacing: 0.5px; text-transform: uppercase; {'animation: dotPulse 1.2s ease infinite alternate;' if severity_name == 'CRITICAL' else ''}">
          {icon} {severity_name}
        </span>
        <span style="background: {status_bg}; color: {status_color}; border: 1px solid {status_border}; border-radius: 4px; padding: 1px 6px; font-size: {Typography.SIZE_XS}; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">
          {status_label}
        </span>
      </div>
      <div style="color: var(--text); font-size: {Typography.SIZE_LG}; font-weight: 700; margin-bottom: 2px;">{message}</div>
      <div style="display: flex; justify-content: space-between; align-items: center; color: var(--muted); font-size: {Typography.SIZE_BASE}; margin-top: 6px;">
        <span>Zone: <b style="color: var(--text2);">{zone_lbl}</b>{f' | {time_str}' if time_str else ''}{f' | {extra_str}' if extra_str else ''}</span>
        {ack_btn}
      </div>
    </div>
    """
    return clean_html(html)


def render_nominal_card(
    title: str = "All Zones Nominal",
    message: str = "All monitored zones are operating normally.",
) -> str:
    """Render a clean nominal/safe state card"""
    return clean_html(f"""
    <div class="glass-card" style="background: rgba(34, 197, 94, 0.04); border-color: rgba(34, 197, 94, 0.2); padding: 12px 14px; text-align: center;">
      <div style="font-size: {Typography.SIZE_3XL}; margin-bottom: 4px;">🟢</div>
      <div style="color: {Colors.GREEN}; font-size: {Typography.SIZE_LG}; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">{title}</div>
      <div style="color: var(--muted); font-size: {Typography.SIZE_BASE}; margin-top: 3px; line-height: 1.4;">{message}</div>
    </div>
    """)


def render_zone_status_row(
    zone_label: str,
    lvl: str,
    score: float,
    gas: float,
) -> str:
    """Render a zone status row item"""
    lvl_upper = lvl.upper()
    is_crit = (lvl_upper == 'CRITICAL')
    is_high = (lvl_upper == 'HIGH')
    hb_pts = "0,8 3,8 5,2 7,14 9,2 11,14 13,8 20,8" if is_crit else "0,8 4,8 6,5 8,11 10,8 14,8 16,6 20,8"
    hb_color = Colors.RED if is_crit else (Colors.ORANGE if is_high else Colors.GREEN)
    row_bg = "rgba(239,68,68,0.05)" if is_crit else ("rgba(249,115,22,0.03)" if is_high else "rgba(255,255,255,0.015)")
    
    c = Colors.SEVERITY.get(lvl_upper, Colors.BLUE)
    badge_bg = Colors.SEVERITY_BG.get(lvl_upper, "rgba(59, 130, 246, 0.08)")
    dot_dot = Colors.SEVERITY_ICON.get(lvl_upper, "🔵")
    
    return clean_html(f"""
    <div style="display:flex;align-items:center;justify-content:space-between;
                padding:5px 8px;background:{row_bg};border-radius:6px;margin-bottom:2px;
                border:1px solid rgba(255,255,255,0.04);font-family:var(--font-primary);">
      <div style="display:flex;align-items:center;gap:6px;flex:1;min-width:0;">
        <span style="font-size:9px;flex-shrink:0;">{dot_dot}</span>
        <span style="color:#f1f5f9;font-size:10.5px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{zone_label}</span>
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
        <span style="background:{badge_bg};color:{c};font-size:7.5px;font-weight:800;
                     padding:1px 5px;border-radius:3px;letter-spacing:0.4px;border:1px solid {c}30;
                     text-transform:uppercase;">{lvl}</span>
        <span style="color:#64748b;font-size:9px;font-family:var(--font-mono);min-width:30px;text-align:right;">{score:.0f}/20</span>
        <span style="color:#94a3b8;font-size:9px;font-family:var(--font-mono);min-width:40px;text-align:right;">{gas:.1f}p</span>
        <svg width="20" height="12" viewBox="0 0 22 16" style="flex-shrink:0;opacity:0.9;">
          <polyline points="{hb_pts}" fill="none" stroke="{hb_color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </div>
    </div>
    """)


def render_notification_channel(
    name: str,
    status: str,
    status_color: str,
    detail: str,
    active: bool = False,
    progress_pct: int = 100
) -> str:
    """Render a notification gateway card"""
    card_bg = 'rgba(20,83,45,0.35)' if active else 'rgba(255,255,255,0.015)'
    chk_mark = "✓ " if active else ""
    return clean_html(f"""
    <div style="background:{card_bg}; border:1px solid {status_color}; border-radius:8px; padding:11px 13px; margin-bottom:8px; font-family:var(--font-primary);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
            <span style="font-size:11px; font-weight:700; color:#fff;">{name}</span>
            <span style="color:{status_color}; font-size:10px; font-weight:800; text-transform:uppercase;">{chk_mark}{status}</span>
        </div>
        <div style="width:100%; height:3px; background:rgba(255,255,255,0.06); border-radius:2px; margin-bottom:4px;">
            <div style="width:{progress_pct}%; height:100%; background:{status_color}; transition:width 0.5s;"></div>
        </div>
        <span style="color:#94a3b8; font-size:10px;">{detail}</span>
    </div>
    """)


def render_gauge_svg(
    value: float,
    min_val: float,
    max_val: float,
    title: str,
    color_theme: str,
    warning_val: float,
    critical_val: float,
    unit: str = ""
) -> str:
    """Render an SVG gauge component"""
    import math
    percentage = (value - min_val) / (max_val - min_val)
    percentage = max(0.0, min(1.0, percentage))
    angle = math.pi - (percentage * math.pi)
    
    nx = 50 + 26 * math.cos(angle)
    ny = 42 - 26 * math.sin(angle)
    
    bar_color = color_theme
    if value >= critical_val:
        bar_color = Colors.RED
    elif value >= warning_val:
        bar_color = Colors.ORANGE
        
    svg = f"""
    <svg width="100%" height="60" viewBox="0 0 100 50" style="overflow:visible;">
        <path d="M 20 42 A 30 30 0 0 1 80 42" fill="none" stroke="rgba(255,255,255,0.06)" stroke-width="7" stroke-linecap="round" />
        <path d="M 20 42 A 30 30 0 0 1 {50 + 30 * math.cos(angle)} {42 - 30 * math.sin(angle)}" fill="none" stroke="{bar_color}" stroke-width="7" stroke-linecap="round" />
        <line x1="50" y1="42" x2="{nx}" y2="{ny}" stroke="#fff" stroke-width="1.8" stroke-linecap="round" />
        <circle cx="50" cy="42" r="2.5" fill="#fff" />
        <text x="50" y="38" font-size="9" font-weight="900" fill="#fff" text-anchor="middle">{value:.1f}{unit}</text>
        <text x="50" y="49" font-size="6.5" fill="#94a3b8" text-anchor="middle" font-weight="700" style="text-transform:uppercase;letter-spacing:0.3px;">{title}</text>
    </svg>
    """
    return svg


def render_sparkline_svg(
    values: List[float],
    width: float = 220,
    height: float = 45,
    stroke_color: str = "#ff9f43"
) -> str:
    """Render an SVG sparkline chart"""
    if not values:
        return ""
    min_val = min(values)
    max_val = max(values)
    range_val = max_val - min_val if max_val != min_val else 1.0
    
    pts = []
    n = len(values)
    for i, v in enumerate(values):
        x = (i / (n - 1)) * width if n > 1 else width / 2
        y = height - 4 - ((v - min_val) / range_val) * (height - 8)
        pts.append((x, y))
        
    pts_str = " ".join(f"{x},{y}" for x, y in pts)
    fill_pts_str = f"0,{height} " + pts_str + f" {width},{height}"
    
    # We use a unique ID for the gradient based on timestamp/random to avoid caching collisions
    import random
    grad_id = f"grad-{random.randint(1000, 9999)}"
    
    svg = f"""
    <svg width="100%" height="{height}" viewBox="0 0 {width} {height}" style="overflow:visible; display:block;">
        <defs>
            <linearGradient id="{grad_id}" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stop-color="{stroke_color}" stop-opacity="0.2"/>
                <stop offset="100%" stop-color="{stroke_color}" stop-opacity="0.0"/>
            </linearGradient>
        </defs>
        <polygon points="{fill_pts_str}" fill="url(#{grad_id})" />
        <polyline points="{pts_str}" fill="none" stroke="{stroke_color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />
    </svg>
    """
    return svg


def render_section_header(title: str, icon: str = "") -> str:
    """Render a consistent section header using styling tokens"""
    icon_html = f'<span style="margin-right: 6px;">{icon}</span>' if icon else ""
    return f'<div class="section-header">{icon_html}{title}</div>'


def render_failsafe_row(
    label: str,
    desc: str,
    status: str,
    color: str,
    bg: str,
) -> str:
    """Render a failsafe system status card row"""
    return clean_html(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px; background: {bg}; border: 1px solid {color}25; border-radius: 8px;">
        <div>
            <div style="font-size: 8px; color: #94a3b8; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px;">{label}</div>
            <div style="font-size: 11px; font-weight: 600; color: #fff; margin-top: 1px;">{desc}</div>
        </div>
        <span style="color: {color}; font-size: 9.5px; font-weight: 800; font-family: var(--font-mono); text-transform: uppercase;">{status}</span>
    </div>
    """)


def render_scada_row(
    label: str,
    status: str,
    color: str = "#22c55e",
    border_top: bool = False
) -> str:
    """Render a SCADA gateway integrations row"""
    border_style = "border-top: 1px solid rgba(255,255,255,0.06); padding-top: 6px; margin-top: 2px;" if border_top else ""
    return clean_html(f"""
    <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; {border_style}">
        <span style="color: #94a3b8; font-weight: 500;">{label}</span>
        <span style="color: {color}; font-weight: 700;">{status}</span>
    </div>
    """)