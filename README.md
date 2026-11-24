# QSF Codebook Generator

This Streamlit app creates a simple evaluation codebook from a Qualtrics `.qsf` file (survey export file).

Upload a `.qsf` file to get an editable draft codebook with these columns:

- **VARIABLE NAME**, **QUESTION**, **VALUE**, **LABEL**
- **SPSS VALUE LABELS**: a ready-to-run SPSS `VALUE LABELS` command for each question, for example
  `VALUE LABELS gender 1 'Man' 2 'Woman' 99 'Prefer not to say'.`
  Matrix and check-all-that-apply items share one command that lists every item variable.

Downloads: Excel (`.xlsx`), CSV, full CSV with metadata, and an SPSS syntax file (`.sps`) containing all the value labels.

## Run locally

```
pip install -r requirements.txt
streamlit run app.py
```
