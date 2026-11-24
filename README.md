# QSF Codebook Generator

This app creates a simple evaluation codebook from a Qualtrics `.qsf` file (survey export file).

## ▶ Use the app: https://fdiste.github.io/codebookcreator/

No install needed. The app runs entirely in your web browser, so your `.qsf` file is never uploaded to a server. The first load takes 10–20 seconds while it sets up.

Upload a `.qsf` file to get an editable draft codebook with these columns:

- **VARIABLE NAME**, **QUESTION**, **VALUE**, **LABEL**
- **SPSS VALUE LABELS**: a ready-to-run SPSS `VALUE LABELS` command for each question, for example
  `VALUE LABELS gender 1 'Man' 2 'Woman' 99 'Prefer not to say'.`
  Matrix and check-all-that-apply items share one command that lists every item variable.

Downloads: Excel (`.xlsx`), CSV, full CSV with metadata, and an SPSS syntax file (`.sps`) containing all the value labels.

## How it's hosted

`index.html` uses [stlite](https://github.com/whitphx/stlite) to run `app.py` in the browser, and GitHub Pages serves it from the `main` branch. To update the public app, edit `app.py` and push.

## Run locally (optional)

```
pip install -r requirements.txt
streamlit run app.py
```
