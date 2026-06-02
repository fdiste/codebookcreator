import json
import re
from io import BytesIO

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup


st.set_page_config(page_title="QSF Codebook Generator", layout="wide")

st.title("Qualtrics QSF to Codebook Generator")

st.write(
    "Upload a Qualtrics .qsf file. This app will create a draft codebook "
    "with VARIABLE NAME, QUESTION, VALUE, and LABEL columns."
)


def clean_html(text):
    """
    Qualtrics question text often contains HTML.
    This removes the HTML and keeps plain readable text.
    """
    if text is None:
        return ""

    soup = BeautifulSoup(str(text), "html.parser")
    clean_text = soup.get_text(" ", strip=True)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text


def parse_qsf(qsf_json):
    """
    This reads the Qualtrics QSF JSON and creates codebook rows.
    """
    rows = []

    survey_elements = qsf_json.get("SurveyElements", [])

    for element in survey_elements:
        # In Qualtrics QSF files, survey questions usually have Element == "SQ"
        if element.get("Element") != "SQ":
            continue

        payload = element.get("Payload", {})

        qid = payload.get("QuestionID", "")
        question_type = payload.get("QuestionType", "")
        selector = payload.get("Selector", "")

        variable_name = (
            payload.get("DataExportTag")
            or payload.get("QuestionName")
            or qid
        )

        question_text = clean_html(payload.get("QuestionText", ""))

        # Multiple choice questions
        if question_type == "MC":
            choices = payload.get("Choices", {})
            recode_values = payload.get("RecodeValues", {})

            for choice_id, choice_info in choices.items():
                value = recode_values.get(str(choice_id), str(choice_id))
                label = clean_html(choice_info.get("Display", ""))

                rows.append({
                    "VARIABLE NAME": variable_name,
                    "QUESTION": question_text,
                    "VALUE": value,
                    "LABEL": label,
                    "QUESTION TYPE": question_type,
                    "SELECTOR": selector,
                    "QID": qid,
                })

        # Open text questions
        elif question_type == "TE":
            rows.append({
                "VARIABLE NAME": variable_name,
                "QUESTION": question_text,
                "VALUE": "[open-ended]",
                "LABEL": "",
                "QUESTION TYPE": question_type,
                "SELECTOR": selector,
                "QID": qid,
            })

        # Matrix/table questions
        elif question_type == "Matrix":
            choices = payload.get("Choices", {})
            answers = payload.get("Answers", {})
            recode_values = payload.get("RecodeValues", {})

            for choice_id, choice_info in choices.items():
                row_text = clean_html(choice_info.get("Display", ""))
                matrix_variable_name = f"{variable_name}_{choice_id}"

                full_question = question_text
                if row_text:
                    full_question = f"{question_text} — {row_text}"

                for answer_id, answer_info in answers.items():
                    value = recode_values.get(str(answer_id), str(answer_id))
                    label = clean_html(answer_info.get("Display", ""))

                    rows.append({
                        "VARIABLE NAME": matrix_variable_name,
                        "QUESTION": full_question,
                        "VALUE": value,
                        "LABEL": label,
                        "QUESTION TYPE": question_type,
                        "SELECTOR": selector,
                        "QID": qid,
                    })

        # Other question types for now
        else:
            rows.append({
                "VARIABLE NAME": variable_name,
                "QUESTION": question_text,
                "VALUE": "",
                "LABEL": "",
                "QUESTION TYPE": question_type,
                "SELECTOR": selector,
                "QID": qid,
            })

    return pd.DataFrame(rows)


uploaded_file = st.file_uploader("Upload a Qualtrics .qsf file", type=["qsf", "json"])

if uploaded_file is not None:
    try:
        qsf_json = json.load(uploaded_file)
    except Exception as error:
        st.error(f"Could not read this file as a QSF/JSON file: {error}")
        st.stop()

    st.success("File uploaded successfully.")

    codebook_df = parse_qsf(qsf_json)

    if codebook_df.empty:
        st.warning("No survey questions were found.")
        st.stop()

    st.subheader("Draft codebook")

    edited_df = st.data_editor(
        codebook_df,
        use_container_width=True,
        num_rows="dynamic",
        height=500
    )

    st.subheader("Download")

    core_columns = ["VARIABLE NAME", "QUESTION", "VALUE", "LABEL"]
    core_df = edited_df[core_columns]

    csv_data = core_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download codebook as CSV",
        data=csv_data,
        file_name="codebook.csv",
        mime="text/csv"
    )

else:
    st.info("Upload a .qsf file to begin.")
