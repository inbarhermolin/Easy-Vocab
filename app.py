import hashlib
import html
import json
import os
from datetime import datetime

import gspread
import google.generativeai as genai
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_autorefresh import st_autorefresh
from gspread.exceptions import APIError


st.set_page_config(
    page_title="Private Vocabulary Portal",
    page_icon="📚",
    layout="centered",
)

# Modern and welcoming styling.
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;600;700&family=Heebo:wght@400;600;700&display=swap');
    .block-container {
        max-width: 1020px;
        padding-top: 2.2rem;
        padding-bottom: 2rem;
    }
    html, body, [data-testid="stAppViewContainer"] {
        font-family: "Assistant", "Heebo", sans-serif;
    }
    h1, h2, h3, p, label {
        color: var(--text-color) !important;
    }
    .big-card {
        background: color-mix(in srgb, var(--secondary-background-color) 82%, var(--background-color) 18%);
        border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
        border-radius: 16px;
        padding: 1rem 1.2rem;
        margin-top: 0.6rem;
        margin-bottom: 0.8rem;
    }
    .welcome-card {
        background: linear-gradient(
            135deg,
            color-mix(in srgb, var(--primary-color) 25%, transparent),
            color-mix(in srgb, #14b8a6 20%, transparent)
        );
        border: 1px solid color-mix(in srgb, var(--text-color) 15%, transparent);
        border-radius: 16px;
        padding: 1rem 1.1rem;
        margin-bottom: 1rem;
    }
    .table-header-row {
        display: grid;
        grid-template-columns: 56px 1.2fr 2fr 2.8fr;
        gap: 0.65rem;
        padding: 0.65rem 0.8rem;
        margin-bottom: 0.45rem;
        border-radius: 12px;
        background: color-mix(in srgb, var(--primary-color) 12%, transparent);
        font-weight: 700;
        border: 1px solid color-mix(in srgb, var(--text-color) 20%, transparent);
        position: sticky;
        top: 0.5rem;
        z-index: 5;
        backdrop-filter: blur(6px);
    }
    .table-header-row > div {
        text-align: center;
    }
    .table-row {
        display: grid;
        grid-template-columns: 56px 1.2fr 2fr 2.8fr;
        gap: 0.65rem;
        align-items: start;
        padding: 0.75rem 0.8rem;
        margin-bottom: 0.15rem;
        border-radius: 12px;
        border: 1px solid color-mix(in srgb, var(--text-color) 15%, transparent);
    }
    .row-divider {
        height: 1px;
        margin: 0.15rem 0.4rem 0.5rem 0.4rem;
        background: color-mix(in srgb, var(--text-color) 30%, transparent);
        border-radius: 999px;
    }
    .row-even {
        background: color-mix(in srgb, var(--secondary-background-color) 68%, transparent);
    }
    .row-odd {
        background: color-mix(in srgb, var(--secondary-background-color) 45%, transparent);
    }
    .word-cell {
        font-size: 1.12rem;
        font-weight: 700;
        color: color-mix(in srgb, var(--primary-color) 85%, #14b8a6 15%);
    }
    .hebrew-text {
        direction: rtl;
        text-align: right;
        unicode-bidi: plaintext;
    }
    .english-text {
        direction: ltr;
        text-align: left;
        unicode-bidi: plaintext;
        opacity: 0.95;
        margin-top: 0.35rem;
    }
    .usage-stack {
        line-height: 1.45;
        white-space: pre-wrap;
    }
    .speak-cell {
        display: flex;
        justify-content: center;
        align-items: center;
        padding-top: 0.05rem;
    }
    .speak-button {
        width: 34px;
        height: 34px;
        border-radius: 50%;
        border: 1px solid color-mix(in srgb, var(--text-color) 24%, transparent);
        background: color-mix(in srgb, var(--secondary-background-color) 70%, transparent);
        color: var(--text-color);
        font-size: 0.95rem;
        cursor: pointer;
    }
    .speak-button:hover {
        background: color-mix(in srgb, var(--primary-color) 20%, transparent);
    }
    div[data-testid="stButton"] > button {
        border-radius: 999px;
        border: 1px solid color-mix(in srgb, var(--text-color) 22%, transparent);
        padding: 0.45rem 1.1rem;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Private Vocabulary Portal")
st.markdown(
    """
    <div class="welcome-card">
      <b>Welcome</b><br/>
      Search your personal vocabulary, filter by lesson, and sort the table your way.
    </div>
    """,
    unsafe_allow_html=True,
)

student_name = st.text_input(
    "Student Name",
    placeholder="e.g., John Smith",
    key="student_name_input",
).strip()
search_clicked = st.button("Search", use_container_width=True, key="student_search_button")


def format_error(exc: Exception) -> str:
    cause = getattr(exc, "__cause__", None)
    target = cause if cause is not None else exc
    message = str(target).strip()
    return message if message else repr(target)


def require_session_defaults() -> None:
    st.session_state.setdefault("active_student_name", "")
    st.session_state.setdefault("sheet_df", None)
    st.session_state.setdefault("sheet_signature", None)
    st.session_state.setdefault("last_loaded_at", None)
    st.session_state.setdefault("admin_translation", "")
    st.session_state.setdefault("admin_usage_example", "")
    st.session_state.setdefault("append_notice", "")


def get_worksheet():
    gsheets_cfg = st.secrets["connections"]["gsheets"]
    service_account = dict(gsheets_cfg["service_account"])
    spreadsheet_url = gsheets_cfg["spreadsheet"]
    client = gspread.service_account_from_dict(service_account)
    return client.open_by_url(spreadsheet_url).get_worksheet(0)


def pull_sheet_snapshot() -> tuple[pd.DataFrame, str]:
    worksheet = get_worksheet()
    values = worksheet.get_all_values()
    if not values:
        return pd.DataFrame(), "empty"

    headers = values[0]
    rows = values[1:]
    df = pd.DataFrame(rows, columns=headers)
    signature_payload = json.dumps(
        {"row_count": len(rows), "last_row": rows[-1] if rows else []},
        ensure_ascii=False,
    )
    signature = hashlib.sha256(signature_payload.encode("utf-8")).hexdigest()
    return df, signature


def refresh_data(force: bool = False) -> bool:
    df, signature = pull_sheet_snapshot()
    previous_signature = st.session_state.get("sheet_signature")
    has_changed = signature != previous_signature

    if force or has_changed or st.session_state.get("sheet_df") is None:
        st.session_state["sheet_df"] = df
        st.session_state["sheet_signature"] = signature
        st.session_state["last_loaded_at"] = datetime.now().strftime("%H:%M:%S")
        return True
    return False


def generate_vocab_with_ai(word: str) -> tuple[str, str]:
    ai_cfg = st.secrets.get("ai", {})
    api_key = ai_cfg.get("gemini_api_key") or ai_cfg.get("api_key") or os.environ.get(
        "GEMINI_API_KEY"
    )
    preferred_model = ai_cfg.get("model")

    if not api_key:
        raise RuntimeError(
            "AI is not configured. Add [ai].gemini_api_key in secrets.toml or set GEMINI_API_KEY."
        )

    prompt = (
        "You are a vocabulary assistant for language learners. "
        "Given one word, return strict JSON only with keys "
        "translation_definition and usage_example. "
        "Keep it concise, clear, and student-friendly. "
        "The usage_example must contain: "
        "1) a Hebrew sentence using the word, then "
        "2) its English translation on the next line prefixed with 'EN: '."
    )

    genai.configure(api_key=api_key)
    available_models = list(genai.list_models())
    generation_models = [
        m for m in available_models if "generateContent" in (m.supported_generation_methods or [])
    ]
    if not generation_models:
        raise RuntimeError("No Gemini models with generateContent support were found.")

    selected_model_name = generation_models[0].name
    if preferred_model:
        preferred_normalized = preferred_model.replace("models/", "")
        for model_info in generation_models:
            model_name = model_info.name
            model_normalized = model_name.replace("models/", "")
            if preferred_model in (model_name, model_normalized) or preferred_normalized in (
                model_name,
                model_normalized,
            ):
                selected_model_name = model_name
                break

    model_client = genai.GenerativeModel(selected_model_name)
    response = model_client.generate_content(
        f"{prompt}\n\nWord: {word}",
        generation_config={"temperature": 0.3},
    )
    content = (response.text or "").strip()
    if content.startswith("```"):
        content = content.strip("`")
        content = content.replace("json\n", "", 1).strip()

    parsed = json.loads(content)
    return (
        parsed.get("translation_definition", "").strip(),
        parsed.get("usage_example", "").strip(),
    )


def append_word_row(student: str, lesson: str, word: str, translation: str, example: str) -> None:
    worksheet = get_worksheet()
    worksheet.append_row([student, lesson, word, translation, example], value_input_option="USER_ENTERED")


def split_usage_example(value: str) -> tuple[str, str]:
    lines = [line.strip() for line in str(value).splitlines() if line.strip()]
    hebrew_line = lines[0] if lines else ""
    english_line = ""
    for line in lines[1:]:
        if line.upper().startswith("EN:"):
            english_line = line[3:].strip()
            break
    if not english_line and len(lines) > 1:
        english_line = lines[1]
    return hebrew_line, english_line


def render_vocab_row(row: pd.Series, idx: int) -> None:
    hebrew_example, english_example = split_usage_example(row["Usage Example"])
    word_text = str(row["Word"])
    cols = st.columns([0.55, 1.2, 2, 2.8], gap="small")
    with cols[0]:
        safe_word = json.dumps(word_text)
        components.html(
            f"""
            <button
              style="
                width:34px;height:34px;border-radius:50%;
                border:1px solid rgba(148,163,184,0.45);
                background:transparent;color:inherit;cursor:pointer;
              "
              onclick='(() => {{
                const text = {safe_word};
                const u = new SpeechSynthesisUtterance(text);
                u.lang = /[\\u0590-\\u05FF]/.test(text) ? "he-IL" : "en-US";
                u.rate = 0.92;
                window.speechSynthesis.cancel();
                window.speechSynthesis.speak(u);
              }})()'
              title="Hear word"
            >🔊</button>
            """,
            height=38,
            scrolling=False,
        )
    with cols[1]:
        st.markdown(
            f'<div class="word-cell hebrew-text">{html.escape(word_text)}</div>',
            unsafe_allow_html=True,
        )
    with cols[2]:
        st.markdown(
            f'<div class="hebrew-text">{html.escape(str(row["Translation/Definition"]))}</div>',
            unsafe_allow_html=True,
        )
    with cols[3]:
        st.markdown(
            (
                '<div class="usage-stack">'
                f'<div class="hebrew-text">{html.escape(hebrew_example)}</div>'
                f'<div class="english-text">{html.escape(english_example)}</div>'
                "</div>"
            ),
            unsafe_allow_html=True,
        )
    st.divider()


def render_admin_panel() -> None:
    st.sidebar.markdown("## Teacher Admin")
    admin_password = st.secrets.get("admin", {}).get("password")
    if not admin_password:
        st.sidebar.info("Set [admin].password in secrets.toml to enable admin mode.")
        return

    provided_password = st.sidebar.text_input("Admin password", type="password")
    if provided_password != admin_password:
        st.sidebar.caption("Enter password to unlock admin tools.")
        return

    st.sidebar.success("Admin unlocked")
    with st.sidebar.form("admin_add_word_form"):
        admin_student = st.text_input("Student Name", key="admin_student_input")
        admin_lesson = st.text_input("Lesson", value="1", key="admin_lesson_input")
        admin_word = st.text_input("New Word", key="admin_word_input")
        generate_clicked = st.form_submit_button(
            "Generate Translation + Example with AI",
            use_container_width=True,
        )

    if generate_clicked:
        if not admin_word.strip():
            st.sidebar.warning("Please enter a word first.")
        else:
            try:
                with st.status("Generating with AI...", expanded=False) as status:
                    translation, usage_example = generate_vocab_with_ai(admin_word.strip())
                    status.update(label="AI content generated.", state="complete")
                st.session_state["admin_translation"] = translation
                st.session_state["admin_usage_example"] = usage_example
                st.session_state["admin_word_save_input"] = admin_word.strip()
                st.session_state["admin_translation_save_input"] = translation
                st.session_state["admin_example_save_input"] = usage_example
                st.sidebar.success("AI content generated. Review and save below.")
            except Exception as exc:
                st.sidebar.error(f"AI generation failed: {format_error(exc)}")

    with st.sidebar.form("admin_save_word_form"):
        final_student = st.text_input(
            "Student Name (save)",
            value=admin_student if "admin_student" in locals() else "",
            key="admin_student_save_input",
        )
        final_lesson = st.text_input(
            "Lesson (save)",
            value=admin_lesson if "admin_lesson" in locals() else "1",
            key="admin_lesson_save_input",
        )
        final_word = st.text_input(
            "Word (save)",
            value=admin_word if "admin_word" in locals() else "",
            key="admin_word_save_input",
        )
        final_translation = st.text_area(
            "Translation/Definition",
            value=st.session_state.get("admin_translation", ""),
            height=90,
            key="admin_translation_save_input",
        )
        final_example = st.text_area(
            "Usage Example",
            value=st.session_state.get("admin_usage_example", ""),
            height=110,
            key="admin_example_save_input",
        )
        save_clicked = st.form_submit_button("Append to Google Sheet", use_container_width=True)

    if save_clicked:
        if not final_student.strip() or not final_lesson.strip() or not final_word.strip():
            st.sidebar.warning("Student Name, Lesson, and Word are required.")
            return
        if not final_translation.strip() or not final_example.strip():
            st.sidebar.warning("Generate or enter Translation/Definition and Usage Example.")
            return

        try:
            append_word_row(
                student=final_student.strip(),
                lesson=final_lesson.strip(),
                word=final_word.strip(),
                translation=final_translation.strip(),
                example=final_example.strip(),
            )
            refresh_data(force=True)
            st.session_state["active_student_name"] = final_student.strip()
            # Reset table controls so the newly added row is immediately visible.
            st.session_state["lesson_filter"] = "All"
            st.session_state["quick_search"] = ""
            st.session_state["word_filter"] = ""
            st.session_state["translation_filter"] = ""
            st.session_state["example_filter"] = ""
            st.session_state["page_number"] = 1
            st.session_state["append_notice"] = "New word added and table refreshed."
            st.sidebar.success("New row added to Google Sheet.")
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f"Append failed: {format_error(exc)}")


require_session_defaults()
render_admin_panel()

if search_clicked:
    if student_name:
        st.session_state["active_student_name"] = student_name
        try:
            with st.spinner("Loading words..."):
                refresh_data(force=True)
        except Exception as exc:
            st.error(f"Error loading data: {format_error(exc)}")
            st.stop()
    else:
        st.warning("Please enter a student name.")
        st.stop()

active_student_name = st.session_state.get("active_student_name", "")
sheet_df = st.session_state.get("sheet_df")

if active_student_name:
    if st.session_state.get("append_notice"):
        st.success(st.session_state["append_notice"])
        st.session_state["append_notice"] = ""
    st.caption(f"Student: {active_student_name}")
    refresh_col, check_col, auto_col, time_col = st.columns([1, 1, 1, 2])
    with refresh_col:
        manual_refresh = st.button("Refresh Data", use_container_width=True, key="manual_refresh")
    with check_col:
        check_updates = st.button("Check Updates", use_container_width=True, key="check_updates")
    with auto_col:
        auto_updates = st.toggle("Auto", value=True, key="auto_updates")
    with time_col:
        last_loaded = st.session_state.get("last_loaded_at") or "-"
        st.caption(f"Last loaded: {last_loaded}")

    if auto_updates:
        # Periodic lightweight checks to sync new teacher-added words for students.
        st_autorefresh(interval=5000, key="student_auto_refresh")

    try:
        if manual_refresh:
            with st.spinner("Refreshing from Google Sheets..."):
                refresh_data(force=True)
            st.success("Data refreshed.")
        elif check_updates:
            with st.spinner("Checking for changes..."):
                changed = refresh_data(force=False)
            if changed:
                st.success("Sheet changed. Table updated.")
            else:
                st.info("No changes detected.")
        elif auto_updates:
            refresh_data(force=False)
    except Exception as exc:
        root_error = format_error(exc)
        if isinstance(exc, PermissionError) or (
            isinstance(exc, APIError) and "403" in root_error
        ) or ("403" in root_error):
            service_email = st.secrets["connections"]["gsheets"]["service_account"]["client_email"]
            st.error(
                "Google Sheets access denied (403). "
                f"Share the sheet with: {service_email}. Details: {root_error}"
            )
        else:
            st.error(f"Error refreshing data: {root_error}")
        st.stop()

    sheet_df = st.session_state.get("sheet_df")
    if sheet_df is None:
        st.info("Click Search to load your vocabulary.")
        st.stop()

    required_columns = [
        "Student Name",
        "Lesson",
        "Word",
        "Translation/Definition",
        "Usage Example",
    ]
    missing_columns = [col for col in required_columns if col not in sheet_df.columns]
    if missing_columns:
        st.error("The sheet structure is invalid. Missing columns: " + ", ".join(missing_columns))
        st.stop()

    user_df = sheet_df[
        sheet_df["Student Name"].astype(str).str.strip().str.casefold()
        == active_student_name.casefold()
    ][["Lesson", "Word", "Translation/Definition", "Usage Example"]]

    if user_df.empty:
        st.warning("Name not found")
        st.stop()

    st.markdown('<div class="big-card">', unsafe_allow_html=True)
    st.subheader("Vocabulary Table")
    st.caption("Search, filter, and copy example sentences quickly.")

    lessons = sorted(user_df["Lesson"].dropna().astype(str).unique().tolist())
    lesson_options = ["All"] + lessons
    selected_lesson = st.selectbox("Lesson", lesson_options, index=0, key="lesson_filter")
    quick_search = st.text_input(
        "Search word / translation / usage",
        value="",
        key="quick_search",
        placeholder="Start typing to filter in real time...",
    ).strip().casefold()
    word_filter = st.text_input("Filter word", value="", key="word_filter").strip().casefold()
    translation_filter = st.text_input(
        "Filter translation/definition",
        value="",
        key="translation_filter",
    ).strip().casefold()
    example_filter = st.text_input(
        "Filter usage example",
        value="",
        key="example_filter",
    ).strip().casefold()
    sort_by = st.selectbox(
        "Order by",
        ["Lesson", "Word", "Translation/Definition", "Usage Example"],
        index=0,
        key="sort_by",
    )
    sort_direction = st.radio(
        "Direction",
        ["Ascending", "Descending"],
        horizontal=True,
        key="sort_direction",
    )

    if selected_lesson != "All":
        user_df = user_df[user_df["Lesson"].astype(str) == selected_lesson]
    if word_filter:
        user_df = user_df[
            user_df["Word"].astype(str).str.casefold().str.contains(word_filter, na=False)
        ]
    if translation_filter:
        user_df = user_df[
            user_df["Translation/Definition"]
            .astype(str)
            .str.casefold()
            .str.contains(translation_filter, na=False)
        ]
    if example_filter:
        user_df = user_df[
            user_df["Usage Example"]
            .astype(str)
            .str.casefold()
            .str.contains(example_filter, na=False)
        ]
    if quick_search:
        user_df = user_df[
            user_df["Word"].astype(str).str.casefold().str.contains(quick_search, na=False)
            | user_df["Translation/Definition"]
            .astype(str)
            .str.casefold()
            .str.contains(quick_search, na=False)
            | user_df["Usage Example"]
            .astype(str)
            .str.casefold()
            .str.contains(quick_search, na=False)
        ]

    user_df = user_df.sort_values(
        by=sort_by,
        ascending=(sort_direction == "Ascending"),
        kind="stable",
    )
    total_rows = len(user_df)
    page_size_col, page_col = st.columns([1, 1])
    with page_size_col:
        page_size = st.selectbox("Rows per page", [10, 20, 30, 50], index=1, key="page_size")

    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    with page_col:
        current_page = st.selectbox(
            "Page",
            list(range(1, total_pages + 1)),
            index=0,
            key="page_number",
        )

    start_idx = (current_page - 1) * page_size
    end_idx = start_idx + page_size
    paged_df = user_df.iloc[start_idx:end_idx]

    st.success(
        f"Showing {len(paged_df)} of {total_rows} words "
        f"(page {current_page}/{total_pages})."
    )
    st.markdown(
        """
        <div class="table-header-row">
            <div>Audio</div>
            <div>Word</div>
            <div>Translation / Definition</div>
            <div>Usage Example</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    for idx, row in paged_df[["Word", "Translation/Definition", "Usage Example"]].reset_index(
        drop=True
    ).iterrows():
        render_vocab_row(row, idx)
    st.markdown("</div>", unsafe_allow_html=True)
else:
    st.info("Enter a student name and click Search.")
