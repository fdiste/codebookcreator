import json
import re
from io import BytesIO

import pandas as pd
import streamlit as st
from bs4 import BeautifulSoup


st.set_page_config(page_title="QSF Codebook Generator", layout="wide")

st.title("Qualtrics QSF to Codebook Generator")

st.write(
    "Upload a Qualtrics `.qsf` file. This app will create a draft codebook "
    "with VARIABLE NAME, QUESTION, VALUE, and LABEL columns."
)

st.info(
    "Privacy note: Uploaded QSF files are processed in memory by this app and "
    "are not intentionally saved by the app code. If this app is hosted on "
    "Streamlit Cloud, uploaded files are still temporarily processed by "
    "Streamlit's servers. Do not upload sensitive or restricted survey "
    "instruments unless this app is running in an approved environment."
)


# ------------------------------------------------------------
# Helper functions: text cleaning
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


# ------------------------------------------------------------
# Helper functions: QSF survey order
# ------------------------------------------------------------

def get_blocks_from_qsf(qsf_json):
    """
    Extracts Qualtrics blocks from the QSF.

    QSF block structure can vary. Sometimes the BL payload is a list.
    Sometimes it is a dictionary with a 'Blocks' key.
    This function tries to handle the common versions.
    """
    blocks = []

    for element in qsf_json.get("SurveyElements", []):
        if element.get("Element") != "BL":
            continue

        payload = element.get("Payload", [])

        # Common case: Payload itself is a list of block objects.
        if isinstance(payload, list):
            blocks.extend(payload)

        # Alternate case: Payload is a dict containing Blocks.
        elif isinstance(payload, dict):
            if isinstance(payload.get("Blocks"), list):
                blocks.extend(payload.get("Blocks"))

            # Less common: Payload itself may act like a block.
            if payload.get("BlockElements"):
                blocks.append(payload)

    return blocks


def get_block_ids_from_survey_flow(qsf_json):
    """
    Attempts to get block order from Qualtrics Survey Flow.

    This is more reliable than raw SurveyElements order when the survey has
    multiple blocks. For complex randomizers/branches, this gives a reasonable
    design-order approximation.
    """
    block_ids = []

    def walk_flow_items(items):
        if not isinstance(items, list):
            return

        for item in items:
            if not isinstance(item, dict):
                continue

            item_type = item.get("Type")
            item_id = item.get("ID")

            if item_type == "Block" and item_id:
                if item_id not in block_ids:
                    block_ids.append(item_id)

            # Survey Flow items can contain nested Flow lists.
            if "Flow" in item:
                walk_flow_items(item.get("Flow"))

            # Some randomizer/branch structures have nested items elsewhere.
            for key in ["SubFlow", "FlowItems"]:
                if key in item:
                    walk_flow_items(item.get(key))

    for element in qsf_json.get("SurveyElements", []):
        if element.get("Element") == "FL":
            payload = element.get("Payload", {})

            if isinstance(payload, dict):
                walk_flow_items(payload.get("Flow", []))
            elif isinstance(payload, list):
                walk_flow_items(payload)

    return block_ids


def get_ordered_question_ids(qsf_json):
    """
    Attempts to get question order from Qualtrics blocks and survey flow.

    Preferred order:
    1. Survey Flow block order, if available
    2. Block order from the BL element
    3. Fallback happens in parse_qsf if this returns no IDs

    Note: surveys with randomization, branches, and complex logic may not have
    one fixed respondent-facing order. This gives a design-order approximation.
    """
    blocks = get_blocks_from_qsf(qsf_json)

    block_id_to_qids = {}
    block_order_from_bl = []

    for block in blocks:
        if not isinstance(block, dict):
            continue

        block_id = block.get("ID") or block.get("BlockID")

        if block_id and block_id not in block_order_from_bl:
            block_order_from_bl.append(block_id)

        qids = []

        for block_element in block.get("BlockElements", []):
            if not isinstance(block_element, dict):
                continue

            if block_element.get("Type") == "Question":
                qid = block_element.get("QuestionID")
                if qid:
                    qids.append(qid)

        if block_id:
            block_id_to_qids[block_id] = qids

    ordered_qids = []

    # First try Survey Flow order.
    flow_block_ids = get_block_ids_from_survey_flow(qsf_json)

    if flow_block_ids:
        for block_id in flow_block_ids:
            for qid in block_id_to_qids.get(block_id, []):
                if qid not in ordered_qids:
                    ordered_qids.append(qid)

    # Then add blocks that were not found in Survey Flow.
    for block_id in block_order_from_bl:
        for qid in block_id_to_qids.get(block_id, []):
            if qid not in ordered_qids:
                ordered_qids.append(qid)

    return ordered_qids


