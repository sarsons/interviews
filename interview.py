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
# ============================================================
if st.session_state.get("_redirect_now"):
    url = st.session_state.get("_redirect_url", PROLIFIC_COMPLETE_URL)

    st.success("All done — returning you…")
    st.link_button("Click here if you are not redirected", url)

    # JS redirect; window.top handles embedded contexts
    components.html(
        f"""
        <script>
          window.top.location.href = "{url}";
        </script>
        """,
        height=0,
    )
    st.stop()

def arm_redirect(url: str = PROLIFIC_COMPLETE_URL, reason: str = ""):
    """Arm a redirect and rerun so the redirect executes at top-of-script deterministically."""
    st.session_state["_redirect_now"] = True
    st.session_state["_redirect_url"] = url
    st.session_state["_redirect_reason"] = reason
    st.rerun()

# ============================================================
# 2) Prolific parameters (capture + enforce)
# ============================================================
params = st.query_params
st.session_state.setdefault("PROLIFIC_PID", params.get("PROLIFIC_PID"))
st.session_state.setdefault("STUDY_ID", params.get("STUDY_ID"))
st.session_state.setdefault("SESSION_ID", params.get("SESSION_ID"))

if not st.session_state["PROLIFIC_PID"]:
    st.error("Missing PROLIFIC_PID. Please start this study from Prolific.")
    st.stop()

# Storage identifier is Prolific PID
st.session_state.setdefault("storage_id", st.session_state["PROLIFIC_PID"])

# ============================================================
# 3) Page config
# ============================================================
st.set_page_config(page_title="Interview", page_icon=config.AVATAR_INTERVIEWER)

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
# 7) Session state init
# ============================================================
st.session_state.setdefault("interview_active", True)
st.session_state.setdefault("messages", [])

if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()
    st.session_state.start_time_file_names = time.strftime(
        "%Y_%m_%d_%H_%M_%S", time.localtime(st.session_state.start_time)
    )

# ============================================================
# 8) Debug panel (so you can SEE if redirect is armed / IDs loaded)
# ============================================================
with st.sidebar:
    st.markdown("### Debug")
    st.write("PROLIFIC_PID:", st.session_state.get("PROLIFIC_PID"))
    st.write("STUDY_ID:", st.session_state.get("STUDY_ID"))
    st.write("SESSION_ID:", st.session_state.get("SESSION_ID"))
    st.write("storage_id:", st.session_state.get("storage_id"))
    st.write("redirect_armed:", bool(st.session_state.get("_redirect_now")))
    if st.session_state.get("_redirect_reason"):
        st.write("redirect_reason:", st.session_state.get("_redirect_reason"))
    st.write("redirect_url:", st.session_state.get("_redirect_url", PROLIFIC_COMPLETE_URL))

# ============================================================
# 9) Completion check (keyed by storage_id)
# ============================================================
interview_previously_completed = check_if_interview_completed(
    config.TIMES_DIRECTORY, st.session_state["storage_id"]
)

if interview_previously_completed and not st.session_state.messages:
    st.session_state.interview_active = False
    st.markdown("Interview already completed.")
    # Optional: you could auto-redirect here if desired:
    # arm_redirect(reason="already_completed")

# ============================================================
# 10) Quit button (always arms redirect even if save fails)
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
            arm_redirect(reason="quit_clicked")

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

    # Backup write (keyed by storage_id)
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

            # Always store the raw assistant output
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

            # If a closing code appears: show closing msg, final save, then redirect
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

                    arm_redirect(reason=f"closing_code:{code}")
