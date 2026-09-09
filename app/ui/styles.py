"""Shared, responsive presentation for the four workspaces."""
import streamlit as st
from html import escape


def apply_styles():
    st.html("""<style>
    .stApp {background:radial-gradient(ellipse at 12% 12%, #e4e5f6 0, transparent 42%), radial-gradient(ellipse at 94% 75%, #e5edf6 0, transparent 40%), #eef0f6;color:#263244;}
    html {font-size:18px;}
    [data-testid="stToolbar"], [data-testid="stAppDeployButton"], #MainMenu {display:none!important;}
    [data-testid="stHeader"] {background:transparent;pointer-events:none;}
    [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
    [data-testid="stWidgetLabel"] p, textarea, input {font-size:1rem!important;}
    [data-testid="stCaptionContainer"] p {font-size:.88rem!important;}
    
    [data-testid="stMainBlockContainer"] {width:60%;max-width:1440px;padding:2.5rem 0 5rem;}
    h1 {font-size:2rem!important;letter-spacing:-.035em;padding-top:1rem!important;}
    h2 {font-size:1.35rem!important;}
    h3 {font-size:1.15rem!important;}
    [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"][data-test-wrap] {border:1px solid #dce0ec!important;border-radius:18px!important;background:#fff;box-shadow:0 6px 24px rgba(43,49,83,.065);}
    [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"][data-test-wrap] {padding:1.2rem;}
    [data-testid="stTextArea"] textarea {border:1px solid #dce1ee!important;border-radius:10px!important;}
    [data-testid="stFileUploaderDropzone"] {border:1px dashed #b6bddd;border-radius:10px;}
    textarea {resize:none!important;line-height:1.7!important;}
    [data-testid="stTextArea"] textarea,[data-testid="stFileUploaderDropzone"] {background:#f4f6fb!important;color:#263244!important;}
    /* Inner sections use spacing and a separator instead of another card. */
    [data-testid="stVerticalBlock"][data-test-wrap] [data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"][data-test-wrap] {border:none!important;border-top:1px solid #ececf2!important;border-radius:0!important;box-shadow:none!important;background:transparent;padding:1.1rem 0 .4rem!important;}
    .choice-label {font-size:.95rem;font-weight:650;color:#42465c;margin:.1rem 0 -.35rem;}
    .choice-label span {font-size:.75rem;font-weight:400;color:#85899a;margin-left:.4rem;}
    [class*="st-key-dropdown_"] button {min-height:48px;background:#f5f3fc;border:1px solid #c9bfdf!important;padding:.65rem .9rem;cursor:pointer;text-align:left;}
    [class*="st-key-dropdown_"] button:hover {background:#ede7fa;border-color:#8b70c6!important;}
    [class*="st-key-dropdown_"] button:focus-visible {outline:3px solid #cfc2ec;outline-offset:2px;}
    [class*="st-key-dropdown_"] button > div {width:100%;justify-content:space-between!important;}
    [class*="st-key-dropdown_"] button [data-testid="stMarkdownContainer"] {flex:1;text-align:left!important;}
    [class*="st-key-dropdown_"] button [data-testid="stMarkdownContainer"] p {text-align:left!important;}
    [class*="st-key-dropdown_"] button svg {margin-left:auto;min-width:24px;color:#7253ae;}
    button {border-radius:9px!important;}
    [data-testid="stPopover"] button {justify-content:space-between;text-align:left;}
    .st-key-navigation {width:100%;}
    .st-key-navigation [role="radiogroup"] {justify-content:center;width:100%;}
    .st-key-navigation [data-testid="stRadioOption"] p {font-size:1.12rem!important;font-weight:700!important;text-align:center;}
    .st-key-top_navigation [data-testid="stMarkdownContainer"] p {font-size:1.12rem!important;font-weight:700;text-align:center;}
    
    .st-key-navigation [role="radiogroup"],.st-key-interview_context_toggle [role="radiogroup"],.st-key-library_section [role="radiogroup"] {gap:.4rem;}
    .st-key-navigation [data-testid="stRadioOption"] > div > div > div:first-child,
    .st-key-interview_context_toggle [data-testid="stRadioOption"] > div > div > div:first-child,
    .st-key-library_section [data-testid="stRadioOption"] > div > div > div:first-child {display:none;}
    .st-key-navigation [role="radiogroup"] label,.st-key-interview_context_toggle [role="radiogroup"] label,.st-key-library_section [role="radiogroup"] label {padding:.65rem 1.1rem;border-radius:10px;cursor:pointer;}
    .st-key-navigation label:has(input:checked),.st-key-interview_context_toggle label:has(input:checked),.st-key-library_section label:has(input:checked) {background:#eeeafd;color:#6650c9;font-weight:600;}
    [role="tablist"] {gap:.5rem;background:#e8eaf3;border-radius:12px;padding:.35rem;}
    [role="tab"][aria-selected="true"] {background:white;border-radius:8px;box-shadow:0 2px 6px #26324412;}
    [data-testid="stLayoutWrapper"] > .st-key-top_navigation[data-testid="stVerticalBlock"] {background:transparent!important;border:none!important;border-radius:0;padding:.6rem 0!important;box-shadow:none!important;margin-bottom:.5rem;width:64vw!important;max-width:none!important;position:relative;left:50%;transform:translateX(-50%);}
    .st-key-page_intro {background:linear-gradient(115deg,#e3ddfa,#edf0fb 65%,#e1edf8)!important;border:1px solid #cfc9ea!important;border-radius:18px;padding:1.6rem 1.8rem!important;margin-bottom:.6rem;position:relative;overflow:hidden;}
    .st-key-page_intro h1 {font-size:2.2rem!important;padding:0!important;color:#302852;}
    .st-key-page_intro [data-testid="stCaptionContainer"] {color:#555877!important;font-size:.95rem;}
    .page-eyebrow {color:#6c56ad;font-size:.72rem;font-weight:700;letter-spacing:.14em;margin-bottom:.1rem;}
    .section-heading {display:flex;align-items:center;gap:.7rem;font-size:1.1rem;font-weight:650;color:#303651;margin-bottom:.4rem;}
    .section-heading span {display:inline-grid;place-items:center;width:30px;height:30px;background:#ece7fa;color:#7456bc;border-radius:9px;font-size:.8rem;}
    .input-heading, .panel-heading {font-size:1.15rem!important;font-weight:750!important;line-height:1.5;background:transparent;border:none;border-left:3px solid #8a70cd;border-radius:0;padding:.15rem .65rem!important;margin:0 0 .65rem!important;color:#44365f;}
    .section-heading {background:transparent;border:none;padding:.2rem 0;font-size:1.2rem;}
    [data-testid="stWidgetLabel"] p {font-weight:650!important;color:#3c405a;}
    .st-key-interview_context_toggle [data-testid="stWidgetLabel"] p,
    .st-key-library_section [data-testid="stWidgetLabel"] p {font-size:1.15rem!important;border-left:4px solid #8a70cd;padding-left:.65rem;margin-bottom:.5rem;}
    .history-preview .record-title {display:block;font-size:1.15rem;line-height:1.55;font-weight:750;color:#403258;margin-bottom:.65rem;padding-left:.7rem;border-left:4px solid #9277cc;}
    .history-preview .record-summary {font-size:.95rem;color:#60677c;line-height:1.75;}
    
    .st-key-navigation label:has(input:checked) {background:#7760c9!important;color:white!important;box-shadow:0 3px 8px #7760c933;}
    .st-key-navigation label:has(input:checked) p {color:white!important;}
    [data-testid="stBaseButton-primary"] {box-shadow:0 4px 10px #7760c92a;}
    
    @media(min-width:641px) and (max-width:1400px) {.st-key-top_navigation {width:94vw!important;}}
    @media(max-width:1200px) {[data-testid="stMainBlockContainer"] {width:86%;}.st-key-top_navigation {width:94vw!important;}}
    @media(max-width:640px) {html {font-size:16px;} .st-key-navigation [role="radiogroup"] label {padding:.55rem .7rem;}[data-testid="stMainBlockContainer"] {width:94%;padding-top:1rem;} h1 {font-size:1.7rem!important;}}
    </style>""")


def page_intro(title, description, eyebrow):
    with st.container(key="page_intro"):
        st.html(f'<div class="page-eyebrow">{eyebrow}</div>')
        st.title(title)
        st.caption(description)


def section_heading(number, title):
    st.html(f'<div class="section-heading"><span>{number}</span>{title}</div>')


def panel_heading(title):
    """Explicit section heading; ordinary bold content keeps its normal style."""
    st.html(f'<h3 class="panel-heading">{escape(str(title))}</h3>')
