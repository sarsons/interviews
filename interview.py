import os
import time
from typing import Optional

import streamlit as st
import streamlit.components.v1 as components

import config
from utils import (
    check_password,
    check_if_interview_completed,
    save_interview_data,
)

# ============================================================
# 0) Prolific parameters (capture + enforce)
# ============================================================
params = st.query_params
st.session_state.setdefault("PROLIFIC_PID", params.get("PROLIFIC_PID"))
st.session_state.setdefault("STUDY_ID", params.get("STUDY_ID"))
st.session_state.setdefault("SESSION_ID", params.get("SESSION_ID"))

if not st.session_state["PROLIFIC_PID"]:
    st.error("Missing PROLIFIC_PID. Please start this study from Prolific.")
    st.stop()

# Use Prolific PID as the storage identifier (do NOT change login username logic)
st.session_state.setdefault("storage_id", st.session_state["PROLIFIC_PID"])

# ============================================================
# 1) Prolific completion redirect (robust for Streamlit Cloud)
# ============================================================
# TODO: Replace XXXXXX with your real completion code from Prolific
PROLIFIC_COMPLETE_URL = "https://example.com"

def redirect_to_prolific(url: str = PROLIFIC_COMPLETE_URL):
    """Redirect user back to Prolific (JS-based). Includes a manual fallback link."""
    st.success("All done — returning you to Prolific…")

    # Manual fallback in case auto-redirect is blocked
    st.link_button("Click here if you are not redirected", url)

    # JS redirect; window.top is important if embedded
    components.html(
        f"""
        <script>
          window.top.location.href = "{url}";
        </script>
        """,
        height=0,
    )
    st.stop()

# ============================================================
# 2) Page config
# ============================================================
st.set_page_config(page_title="Interview", page_icon=config.AVATAR_INTERVIEWER)

# ============================================================
# 3) API selection
# ============================================================
if "gpt" in config.MODEL.lower():
    api = "openai"
    from openai import OpenAI
elif "claude" in config.MODEL.lower():
    api = "anthropic"
    import anthropic
else:
    raise ValueError("Model does not contain 'gpt' or 'claude'; unable to determine API.")

# ============================================================
# 4) Login logic (UNCHANGED)
# ============================================================
if config.LOGINS:
    pwd_correct, username = check_password()
    if not pwd_correct:
        st.stop()
    st.session_state.username = username
else:
    st.session_state.username = "testaccount"

# ============================================================
# 5) Ensure directories exist
# ============================================================
for d in [config.TRANSCRIPTS_DIRECTORY, config.TIMES_DIRECTORY, config.BACKUPS_DIRECTORY]:
    os.makedirs(d, exist_ok=True)

# ============================================================
# 6) Session state init
# ============================================================
st.session_state.setdefault("interview_active", True)
st.session_state.setdefault("messages", [])

if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()
    st.session_state.start_time_file_names = time.strftime(
        "%Y_%m_%d_%H_%M_%S", time.localtime(st.session_state.start_time)
    )

# ============================================================
# 7) Completion check (keyed by Prolific PID storage_id)
# ============================================================
interview_previously_completed = check_if_interview_completed(
    config.TIMES_DIRECTORY, st.session_state["storage_id"]
)

if interview_previously_completed and not st.session_state.messages:
    st.session_state.interview_active = False
    st.markdown("Interview already completed.")

# ============================================================
# 8) Quit button (always redirects even if saving errors)
# ============================================================
_, col_quit = st.columns([0.85, 0.15])
with col_quit:
    if st.session_state.interview_active and st.button("Quit", help="End the interview."):
        st.session_state.interview_active = False
        st.session_state.messages.append(
            {"role": "assistant", "content": "You have cancelled the interview."}
        )
        try:
            save_interview_data(
                st.session_state["storage_id"],
                config.TRANSCRIPTS_DIRECTORY,
                config.TIMES_DIRECTORY,
            )
        finally:
            redirect_to_prolific()

# ============================================================
# 9) Render prior conversation (skip system prompt and skip code messages)
# ============================================================
for message in st.session_state.messages[1:]:
    avatar = config.AVATAR_INTERVIEWER if message["role"] == "assistant" else config.AVATAR_RESPONDENT
    if not any(code in message["content"] for code in config.CLOSING_MESSAGES.keys()):
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])

