# Deploying the CIRV app

The app runs on Azure at:

https://chd-ds-demos-cirv-hdbrh2e2deb6eec8.eastus2-01.azurewebsites.net

It is public, with no login.

## How to deploy

1. Make sure `requirements.txt` at the repo root lists every package the app imports. Azure installs only what is listed there.
2. Push your changes to `main`.
3. On GitHub, go to **Actions** → **Deploy to Azure** → **Run workflow**.

The deploy takes a few minutes. After it finishes, the app can take a minute or two to start. Nothing deploys automatically when you push; only clicking **Run workflow** deploys.

## What the server runs

```
python -m streamlit run cirv_all_data_app.py --server.port 8000 --server.address 0.0.0.0 --server.headless true
```

The startup command is set on Azure, not in this repo. To serve a different file, ask the data science team to change it.

## What the server has

- **Only what is in the repo.** Files listed in `.gitignore` are not on the server: the reference workbook (`*.xlsx`), `data/raw/`, and the credential files.
- **No saved files.** Anything the app writes on the server is lost when the app restarts or is redeployed. To update the data, run the refresh on your laptop, commit the new CSV files, and deploy again.
- **No secrets.** The repo and the app are both public, so never commit passwords or API keys. If the app needs a key on the server, ask the data science team to add it as a setting on Azure.

## If something goes wrong

- **The deploy fails with a 503 or "Service Unavailable".** The shared server is busy. Wait a few minutes and run the workflow again.
- **The deploy succeeds but the page shows "Application Error".** The app crashed while starting. Ask the data science team for the startup logs.
- **The deploy stops with "requirements.txt is missing".** Add the file at the repo root and run the workflow again.

## For the data science team

- Azure: slot `cirv` of web app `chd-ds-demos`, resource group `IMB-CHD-DataScience-EastUS2`, plan `DsciAppServicePlan`. Python 3.14, WebSockets on (Streamlit needs them), container logging on.
- App settings: `SCM_DO_BUILD_DURING_DEPLOYMENT=true`, so Azure installs `requirements.txt` on each deploy.
- Deploy auth: the repo secret `AZURE_WEBAPP_PUBLISH_PROFILE` holds the publish profile of the `cirv` slot only. SCM basic auth is on for this slot so the profile works; FTP is off.
- Logs: `az webapp log tail -n chd-ds-demos -g IMB-CHD-DataScience-EastUS2 --slot cirv`.
