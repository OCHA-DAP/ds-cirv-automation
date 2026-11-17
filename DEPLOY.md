# Deploying the CIRV app

The app runs on Azure at:

https://chd-ds-demos-cirv-hdbrh2e2deb6eec8.eastus2-01.azurewebsites.net

It is public, with no login. Nothing has been deployed yet, so it shows a placeholder page.

## Before the first deploy

1. **Add `requirements.txt` at the repo root.** Azure installs only what is listed there, on Python 3.14. The page itself needs:

   ```
   streamlit
   lxml
   openpyxl
   plotly
   beautifulsoup4
   ```

   Streamlit brings pandas, numpy and requests with it. The collectors' extra packages (pytesseract, opencv, playwright, pymupdf, msal) are not needed to serve the page. Don't paste a `pip freeze` from your laptop: older pinned versions (for example `pandas==2.2.2`) have no Python 3.14 build and the deploy will fail.

2. **Decide about the reference workbook.** The app needs the August CERF UFE workbook to show anything: it takes the country list, headers and formatting from it. The workbook is gitignored, so it won't be on the server, and the page will show only the error "Put the August reference workbook in the project root (or config/cirv_template.xlsx)". The repo and the app are both public. Commit the workbook (for example as `config/cirv_template.xlsx`) only once CERF has agreed it can be public. If it can't be, talk to the data science team before deploying.

3. **Hide the refresh controls on the server.** The "Data refresh controls" panel shows for every visitor. On the server, anyone could start a full refresh, turn on refresh-at-startup, or read the refresh log. The server is shared with other apps and has little memory to spare. One way: Azure sets the environment variable `WEBSITE_SITE_NAME` on the server, so the app can skip the panel when that variable is set.

## How to deploy

1. Push your changes to `main`.
2. On GitHub, go to **Actions** → **Deploy to Azure** → **Run workflow**.

The deploy takes a few minutes. After it finishes, the app can take a minute or two to start. Nothing deploys automatically when you push; only clicking **Run workflow** deploys.

## What the server runs

```
python -m streamlit run cirv_all_data_app.py --server.port 8000 --server.address 0.0.0.0 --server.headless true
```

The startup command is set on Azure, not in this repo. To serve a different file, ask the data science team to change it.

## What the server has

- **Only what is in the repo.** Files listed in `.gitignore` are not on the server: the reference workbook (`*.xlsx`), `data/raw/`, and the credential files.
- **No saved files.** Anything the app writes on the server is lost when the app restarts or is redeployed. To update the data, run the refresh on your laptop, commit the new CSV files, and deploy again.
- **No secrets.** The repo and the app are both public, so never commit passwords or API keys. If the app needs a key on the server, ask the data science team.

## If something goes wrong

- **The deploy step fails.** If the error is a 503 or "Service Unavailable", the shared server is busy: wait a few minutes and run the workflow again. Otherwise it is usually `requirements.txt` (a misspelt package or a version with no Python 3.14 build). Ask the data science team for the build log.
- **The deploy stops with "requirements.txt is missing".** Add the file at the repo root and run the workflow again.
- **The page loads but shows a red error box.** The app started but hit an error, for example the missing workbook or a package missing from `requirements.txt`. The message says which.
- **The page shows "Application Error".** The app server could not start at all. Ask the data science team for the startup logs.

## For the data science team

- Azure: slot `cirv` of web app `chd-ds-demos`, resource group `IMB-CHD-DataScience-EastUS2`, plan `DsciAppServicePlan`. Python 3.14, WebSockets on (Streamlit needs them), container logging on.
- App settings: `SCM_DO_BUILD_DURING_DEPLOYMENT=true`, so Azure installs `requirements.txt` on each deploy.
- Deploy auth: the repo secret `AZURE_WEBAPP_PUBLISH_PROFILE` holds the publish profile of the `cirv` slot. It gives full access to that slot (files, deploys and its app settings) and nothing else. Anyone who can push to the repo could use it, so treat any key added to the slot's settings as readable by them.
- Build log: `az webapp log deployment show -n chd-ds-demos -g IMB-CHD-DataScience-EastUS2 --slot cirv`.
- Startup log: `az webapp log tail -n chd-ds-demos -g IMB-CHD-DataScience-EastUS2 --slot cirv`.