# ============================================================
# 10) API client + kwargs
# ============================================================
if api == "openai":
    client = OpenAI(api_key=st.secrets["API_KEY_OPENAI"])
    api_kwargs = {"stream": True}
else:
    client = anthropic.Anthropic(api_key=st.secrets["API_KEY_ANTHROPIC"])
    api_kwargs = {"system": config.SYSTEM_PROMPT}

api_kwargs["messages"] = st.session_state.messages
api_kwargs["model"] = config.MODEL
api_kwargs["max_tokens"] = config.MAX_OUTPUT_TOKENS
if config.TEMPERATURE is not None:
    api_kwargs["temperature"] = config.TEMPERATURE

# ============================================================
# 11) Bootstrap: initial message if empty
# ============================================================
if not st.session_state.messages:
    if api == "openai":
        st.session_state.messages.append({"role": "system", "content": config.SYSTEM_PROMPT})
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            stream = client.chat.completions.create(**api_kwargs)
            message_interviewer = st.write_stream(stream)
    else:
        st.session_state.messages.append({"role": "user", "content": "Hi"})
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            placeholder = st.empty()
            message_interviewer = ""
            with client.messages.stream(**api_kwargs) as stream:
                for text_delta in stream.text_stream:
                    if text_delta:
                        message_interviewer += text_delta
                    placeholder.markdown(message_interviewer + "▌")
            placeholder.markdown(message_interviewer)

    st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

    # Backup write (keyed by storage_id)
    save_interview_data(
        username=st.session_state["storage_id"],
        transcripts_directory=config.BACKUPS_DIRECTORY,
        times_directory=config.BACKUPS_DIRECTORY,
        file_name_addition_transcript=f"_transcript_started_{st.session_state.start_time_file_names}",
        file_name_addition_time=f"_time_started_{st.session_state.start_time_file_names}",
    )

# ============================================================
# 12) Main interview loop
# ============================================================
if st.session_state.interview_active:
    if message_respondent := st.chat_input("Your message here"):
        st.session_state.messages.append({"role": "user", "content": message_respondent})

        with st.chat_message("user", avatar=config.AVATAR_RESPONDENT):
            st.markdown(message_respondent)

        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            placeholder = st.empty()
            message_interviewer = ""

            if api == "openai":
                stream = client.chat.completions.create(**api_kwargs)
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        message_interviewer += delta
                    if len(message_interviewer) > 5:
                        placeholder.markdown(message_interviewer + "▌")
                    if any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                        placeholder.empty()
                        break
            else:
                with client.messages.stream(**api_kwargs) as stream:
                    for text_delta in stream.text_stream:
                        if text_delta:
                            message_interviewer += text_delta
                        if len(message_interviewer) > 5:
                            placeholder.markdown(message_interviewer + "▌")
                        if any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                            placeholder.empty()
                            break

            # Always store the raw assistant output (even if it contains a code)
            st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

            # If no code, show full response and write backup
            if not any(code in message_interviewer for code in config.CLOSING_MESSAGES.keys()):
                placeholder.markdown(message_interviewer)

                try:
                    save_interview_data(
                        username=st.session_state["storage_id"],
                        transcripts_directory=config.BACKUPS_DIRECTORY,
                        times_directory=config.BACKUPS_DIRECTORY,
                        file_name_addition_transcript=f"_transcript_started_{st.session_state.start_time_file_names}",
                        file_name_addition_time=f"_time_started_{st.session_state.start_time_file_names}",
                    )
                except Exception:
                    pass

            # If a closing code appears, show closing message, save final, redirect
            for code, closing_msg in config.CLOSING_MESSAGES.items():
                if code in message_interviewer:
                    st.session_state.interview_active = False
                    st.markdown(closing_msg)
                    st.session_state.messages.append({"role": "assistant", "content": closing_msg})

                    # Final save loop (with timeout)
                    deadline = time.time() + 10.0
                    final_transcript_stored = False

                    while (not final_transcript_stored) and (time.time() < deadline):
                        try:
                            save_interview_data(
                                username=st.session_state["storage_id"],
                                transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                                times_directory=config.TIMES_DIRECTORY,
                            )
                        except Exception:
                            pass

                        final_transcript_stored = check_if_interview_completed(
                            config.TRANSCRIPTS_DIRECTORY,
                            st.session_state["storage_id"],
                        )
                        time.sleep(0.1)

                    redirect_to_prolific()
