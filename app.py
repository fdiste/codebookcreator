import json
import re

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup


st.set_page_config(page_title="QSF Codebook Generator", layout="wide")

st.title("Qualtrics QSF to Codebook Generator")

st.write(
    "Upload a Qualtrics `.qsf` file. This app will create a draft codebook "
    "with VARIABLE NAME, QUESTION, VALUE, and LABEL columns."
)


# ------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------

def clean_html(text):
    """
    Removes HTML from Qualtrics text using BeautifulSoup.
    Qualtrics often stores question and answer text with HTML tags.
    """
    if text is None:
        return ""

    soup = BeautifulSoup(str(text), "html.parser")
    clean_text = soup.get_text(" ", strip=True)

    # Normalize whitespace
    clean_text = re.sub(r"\s+", " ", clean_text).strip()

    return clean_text


def get_choice_variable_name(payload, base_variable_name, choice_id):
    """
    For multi-select questions, Qualtrics may store custom variable names
    for each answer option in different places. This checks common locations.

    These names are often created in Qualtrics by changing variable naming
    for each answer option.
    """

    choice_id = str(choice_id)

    # Common location 1: VariableNaming
    variable_naming = payload.get("VariableNaming", {})
    if isinstance(variable_naming, dict):
        if choice_id in variable_naming:
            return str(variable_naming[choice_id])

    # Common location 2: ChoiceDataExportTags
    choice_export_tags = payload.get("ChoiceDataExportTags", {})
    if isinstance(choice_export_tags, dict):
        if choice_id in choice_export_tags:
            return str(choice_export_tags[choice_id])

    # Common location 3: inside the Choices object
    choices = payload.get("Choices", {})
    choice_info = choices.get(choice_id, {})

    if isinstance(choice_info, dict):
        for possible_key in ["VariableName", "DataExportTag", "ExportTag"]:
            if choice_info.get(possible_key):
                return str(choice_info[possible_key])

    # Fallback if Qualtrics does not provide a custom option name
    return f"{base_variable_name}_{choice_id}"


def blank_repeated_values(df):
    """
    Makes the downloaded codebook prettier by blanking repeated VARIABLE NAME
    and QUESTION values after the first row.
    """
    pretty_df = df.copy()

    for column in ["VARIABLE NAME", "QUESTION"]:
        if column in pretty_df.columns:
            pretty_df.loc[
                pretty_df[column] == pretty_df[column].shift(),
                column
            ] = ""

    return pretty_df


def parse_qsf(qsf_json):
    """
    Reads a Qualtrics QSF JSON file and creates codebook rows.
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

        # ------------------------------------------------------------
        # Multiple choice questions
        # ------------------------------------------------------------
        if question_type == "MC":
            choices = payload.get("Choices", {})
            recode_values = payload.get("RecodeValues", {})

            # Qualtrics selectors that start with MA are usually
            # multi-answer/check-all-that-apply.
            is_multi_select = str(selector).upper().startswith("MA")

            if is_multi_select:
                # Parent row for the overall multi-select question.
                # Put the Yes/No coding here only once.
                rows.append({
                    "VARIABLE NAME": variable_name,
                    "QUESTION": question_text,
                    "VALUE": "1",
                    "LABEL": "Yes",
                    "QUESTION TYPE": question_type,
                    "SELECTOR": selector,
                    "QID": qid,
                })

                rows.append({
                    "VARIABLE NAME": variable_name,
                    "QUESTION": question_text,
                    "VALUE": "0",
                    "LABEL": "No",
                    "QUESTION TYPE": question_type,
                    "SELECTOR": selector,
                    "QID": qid,
                })

                # Then list each response option's exported variable name.
                # Do not repeat 1/0 coding for every option.
                for choice_id, choice_info in choices.items():
                    option_variable_name = get_choice_variable_name(
                        payload,
                        variable_name,
                        choice_id
                    )

                    option_label = clean_html(choice_info.get("Display", ""))

                    rows.append({
                        "VARIABLE NAME": option_variable_name,
                        "QUESTION": option_label,
                        "VALUE": "",
                        "LABEL": "",
                        "QUESTION TYPE": question_type,
                        "SELECTOR": selector,
                        "QID": qid,
                    })

            else:
                # Regular single-choice question.
                # Use recode values if Qualtrics provides them.
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

        # ------------------------------------------------------------
        # Open text questions
        # ------------------------------------------------------------
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

        # ------------------------------------------------------------
        # Matrix/table questions
        # ------------------------------------------------------------
        elif question_type == "Matrix":
            choices = payload.get("Choices", {})
            answers = payload.get("Answers", {})
            recode_values = payload.get("RecodeValues", {})

            for choice_id, choice_info in choices.items():
                row_text = clean_html(choice_info.get("Display", ""))

                # Try to use Qualtrics variable naming for matrix rows if available.
                matrix_variable_name = get_choice_variable_name(
                    payload,
                    variable_name,
                    choice_id
                )

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

        # ------------------------------------------------------------
        # Drill down questions - basic placeholder/fallback
        # ------------------------------------------------------------
        elif question_type in ["DD", "DrillDown"]:
            rows.append({
                "VARIABLE NAME": variable_name,
                "QUESTION": question_text,
                "VALUE": "",
                "LABEL": "[drill-down question - needs review]",
                "QUESTION TYPE": question_type,
                "SELECTOR": selector,
                "QID": qid,
            })

        # ------------------------------------------------------------
        # Other question types
        # ------------------------------------------------------------
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


# ------------------------------------------------------------
# Streamlit app
# ------------------------------------------------------------

uploaded_file = st.file_uploader(
    "Upload a Qualtrics .qsf file",
    type=["qsf", "json"]
)

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

    st.write(
        "You can edit the table below before downloading. "
        "The download can optionally blank repeated variable names and questions "
        "to make the codebook easier to read."
    )

    edited_df = st.data_editor(
        codebook_df,
        use_container_width=True,
        num_rows="dynamic",
        height=500
    )

    st.subheader("Download")

    blank_repeats = st.checkbox(
        "Blank repeated variable names and questions in downloaded file",
        value=True
    )

    core_columns = ["VARIABLE NAME", "QUESTION", "VALUE", "LABEL"]

    if blank_repeats:
        download_df = blank_repeated_values(edited_df)
    else:
        download_df = edited_df.copy()

    # Only include the four main codebook columns in the CSV download.
    core_df = download_df[core_columns]

    csv_data = core_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download codebook as CSV",
        data=csv_data,
        file_name="codebook.csv",
        mime="text/csv"
    )

    # Optional: also allow downloading the fuller version with metadata.
    full_csv_data = download_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download full codebook with metadata as CSV",
        data=full_csv_data,
        file_name="codebook_full.csv",
        mime="text/csv"
    )

else:
    st.info("Upload a .qsf file to begin.")
