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
# Prolific completion URL
#   - Use https://example.com for testing
#   - Replace with Prolific completion URL when ready:
#     https://app.prolific.com/submissions/complete?cc=YOURCODE
# ============================================================
PROLIFIC_COMPLETE_URL = "https://app.prolific.com/submissions/complete?cc=C1QA3C1R"


def completion_screen(url: str, title: str = "All done!", subtitle: str = ""):
    """
    Show a completion screen that:
      1) ALWAYS provides a clickable link (reliable)
      2) ALSO attempts auto-redirect (best-effort)
    """
    st.session_state["interview_active"] = False

    st.markdown(f"## {title}")
    if subtitle:
        st.markdown(subtitle)

    st.markdown("### Return to Prolific")
    st.link_button("Return to Prolific", url)
    st.markdown(f"If the button doesn’t work, click this link: {url}")

    # Best-effort auto-redirect attempts (some environments block these)
    components.html(
        f"""
        <script>
          // Try multiple redirect styles
          try {{
            window.top.location.href = "{url}";
          }} catch (e) {{}}

          setTimeout(function() {{
            try {{
              window.location.href = "{url}";
            }} catch (e) {{}}
          }}, 250);

          setTimeout(function() {{
            try {{
              window.location.replace("{url}");
            }} catch (e) {{}}
          }}, 750);
        </script>

        <noscript>
          <p>JavaScript is disabled. Please use the button above to return to Prolific.</p>
        </noscript>
        """,
        height=0,
    )

    st.stop()


# ============================================================
# Prolific parameters (capture + enforce)
# ============================================================
params = st.query_params
st.session_state.setdefault("PROLIFIC_PID", params.get("PROLIFIC_PID"))
st.session_state.setdefault("STUDY_ID", params.get("STUDY_ID"))
st.session_state.setdefault("SESSION_ID", params.get("SESSION_ID"))

if not st.session_state["PROLIFIC_PID"]:
    st.error("Missing PROLIFIC_PID. Please start this study from Prolific.")
    st.stop()

# Use Prolific PID as storage identifier (do NOT change login username logic)
st.session_state.setdefault("storage_id", st.session_state["PROLIFIC_PID"])

# ============================================================
# Page config
# ============================================================
st.set_page_config(page_title="Interview", page_icon=config.AVATAR_INTERVIEWER)

# ============================================================
# API selection
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
# Login logic (UNCHANGED)
# ============================================================
if config.LOGINS:
    pwd_correct, username = check_password()
    if not pwd_correct:
        st.stop()
    st.session_state.username = username
else:
    st.session_state.username = "testaccount"

# ============================================================
# ADMIN: Download study data as ZIP (temporary / admin-only)
# ============================================================
import zipfile
import io

with st.sidebar:
    if st.button("Download study data (admin)"):
        zip_buffer = io.BytesIO()

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
            for folder in [
                config.TRANSCRIPTS_DIRECTORY,
                config.TIMES_DIRECTORY,
                config.BACKUPS_DIRECTORY,
            ]:
                if not os.path.exists(folder):
                    continue

                for root, _, files in os.walk(folder):
                    for file in files:
                        full_path = os.path.join(root, file)
                        arcname = os.path.relpath(full_path)
                        zipf.write(full_path, arcname=arcname)

        zip_buffer.seek(0)

        st.download_button(
            label="Download ZIP file",
            data=zip_buffer,
            file_name="study_data.zip",
            mime="application/zip",
        )
    

# ============================================================
# Ensure directories exist
# ============================================================
for d in [config.TRANSCRIPTS_DIRECTORY, config.TIMES_DIRECTORY, config.BACKUPS_DIRECTORY]:
    os.makedirs(d, exist_ok=True)

# ============================================================
# Session state init
# ============================================================
st.session_state.setdefault("interview_active", True)
st.session_state.setdefault("messages", [])

if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()
    st.session_state.start_time_file_names = time.strftime(
        "%Y_%m_%d_%H_%M_%S", time.localtime(st.session_state.start_time)
    )

# ============================================================
# Completion check (keyed by storage_id)
# ============================================================
interview_previously_completed = check_if_interview_completed(
    config.TIMES_DIRECTORY, st.session_state["storage_id"]
)

if interview_previously_completed and not st.session_state.messages:
    completion_screen(
        PROLIFIC_COMPLETE_URL,
        title="Interview already completed.",
        subtitle="Please return to Prolific to finish your submission.",
    )

# ============================================================
# Quit handler + button
#   IMPORTANT: We DO NOT append extra UI chat messages after quit.
#   We go straight to completion_screen.
# ============================================================
def on_quit():
    st.session_state.interview_active = False
    try:
        save_interview_data(
            st.session_state["storage_id"],
            config.TRANSCRIPTS_DIRECTORY,
            config.TIMES_DIRECTORY,
        )
    except Exception:
        pass

    completion_screen(
        PROLIFIC_COMPLETE_URL,
        title="You ended the interview.",
        subtitle="Please return to Prolific to finish your submission.",
    )


_, col_quit = st.columns([0.85, 0.15])
with col_quit:
    st.button(
        "Quit",
        help="End the interview.",
        on_click=on_quit,
        disabled=not st.session_state.interview_active,
    )

# ============================================================
# Render prior conversation
# ============================================================
for message in st.session_state.messages[1:]:
    avatar = config.AVATAR_INTERVIEWER if message["role"] == "assistant" else config.AVATAR_RESPONDENT
    if not any(code in message["content"] for code in config.CLOSING_MESSAGES.keys()):
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])

# ============================================================
# API client + kwargs
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
# Bootstrap: initial message if empty
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
# Main interview loop
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

            # Always store raw assistant output
            st.session_state.messages.append({"role": "assistant", "content": message_interviewer})

            # If no code: show message and backup-save
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

            # If closing code: final save + completion screen
            for code, closing_msg in config.CLOSING_MESSAGES.items():
                if code in message_interviewer:
                    st.session_state.interview_active = False
                    st.markdown(closing_msg)
                    st.session_state.messages.append({"role": "assistant", "content": closing_msg})

                    # Final save loop with timeout
                    deadline = time.time() + 10.0
                    stored = False
                    while (not stored) and (time.time() < deadline):
                        try:
                            save_interview_data(
                                username=st.session_state["storage_id"],
                                transcripts_directory=config.TRANSCRIPTS_DIRECTORY,
                                times_directory=config.TIMES_DIRECTORY,
                            )
                        except Exception:
                            pass

                        stored = check_if_interview_completed(
                            config.TRANSCRIPTS_DIRECTORY,
                            st.session_state["storage_id"],
                        )
                        time.sleep(0.1)

                    completion_screen(
                        PROLIFIC_COMPLETE_URL,
                        title="Interview complete.",
                        subtitle="Please return to Prolific to finish your submission.",
                    )
