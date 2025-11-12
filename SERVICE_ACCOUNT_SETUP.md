# Google Sheets API Service Account Setup

This guide explains how to set up a Google Cloud Platform service account for accessing your Google Sheets LIMS database.

## Step 1: Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Note your project ID

## Step 2: Enable Required APIs

1. In the Google Cloud Console, go to **APIs & Services** > **Library**
2. Search for and enable the following APIs:
   - Google Sheets API
   - Google Drive API

## Step 3: Create a Service Account

1. Go to **APIs & Services** > **Credentials**
2. Click **Create Credentials** > **Service Account**
3. Fill in the service account details:
   - Name: `lims-sync-service`
   - Description: `Service account for LIMS Google Sheets sync`
4. Click **Create and Continue**
5. Skip the optional permissions steps
6. Click **Done**

## Step 4: Create and Download Credentials

1. In the **Credentials** page, find your new service account
2. Click on the service account email
3. Go to the **Keys** tab
4. Click **Add Key** > **Create New Key**
5. Select **JSON** as the key type
6. Click **Create**
7. A JSON file will be downloaded to your computer

## Step 5: Install Credentials

1. Create a `credentials` directory in your AISynbioPipeline project root:
   ```bash
   mkdir credentials
   ```
2. Rename the downloaded JSON file to `service_account.json`
3. Move it to the `credentials` directory: `credentials/service_account.json`
4. **IMPORTANT**: Never commit this file to version control (the credentials/ directory is in .gitignore)

## Step 6: Share Google Sheets with Service Account

1. Open your Google Sheets LIMS spreadsheet
2. Click the **Share** button
3. Copy the service account email from the JSON file (it looks like: `lims-sync-service@your-project.iam.gserviceaccount.com`)
4. Paste it into the share dialog
5. Set permission to **Viewer** (the API only needs read access)
6. Uncheck "Notify people" (the service account doesn't need notification)
7. Click **Share**

## Step 7: Update Configuration

1. Open `aisynbiopipeline/limsapi/config.json`
2. Update the `spreadsheet_id` field with your Google Sheets ID:
   - The spreadsheet ID is in the URL: `https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/edit`
   - For example, if your URL is `https://docs.google.com/spreadsheets/d/1Rs5WeIy4bXRKL6DRJ41S3_NAc8JUHdeL7oDya5JEvE4/edit`
   - Your spreadsheet ID is: `1Rs5WeIy4bXRKL6DRJ41S3_NAc8JUHdeL7oDya5JEvE4`

## Step 8: Test the Connection

Run a manual sync to test everything is working:

```bash
lims sync
```

If successful, you should see output showing tables being synced.

## Troubleshooting

### Error: "Credentials file not found"
- Make sure `service_account.json` is in the `credentials/` directory
- Check the `credentials_file` path in `config.json` (should be `credentials/service_account.json`)

### Error: "Permission denied" or "403 Forbidden"
- Make sure you shared the spreadsheet with the service account email
- Check that the service account has at least Viewer permission

### Error: "API has not been used in project"
- Make sure you enabled Google Sheets API and Google Drive API in your Google Cloud project
- Wait a few minutes and try again

### Error: "Spreadsheet not found"
- Double-check the spreadsheet ID in `config.json`
- Make sure the spreadsheet hasn't been deleted
- Verify the service account has access

## Security Best Practices

1. **Never commit credentials to version control** (the `credentials/` directory is in .gitignore)
2. Store the file securely and restrict file permissions:
   ```bash
   chmod 600 credentials/service_account.json
   ```
3. Only grant the minimum required permissions (Viewer is enough for read-only sync)
4. Rotate service account keys periodically
5. Monitor service account usage in Google Cloud Console
6. Use different service accounts for different environments (dev, staging, prod)

## Next Steps

Once the service account is set up and working:

1. Start the sync daemon: `lims daemon start`
2. Check sync status: `lims status`
3. Query your data: `lims list` and `lims query <table_name>`
