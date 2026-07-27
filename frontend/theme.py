"""Enterprise theme (custom CSS) for the Streamlit UI.

Streamlit 1.56 only exposes a handful of [theme] keys in config.toml, so the
richer look (brand header, cards, stepper, pill badges, button polish) is done
here with scoped CSS targeting Streamlit's stable data-testid selectors.
"""

import streamlit as st

_BASE_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

  :root {
    --brand:        #059669;
    --brand-2:      #0D9488;
    --brand-3:      #14B8A6;
    --brand-ink:    #064E3B;
    --ink:          #0F172A;
    --muted:        #64748B;
    --line:         #E7EAF0;
    --surface:      #FFFFFF;
    --surface-2:    #F8FAFC;
    --ok:           #16A34A;
    --ok-bg:        #F0FDF4;
    --err:          #DC2626;
    --err-bg:       #FEF2F2;
    --shadow-sm:    0 1px 2px rgba(15,23,42,.05);
    --shadow:       0 1px 3px rgba(15,23,42,.05), 0 12px 32px -8px rgba(15,23,42,.10);
    --shadow-lg:    0 24px 60px -16px rgba(6,78,59,.30);
  }

  html, body, [class*="css"], .stMarkdown, .stButton, input, textarea {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased;
  }

  /* ---------- Ambient gradient-mesh background ---------- */
  [data-testid="stAppViewContainer"] {
    background: #F1F5F9;
  }
  [data-testid="stHeader"] { background: transparent; }
  #MainMenu, footer { visibility: hidden; }

  .block-container, [data-testid="stMainBlockContainer"] {
    max-width: 780px;
    padding-top: 2rem;
    padding-bottom: 4rem;
  }

  @keyframes rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
  @keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
  @keyframes pulse-ring {
    0%   { box-shadow: 0 0 0 0 rgba(5,150,105,.30); }
    70%  { box-shadow: 0 0 0 8px rgba(5,150,105,0); }
    100% { box-shadow: 0 0 0 0 rgba(5,150,105,0); }
  }

  /* ---------- Brand header (glass + sheen) ---------- */
  .app-header {
    position: relative; overflow: hidden;
    display: flex; align-items: center; gap: 16px;
    padding: 24px 26px;
    border-radius: 20px;
    background: linear-gradient(120deg, var(--brand) 0%, var(--brand-2) 55%, #0F766E 100%);
    color: #fff;
    box-shadow: var(--shadow-lg);
    animation: rise .5s ease both;
  }
  .app-header::after {
    content: ""; position: absolute; inset: 0;
    background: linear-gradient(100deg, transparent 30%, rgba(255,255,255,.22) 50%, transparent 70%);
    background-size: 200% 100%;
    animation: shimmer 6s linear infinite;
    pointer-events: none;
  }
  .app-header .logo {
    width: 52px; height: 52px; flex: 0 0 52px; position: relative; z-index: 1;
    display: grid; place-items: center;
    background: rgba(255,255,255,.18);
    border: 1px solid rgba(255,255,255,.3);
    border-radius: 14px; font-size: 26px;
    backdrop-filter: blur(6px);
  }
  .app-header .htext { position: relative; z-index: 1; }
  .app-header h1 { margin: 0; font-size: 1.5rem; font-weight: 800; letter-spacing: -.02em; }
  .app-header p  { margin: 3px 0 0; font-size: .88rem; opacity: .9; font-weight: 400; }
  .app-header .pill {
    position: relative; z-index: 1;
    margin-left: auto; font-size: .66rem; font-weight: 700; letter-spacing: .1em;
    text-transform: uppercase; padding: 7px 13px; border-radius: 999px;
    background: rgba(255,255,255,.2); border: 1px solid rgba(255,255,255,.35);
    backdrop-filter: blur(6px);
  }

  /* ---------- Trust badges row ---------- */
  .trust { display: flex; gap: 10px; flex-wrap: wrap; margin: 16px 2px 4px; animation: rise .6s ease both; }
  .trust .chip {
    display: inline-flex; align-items: center; gap: 7px;
    font-size: .78rem; font-weight: 600; color: #334155;
    background: rgba(255,255,255,.72); backdrop-filter: blur(8px);
    border: 1px solid var(--line); border-radius: 999px; padding: 7px 13px;
    box-shadow: var(--shadow-sm);
  }
  .trust .chip .ic { font-size: .9rem; }

  /* ---------- Stepper (connected + animated) ---------- */
  .stepper {
    display: flex; margin: 24px 4px 8px; padding: 0;
    animation: rise .6s ease both;
  }
  .stepper .step { flex: 1; text-align: center; position: relative; }
  /* connector line between dots */
  .stepper .step::before {
    content: ""; position: absolute; top: 17px; left: -50%; width: 100%; height: 3px;
    background: var(--line); z-index: 0; border-radius: 2px;
  }
  .stepper .step:first-child::before { display: none; }
  .stepper .step.done::before, .stepper .step.active::before {
    background: linear-gradient(90deg, var(--brand), var(--brand-2));
  }
  .stepper .dot {
    position: relative; z-index: 1;
    width: 34px; height: 34px; margin: 0 auto 9px; border-radius: 50%;
    display: grid; place-items: center; font-size: .82rem; font-weight: 700;
    background: #fff; color: var(--muted);
    border: 2px solid var(--line); transition: all .25s ease;
  }
  .stepper .label { font-size: .73rem; color: var(--muted); font-weight: 600; letter-spacing: .01em; }
  .stepper .step.done  .dot {
    background: linear-gradient(135deg, var(--brand), var(--brand-2));
    color:#fff; border-color: transparent;
  }
  .stepper .step.active .dot {
    background:#fff; color: var(--brand); border-color: var(--brand);
    animation: pulse-ring 1.6s ease-out infinite;
  }
  .stepper .step.done  .label, .stepper .step.active .label { color: var(--ink); }

  /* ---------- Section headings ---------- */
  .section-title {
    font-size: 1.1rem; font-weight: 700; color: var(--ink);
    margin: 28px 0 3px; letter-spacing: -.01em;
  }
  .section-sub { font-size: .86rem; color: var(--muted); margin: 0 0 6px; line-height: 1.5; }

  /* ---------- Form as an elevated glass card ---------- */
  [data-testid="stForm"] {
    background: rgba(255,255,255,.82);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255,255,255,.7);
    box-shadow: var(--shadow);
    border-radius: 20px;
    padding: 24px 26px 10px;
    animation: rise .6s ease both;
  }

  /* Inputs */
  [data-testid="stWidgetLabel"] p { font-weight: 600; font-size: .8rem; color: #475569; }
  .stTextInput input, .stNumberInput input {
    border-radius: 11px !important;
    border: 1px solid var(--line) !important;
    background: var(--surface-2) !important;
    padding: 11px 13px !important;
    transition: all .18s ease !important;
  }
  .stTextInput input:hover, .stNumberInput input:hover { border-color: #CBD5E1 !important; }
  .stTextInput input:focus, .stNumberInput input:focus {
    border-color: var(--brand) !important;
    box-shadow: 0 0 0 4px rgba(5,150,105,.15) !important;
    background: #fff !important;
  }
  [data-baseweb="select"] > div {
    border-radius: 11px !important;
    border: 1px solid var(--line) !important;
    background: var(--surface-2) !important;
  }

  /* Buttons */
  .stButton > button, [data-testid="stFormSubmitButton"] button {
    width: 100%;
    border-radius: 12px !important;
    font-weight: 700 !important;
    font-size: .95rem !important;
    letter-spacing: .01em !important;
    padding: 13px 16px !important;
    border: none !important;
    color: #fff !important;
    background: linear-gradient(120deg, var(--brand) 0%, var(--brand-2) 100%) !important;
    background-size: 160% 160% !important;
    box-shadow: 0 8px 20px -4px rgba(5,150,105,.5) !important;
    transition: transform .08s ease, box-shadow .25s ease, background-position .4s ease !important;
  }
  .stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover {
    background-position: 100% 0 !important;
    box-shadow: 0 12px 28px -4px rgba(5,150,105,.6) !important;
    transform: translateY(-2px);
  }
  .stButton > button:active, [data-testid="stFormSubmitButton"] button:active {
    transform: translateY(0);
  }

  /* ---------- Result card + status badge ---------- */
  .result-card {
    background: rgba(255,255,255,.86); backdrop-filter: blur(10px);
    border: 1px solid var(--line);
    border-radius: 18px; padding: 20px 22px; box-shadow: var(--shadow);
    margin-top: 16px; animation: rise .45s ease both;
  }
  .badge {
    display: inline-flex; align-items: center; gap: 9px;
    font-size: .84rem; font-weight: 700; padding: 9px 15px; border-radius: 999px;
  }
  .badge .dotled { width: 9px; height: 9px; border-radius: 50%; }
  .badge.ok   { background: var(--ok-bg);  color: var(--ok);  }
  .badge.err  { background: var(--err-bg); color: var(--err); }
  .badge.idle { background: var(--surface-2); color: var(--muted); border: 1px solid var(--line); }
  .badge.ok   .dotled { background: var(--ok);  box-shadow: 0 0 0 4px rgba(22,163,74,.16); animation: pulse-ring 2s infinite; }
  .badge.err  .dotled { background: var(--err); box-shadow: 0 0 0 4px rgba(220,38,38,.16); }
  .badge.idle .dotled { background: #94A3B8; }

  .kv { font-size: .84rem; color: var(--muted); margin: 12px 0 0; line-height: 1.7; }
  .kv code {
    background: var(--surface-2); border: 1px solid var(--line);
    border-radius: 7px; padding: 3px 8px; color: var(--brand-ink);
    font-size: .8rem; font-weight: 600;
  }

  /* ---------- Footer ---------- */
  .app-footer {
    text-align: center; margin-top: 34px; padding-top: 18px;
    border-top: 1px solid var(--line);
    font-size: .76rem; color: var(--muted);
  }
  .app-footer b { color: #475569; font-weight: 700; }
</style>
"""


def inject_base_theme() -> None:
    st.markdown(_BASE_CSS, unsafe_allow_html=True)
