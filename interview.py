import streamlit as st
import time
import os
import config
from utils import (
    check_password,
    check_if_interview_completed,
    save_interview_data,
)

# ==============================
# Prolific URL parameters
# ==============================
params = st.query_params
st.session_state.setdefault("PROLIFIC_PID", params.get("PROLIFIC_PID"))
st.session_state.setdefault("STUDY_ID", params.get("STUDY_ID"))
st.session_state.setdefault("SESSION_ID", params.get("SESSION_ID"))

if not st.session_state["PROLIFIC_PID"]:
    st.error("This study must be started from Prolific.")
    st.stop()

# Use Prolific PID as storage identifier
st.session_state.setdefault("storage_id", st.session_state["PROLIFIC_PID"])

# ==============================
# Prolific completion redirect
# ==============================
PROLIFIC_COMPLETE_URL = "https://app.prolific.com/submissions/complete?cc=C1QA3C1R"

def redirect_to_prolific():
    st.success("All done — returning you to Prolific…")
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={PROLIFIC_COMPLETE_URL}">',
        unsafe_allow_html=True,
    )
    st.stop()

# ==============================
# API selection
# ==============================
if "gpt" in config.MODEL.lower():
    from openai import OpenAI
    api = "openai"
elif "claude" in config.MODEL.lower():
    import anthropic
    api = "anthropic"
else:
    raise ValueError("Unsupported model")

# ==============================
# Page config
# ==============================
st.set_page_config(page_title="Interview", page_icon=config.AVATAR_INTERVIEWER)

# ==============================
# Login logic (UNCHANGED)
# ==============================
if config.LOGINS:
    pwd_correct, username = check_password()
    if not pwd_correct:
        st.stop()
    st.session_state.username = username
else:
    st.session_state.username = "testaccount"

# ==============================
# Directories
# ==============================
for d in [
    config.TRANSCRIPTS_DIRECTORY,
    config.TIMES_DIRECTORY,
    config.BACKUPS_DIRECTORY,
]:
    os.makedirs(d, exist_ok=True)

# ==============================
# Session state init
# ==============================
st.session_state.setdefault("interview_active", True)
st.session_state.setdefault("messages", [])

if "start_time" not in st.session_state:
    st.session_state.start_time = time.time()
    st.session_state.start_time_file_names = time.strftime(
        "%Y_%m_%d_%H_%M_%S", time.localtime(st.session_state.start_time)
    )

# ==============================
# Check if already completed
# ==============================
if check_if_interview_completed(
    config.TIMES_DIRECTORY, st.session_state["storage_id"]
) and not st.session_state.messages:
    st.session_state.interview_active = False
    st.markdown("Interview already completed.")

# ==============================
# Quit button
# ==============================
_, col_quit = st.columns([0.85, 0.15])
with col_quit:
    if st.session_state.interview_active and st.button("Quit"):
        st.session_state.interview_active = False
        st.session_state.messages.append(
            {"role": "assistant", "content": "You have cancelled the interview."}
        )
        save_interview_data(
            st.session_state["storage_id"],
            config.TRANSCRIPTS_DIRECTORY,
            config.TIMES_DIRECTORY,
        )
        redirect_to_prolific()

# ==============================
# Display conversation history
# ==============================
for msg in st.session_state.messages[1:]:
    avatar = (
        config.AVATAR_INTERVIEWER
        if msg["role"] == "assistant"
        else config.AVATAR_RESPONDENT
    )
    if not any(code in msg["content"] for code in config.CLOSING_MESSAGES):
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

# ==============================
# API client
# ==============================
if api == "openai":
    client = OpenAI(api_key=st.secrets["API_KEY_OPENAI"])
    api_kwargs = {"stream": True}
else:
    client = anthropic.Anthropic(api_key=st.secrets["API_KEY_ANTHROPIC"])
    api_kwargs = {"system": config.SYSTEM_PROMPT}

api_kwargs.update(
    {
        "messages": st.session_state.messages,
        "model": config.MODEL,
        "max_tokens": config.MAX_OUTPUT_TOKENS,
    }
)
if config.TEMPERATURE is not None:
    api_kwargs["temperature"] = config.TEMPERATURE

# ==============================
# Initial system prompt
# ==============================
if not st.session_state.messages:
    if api == "openai":
        st.session_state.messages.append(
            {"role": "system", "content": config.SYSTEM_PROMPT}
        )
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            stream = client.chat.completions.create(**api_kwargs)
            msg = st.write_stream(stream)
    else:
        st.session_state.messages.append({"role": "user", "content": "Hi"})
        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            msg = ""
            placeholder = st.empty()
            with client.messages.stream(**api_kwargs) as stream:
                for delta in stream.text_stream:
                    if delta:
                        msg += delta
                        placeholder.markdown(msg + "▌")
            placeholder.markdown(msg)

    st.session_state.messages.append({"role": "assistant", "content": msg})

    save_interview_data(
        username=st.session_state["storage_id"],
        transcripts_directory=config.BACKUPS_DIRECTORY,
        times_directory=config.BACKUPS_DIRECTORY,
        file_name_addition_transcript=f"_started_{st.session_state.start_time_file_names}",
        file_name_addition_time=f"_started_{st.session_state.start_time_file_names}",
    )

# ==============================
# Main chat loop
# ==============================
if st.session_state.interview_active:
    if user_msg := st.chat_input("Your message here"):
        st.session_state.messages.append({"role": "user", "content": user_msg})
        with st.chat_message("user", avatar=config.AVATAR_RESPONDENT):
            st.markdown(user_msg)

        with st.chat_message("assistant", avatar=config.AVATAR_INTERVIEWER):
            placeholder = st.empty()
            response = ""

            if api == "openai":
                stream = client.chat.completions.create(**api_kwargs)
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        response += delta
                        if len(response) > 5:
                            placeholder.markdown(response + "▌")
                    if any(code in response for code in config.CLOSING_MESSAGES):
                        placeholder.empty()
                        break
            else:
                with client.messages.stream(**api_kwargs) as stream:
                    for delta in stream.text_stream:
                        if delta:
                            response += delta
                            if len(response) > 5:
                                placeholder.markdown(response + "▌")
                        if any(code in response for code in config.CLOSING_MESSAGES):
                            placeholder.empty()
                            break

            st.session_state.messages.append(
                {"role": "assistant", "content": response}
            )

            for code, closing_msg in config.CLOSING_MESSAGES.items():
                if code in response:
                    st.session_state.interview_active = False
                    st.markdown(closing_msg)

                    deadline = time.time() + 10
                    saved = False
                    while not saved and time.time() < deadline:
                        save_interview_data(
                            st.session_state["storage_id"],
                            config.TRANSCRIPTS_DIRECTORY,
                            config.TIMES_DIRECTORY,
                        )
                        saved = check_if_interview_completed(
                            config.TRANSCRIPTS_DIRECTORY,
                            st.session_state["storage_id"],
                        )
                        time.sleep(0.1)

                    redirect_to_prolific()
