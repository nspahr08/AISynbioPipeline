import os
import logging
from .config import load_config
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

CONFIG = load_config()
OAUTH_CREDENTIALS_FILE = CONFIG["drive"]["credentials_file"]
TOKEN_FILE = CONFIG["drive"]["token_file"]
SCOPES = CONFIG["drive"]["scopes"]


def get_drive_service():
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                OAUTH_CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def find_file_in_folder(service, filename, folder_id):
    query = (
        f"name = '{filename}' "
        f"and '{folder_id}' in parents "
        f"and trashed = false"
    )

    results = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)"
    ).execute()

    files = results.get("files", [])
    return files[0]["id"] if files else None


def upload_or_replace(file_path, folder_id):
    service = get_drive_service()
    filename = os.path.basename(file_path)

    existing_file_id = find_file_in_folder(service, filename, folder_id)
    media = MediaFileUpload(file_path, resumable=False)

    if existing_file_id:
        service.files().update(
            fileId=existing_file_id,
            media_body=media
        ).execute()
        logging.info(f"Updated existing file: {filename}")
    else:
        service.files().create(
            body={
                "name": filename,
                "parents": [folder_id],
            },
            media_body=media,
            fields="id"
        ).execute()
        logging.info(f"Uploaded new file: {filename}")


# def upload_all_outputs():

#     for filename in os.listdir(OUTPUT_FOLDER):
#         file_path = os.path.join(OUTPUT_FOLDER, filename)
#         if os.path.isfile(file_path):
#             upload_or_replace(file_path, DRIVE_FOLDER_ID)