# ------------------------------------------------------------
# Helper functions: codebook rows
# ------------------------------------------------------------

def get_choice_variable_name(payload, base_variable_name, choice_id):
    """
    For multi-select and matrix questions, Qualtrics may store custom variable
    names for each answer option or matrix row in different places.
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


def blank_row():
    """
    Creates an empty row between questions.
    """
    return {
        "VARIABLE NAME": "",
        "QUESTION": "",
        "VALUE": "",
        "LABEL": "",
        "QUESTION TYPE": "",
        "SELECTOR": "",
        "QID": "",
        "IS MAIN QUESTION": False,
    }


def make_row(
    variable_name,
    question,
    value,
    label,
    question_type,
    selector,
    qid,
    is_main_question=False
):
    """
    Creates one standard codebook row.
    """
    return {
        "VARIABLE NAME": variable_name,
        "QUESTION": question,
        "VALUE": value,
        "LABEL": label,
        "QUESTION TYPE": question_type,
        "SELECTOR": selector,
        "QID": qid,
        "IS MAIN QUESTION": is_main_question,
    }


def combine_left_and_right(left_items, right_items, question_type, selector, qid):
    """
    Combines left-side variable/question items with right-side value/label items.

    Used for matrix and multi-select questions where the left side lists
    variables/items and the right side lists a shared response scale.

    Example:

    VARIABLE NAME    QUESTION                  VALUE    LABEL
    Prices           Main matrix question       1       Strongly disagree
    PricesHigh       Prices are higher...       2       Disagree
    PricesQuality    Quality is good...         3       Neither agree nor disagree
                                                4       Agree
                                                5       Strongly agree
    """
    rows = []

    max_rows = max(len(left_items), len(right_items))

    for i in range(max_rows):
        if i < len(left_items):
            variable_name = left_items[i].get("VARIABLE NAME", "")
            question = left_items[i].get("QUESTION", "")
            is_main_question = left_items[i].get("IS MAIN QUESTION", False)
        else:
            variable_name = ""
            question = ""
            is_main_question = False

        if i < len(right_items):
            value = right_items[i].get("VALUE", "")
            label = right_items[i].get("LABEL", "")
        else:
            value = ""
            label = ""

        rows.append(make_row(
            variable_name=variable_name,
            question=question,
            value=value,
            label=label,
            question_type=question_type,
            selector=selector,
            qid=qid,
            is_main_question=is_main_question
        ))

    return rows


# ------------------------------------------------------------
# Main parser
# ------------------------------------------------------------

def parse_qsf(qsf_json):
    """
    Reads a Qualtrics QSF JSON file and creates codebook rows.

    This version attempts to follow survey order using Qualtrics block/survey
    flow order when available.
    """
    all_rows = []

    # Build dictionary of question elements by QID.
    question_elements_by_qid = {}
    raw_question_elements = []

    for element in qsf_json.get("SurveyElements", []):
        if element.get("Element") != "SQ":
            continue

        payload = element.get("Payload", {})
        qid = payload.get("QuestionID") or element.get("PrimaryAttribute")

        if qid:
            question_elements_by_qid[qid] = element

        raw_question_elements.append(element)

    # Try to order questions using Qualtrics block/survey flow order.
    ordered_qids = get_ordered_question_ids(qsf_json)

    ordered_elements = []

    if ordered_qids:
        for qid in ordered_qids:
            if qid in question_elements_by_qid:
                ordered_elements.append(question_elements_by_qid[qid])

        # Add any question elements not found in blocks, just in case.
        already_added_qids = set(ordered_qids)

        for element in raw_question_elements:
            payload = element.get("Payload", {})
            qid = payload.get("QuestionID") or element.get("PrimaryAttribute")

            if qid not in already_added_qids:
                ordered_elements.append(element)
    else:
        # Fallback to raw SurveyElements order.
        ordered_elements = raw_question_elements

    # Parse questions in order.
    for element in ordered_elements:
        payload = element.get("Payload", {})

        qid = payload.get("QuestionID") or element.get("PrimaryAttribute", "")
        question_type = payload.get("QuestionType", "")
        selector = payload.get("Selector", "")

        variable_name = (
            payload.get("DataExportTag")
            or payload.get("QuestionName")
            or qid
        )

        question_text = clean_html(payload.get("QuestionText", ""))

        question_rows = []

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
                # LEFT SIDE:
                # Parent question first, then each option's variable name.
                left_items = [
                    {
                        "VARIABLE NAME": variable_name,
                        "QUESTION": question_text,
                        "IS MAIN QUESTION": True,
                    }
                ]

                for choice_id, choice_info in choices.items():
                    option_variable_name = get_choice_variable_name(
                        payload,
                        variable_name,
                        choice_id
                    )

                    option_label = clean_html(choice_info.get("Display", ""))

                    left_items.append({
                        "VARIABLE NAME": option_variable_name,
                        "QUESTION": option_label,
                        "IS MAIN QUESTION": False,
                    })

                # RIGHT SIDE:
                # Shared Yes/No coding listed once.
                right_items = [
                    {
                        "VALUE": "1",
                        "LABEL": "Yes",
                    },
                    {
                        "VALUE": "0",
                        "LABEL": "No",
                    }
                ]

                question_rows.extend(
                    combine_left_and_right(
                        left_items=left_items,
                        right_items=right_items,
                        question_type=question_type,
                        selector=selector,
                        qid=qid
                    )
                )

            else:
                # Regular single-choice question.
                # No extra parent/question-only row is added.
                # The first value/label is on the same row as the question.
                first_row = True

                for choice_id, choice_info in choices.items():
                    value = recode_values.get(str(choice_id), str(choice_id))
                    label = clean_html(choice_info.get("Display", ""))

                    if first_row:
                        row_variable_name = variable_name
                        row_question = question_text
                        is_main_question = True
                        first_row = False
                    else:
                        row_variable_name = ""
                        row_question = ""
                        is_main_question = False

                    question_rows.append(make_row(
                        variable_name=row_variable_name,
                        question=row_question,
                        value=value,
                        label=label,
                        question_type=question_type,
                        selector=selector,
                        qid=qid,
                        is_main_question=is_main_question
                    ))

        # ------------------------------------------------------------
        # Open text questions
        # ------------------------------------------------------------
        elif question_type == "TE":
            question_rows.append(make_row(
                variable_name=variable_name,
                question=question_text,
                value="[open-ended]",
                label="",
                question_type=question_type,
                selector=selector,
                qid=qid,
                is_main_question=True
            ))

        # ------------------------------------------------------------
        # Matrix/table questions
        # ------------------------------------------------------------
        elif question_type == "Matrix":
            choices = payload.get("Choices", {})
            answers = payload.get("Answers", {})
            recode_values = payload.get("RecodeValues", {})

            # LEFT SIDE:
            # Parent matrix question first, then each matrix row variable.
            left_items = [
                {
                    "VARIABLE NAME": variable_name,
                    "QUESTION": question_text,
                    "IS MAIN QUESTION": True,
                }
            ]

            for choice_id, choice_info in choices.items():
                row_text = clean_html(choice_info.get("Display", ""))

                matrix_variable_name = get_choice_variable_name(
                    payload,
                    variable_name,
                    choice_id
                )

                left_items.append({
                    "VARIABLE NAME": matrix_variable_name,
                    "QUESTION": row_text,
                    "IS MAIN QUESTION": False,
                })

            # RIGHT SIDE:
            # Matrix scale values/labels listed once.
            right_items = []

            for answer_id, answer_info in answers.items():
                value = recode_values.get(str(answer_id), str(answer_id))
                label = clean_html(answer_info.get("Display", ""))

                right_items.append({
                    "VALUE": value,
                    "LABEL": label,
                })

            question_rows.extend(
                combine_left_and_right(
                    left_items=left_items,
                    right_items=right_items,
                    question_type=question_type,
                    selector=selector,
                    qid=qid
                )
            )

        # ------------------------------------------------------------
        # Drill down questions - basic placeholder/fallback
        # ------------------------------------------------------------
        elif question_type in ["DD", "DrillDown"]:
            question_rows.append(make_row(
                variable_name=variable_name,
                question=question_text,
                value="",
                label="[drill-down question - needs review]",
                question_type=question_type,
                selector=selector,
                qid=qid,
                is_main_question=True
            ))

        # ------------------------------------------------------------
        # Descriptive text / instructions
        # ------------------------------------------------------------
        elif question_type == "DB":
            # Descriptive blocks are usually instructions, not variables.
            # Keep them in the output, but mark them clearly.
            question_rows.append(make_row(
                variable_name="",
                question=question_text,
                value="",
                label="[descriptive text / instruction]",
                question_type=question_type,
                selector=selector,
                qid=qid,
                is_main_question=True
            ))

        # ------------------------------------------------------------
        # Other question types
        # ------------------------------------------------------------
        else:
            question_rows.append(make_row(
                variable_name=variable_name,
                question=question_text,
                value="",
                label="",
                question_type=question_type,
                selector=selector,
                qid=qid,
                is_main_question=True
            ))

        # Add this question's rows to the full codebook.
        if question_rows:
            all_rows.extend(question_rows)

            # Add one empty row between questions.
            all_rows.append(blank_row())

    # Remove final trailing blank row, if present.
    if all_rows and all_rows[-1] == blank_row():
        all_rows.pop()

    return pd.DataFrame(all_rows)


# ------------------------------------------------------------
# Excel export
# ------------------------------------------------------------

def dataframe_to_excel(df):
    """
    Creates an Excel file where only the main question's variable name
    and question text are bolded.

    CSV cannot support bold formatting, so this is for Excel downloads.
    """
    output = BytesIO()

    core_columns = ["VARIABLE NAME", "QUESTION", "VALUE", "LABEL"]
    export_df = df[core_columns].copy()

    if "IS MAIN QUESTION" in df.columns:
        main_question_flags = df["IS MAIN QUESTION"].fillna(False).astype(bool).tolist()
    else:
        main_question_flags = [False] * len(df)

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Codebook", startrow=0)

        workbook = writer.book
        worksheet = writer.sheets["Codebook"]

        header_format = workbook.add_format({
            "bold": True,
            "bg_color": "#70AD47",
            "font_color": "black",
            "border": 1,
            "align": "left",
            "valign": "top",
        })

        normal_format = workbook.add_format({
            "text_wrap": True,
            "valign": "top",
        })

        bold_main_question_format = workbook.add_format({
            "bold": True,
            "text_wrap": True,
            "valign": "top",
        })

        # Rewrite headers with formatting.
        for col_num, col_name in enumerate(export_df.columns):
            worksheet.write(0, col_num, col_name, header_format)

        # Rewrite cells with formatting.
        for row_num, row in export_df.iterrows():
            excel_row = row_num + 1

            is_main_question = main_question_flags[row_num]

            for col_num, col_name in enumerate(export_df.columns):
                value = row[col_name]

                if pd.isna(value):
                    value = ""

                # Bold only the main question's VARIABLE NAME and QUESTION.
                if (
                    is_main_question
                    and col_name in ["VARIABLE NAME", "QUESTION"]
                    and str(value).strip() != ""
                ):
                    worksheet.write(excel_row, col_num, value, bold_main_question_format)
                else:
                    worksheet.write(excel_row, col_num, value, normal_format)

        # Column widths.
        worksheet.set_column("A:A", 28, normal_format)
        worksheet.set_column("B:B", 75, normal_format)
        worksheet.set_column("C:C", 14, normal_format)
        worksheet.set_column("D:D", 45, normal_format)

        worksheet.freeze_panes(1, 0)

    output.seek(0)
    return output


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
        "The app attempts to follow Qualtrics survey/block order when available."
    )

    edited_df = st.data_editor(
        codebook_df,
        use_container_width=True,
        num_rows="dynamic",
        height=500,
        column_config={
            "IS MAIN QUESTION": None
        }
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

    full_csv_data = edited_df.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Download full codebook with metadata as CSV",
        data=full_csv_data,
        file_name="codebook_full.csv",
        mime="text/csv"
    )

else:
    st.info("Upload a .qsf file to begin.")
