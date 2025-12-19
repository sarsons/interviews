import os
import time

import streamlit as st
import streamlit.components.v1 as components

import config
from utils import (
    check_password,
    check_if_interview_completed,
    save_interview_data,
)

# ============================================================
# 0) Configuration: where to redirect (use example.com for testing)
# ============================================================
PROLIFIC_COMPLETE_URL = "https://example.com"  # replace with Prolific completion URL when ready

# ============================================================
# 1) Redirect handler (MUST run at top, before any other UI)
#    This is the only place we execute JS redirect.
# ============================================
