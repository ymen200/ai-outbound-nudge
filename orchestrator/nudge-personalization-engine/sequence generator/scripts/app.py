import streamlit as st

# Import sequence UI
from app_sequences import render_sequence_ui

st.set_page_config(page_title="Outreach Sequence Manager", layout="wide", page_icon="�")
st.title("� AI Outreach Sequence Manager")

# Render the sequence UI directly (no tabs, no simple analysis)
render_sequence_ui()