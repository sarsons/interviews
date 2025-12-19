import os
import time
import io
import zipfile

import streamlit as st
import streamlit.components.v1 as components

import config
from utils import (
    check_password,
    check_if_interview_completed,
    save_interview_data,
)

# ============================================================
# 0) SETTINGS
# ============================================================
# While testing redirects, keep example.com. For launch:
PROLIFIC_COMPLETE_URL = "https://app.prolific.com/submissions/complete?cc=C1QA3C1R"

# If LOGINS is False, we'll allow an admin bypass without Prolific params.
# If LOGINS is True, you can open the app without Prolific params and log in.
ALLOW_ADMIN_BYPASS_WHEN_LOGINS_FALSE = True

# ============================================================
# 1) Helper: Completion/Exit screen (reliable + clickable)
# ============================================================
def completion_screen(url: str, title: str, subtitle: str = "", completion_code: str = ""):
    st.session_state["interview_active"] = False

    st.markdown(f"# {title}")
    if subtitle:
        st.markdown(subtitle)

    if completion_code:
        st.markdown("## Completion code")
        st.code(completion_code, language="text")

    st.markdown("---")
    st.markdown("## Return / Finish")

    # Most compatible navigation method: HTML <a> with target=_top
    st.markdown(
        f"""
        <div style="font-size: 20px; line-height: 1.6;">
          <a href="{url}" target="_top" rel="noopener noreferrer"
             style="display:inline-block; padding:12px 18px; border:1px solid #ccc; border-radius:10px; text-decoration:none;">
            ✅ Click here to return
          </a>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(f"Backup link: [{url}]({url})")
    st.code(url, language="text")

    # Best-effort auto redirect (may be blocked in some contexts)
    components.html(
        f"""<script>try{{window.top.location.href="{url}"}}catch(e){{}}</script>""",
        height=0,
    )
    st.stop()

# ============================================================
# 2) Page config
# ============================================================
st.set_page_config(page_title="Interview", page_icon=config.AVATAR_INTERVIEWER)

# ============================================================
# 3) Prolific parameters (capture + enforce, with admin bypass)
# ============================================================
params = st.query_params
st.session_state.setdefault("PROLIFIC_PID", params.get("PROLIFIC_PID"))
st.session_state.setdefault("STUDY_ID", params.get("STUDY_ID"))
st.session_state.setdefault("SESSION_ID", params.get("SESSION_ID"))

# Admin access rule:
# - If LOGINS=True: you can open the app with no params and log in.
# - If LOGINS=False: optionally allow a temporary bypass so you can download data.
if not st.session_state.get("PROLIFIC_PID"):
    if config.LOGINS:
        # allow admin to proceed to login (do not stop)
        pass
    else:
        if ALLOW_ADMIN_BYPASS_WHEN_LOGINS_FALSE:
            st.session_state["PROLIFIC_PID"] = "ADMIN"
            st.session_state["STUDY_ID"] = st.session_state.get("STUDY_ID") or "ADMIN"
            st.session_state["SESSION_ID"] = st.session_state.get("SESSION_ID") or "ADMIN"
        else:
            st.error("Missing PROLIFIC_PID. Please start this study from Prolific.")
            st.stop()

# Storage identifier (per-participant) is Prolific PID (or ADMIN)
st.session_state.setdefault("storage_id", st.session_state["PROLIFIC_PID"])

# ============================================================
# 4) API selection
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
# 5) Login logic (UNCHANGED)
# ============================================================
if config.LOGINS:
    pwd_correct, username = check_password()
    if not pwd_correct:
        st.stop()
    st.session_state.username = username
else:
    st.session_state.username = "testaccount"

# ============================================================
# 6) Ensure directories exist
# ============================================================
for d in [config.TRANSCRIPTS_DIRECTORY, config.TIMES_DIRECTORY, config.BACKUPS_DIRECTORY]:
    os.makedirs(d, exist_ok=True)

# ============================================================
# 7) Admin download: ZIP all study data (sidebar) — LOCKED DOWN
#    Only visible when running as ADMIN (i.e., when you open app without Prolific params)
# ============================================================
def build_data_zip() -> bytes:
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
        for folder in [config.TRANSCRIPTS_DIRECTORY, config.TIMES_DIRECTORY, config.BACKUPS_DIRECTORY]:
            if not os.path.exists(folder):
                continue
            for root, _, files in os.walk(folder):
                for file in files:
                    full_path = os.path.join(root, file)
                    arcname = os.path.relpath(full_path)
                    zipf.write(full_path, arcname=arcname)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()

with st.sidebar:
    # LOCKDOWN: only show admin tools + debug when PROLIFIC_PID == "ADMIN"
    is_admin_view = st.session_state.get("PROLIFIC_PID") == "ADMIN"

    if is_admin_view:
        st.markdown("### Admin")

        if st.button("Prepare study data ZIP"):
            st.session_state["_zip_bytes"] = build_data_zip()

        if st.session_state.get("_zip_bytes"):
            st.download_button(
                "Download study_data.zip",
                data=st.session_state["_zip_bytes"],
                file_name="study_data.zip",
                mime="application/zip",
            )

        st.markdown("---")
        st.markdown("### Debug")
        st.write("PROLIFIC_PID:", st.session_state.get("PROLIFIC_PID"))
        st.write("storage_id:", st.session_state.get("storage_id"))
        st.write("LOGINS:", config.LOGINS)

# ============================================================
# 8) Session state init
# ============================================================
st.session_state.setdefault("interview_active", True)
st.session_state.setdefault("messages", [])

if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()
    st.session_state.start_time_file_names = time.strftime(
        "%Y_%m_%d_%H_%M_%S", time.localtime(st.session_state.start_time)
    )

# ============================================================
# 9) Completion check (keyed by storage_id)
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
# 10) Quit handler + button
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
# 11) Render prior conversation
# ============================================================
for message in st.session_state.messages[1:]:
    avatar = config.AVATAR_INTERVIEWER if message["role"] == "assistant" else config.AVATAR_RESPONDENT
    if not any(code in message["content"] for code in config.CLOSING_MESSAGES.keys()):
        with st.chat_message(message["role"], avatar=avatar):
            st.markdown(message["content"])

# ============================================================
# 12) API client + kwargs
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
# 13) Bootstrap: initial message if empty
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

    # Backup write to record who started (keyed by storage_id)
    save_interview_data(
        username=st.session_state["storage_id"],
        transcripts_directory=config.BACKUPS_DIRECTORY,
        times_directory=config.BACKUPS_DIRECTORY,
        file_name_addition_transcript=f"_transcript_started_{st.session_state.start_time_file_names}",
        file_name_addition_time=f"_time_started_{st.session_state.start_time_file_names}",
    )

# ============================================================
# 14) Main interview loop
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

            # If no code: show and backup-save
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

            # If a closing code appears: show closing msg, final save, completion screen
            for code, closing_msg in config.CLOSING_MESSAGES.items():
                if code in message_interviewer:
                    st.session_state.interview_active = False
                    st.markdown(closing_msg)
                    st.session_state.messages.append({"role": "assistant", "content": closing_msg})

                    # Final save loop (with timeout)
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
