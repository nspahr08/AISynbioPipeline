import os
import logging
from pathlib import Path
from .config import load_config, get_drive_credentials_path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

CONFIG = load_config()
credentials_path = get_drive_credentials_path(CONFIG)
OAUTH_CREDENTIALS_FILE = credentials_path / CONFIG["drive"]["credentials_file"]
TOKEN_FILE = credentials_path / CONFIG["drive"]["token_file"]
SCOPES = CONFIG["drive"]["scopes"]
# AUTH_METHOD = os.getenv("GOOGLE_AUTH_METHOD", "local_server").lower()


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
            # creds = flow.run_local_server(port=0)
            creds = flow.run_local_server(
                port=8080,
                access_type="offline",
                prompt="consent"
            )

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
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
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
            supportsAllDrives=True,
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
            supportsAllDrives=True,
            fields="id"
        ).execute()
        logging.info(f"Uploaded new file: {filename}")


def upload_folder(local_folder_path, drive_parent_folder_id):
    """
    Recursively upload a local folder and its contents to Google Drive.

    Creates the folder structure in Google Drive, uploading all files and
    subfolders. Existing files/folders with the same name will be updated.

    Parameters
    ----------
    local_folder_path : str or Path
        Path to the local folder to upload
    drive_parent_folder_id : str
        ID of the parent folder in Google Drive where the folder will be created

    Returns
    -------
    str
        ID of the created/updated folder in Google Drive

    Raises
    ------
    FileNotFoundError
        If local_folder_path does not exist
    ValueError
        If local_folder_path is not a directory
    """
    local_folder_path = Path(local_folder_path)
    if not local_folder_path.exists():
        raise FileNotFoundError(f"Local folder not found: {local_folder_path}")
    if not local_folder_path.is_dir():
        raise ValueError(f"Path is not a directory: {local_folder_path}")

    service = get_drive_service()
    folder_name = local_folder_path.name

    # Create or find the root folder in Drive
    root_folder_id = _create_or_find_drive_folder(service, folder_name, drive_parent_folder_id)

    # Recursively upload contents
    _upload_folder_contents(service, local_folder_path, root_folder_id)

    logging.info(f"Uploaded folder '{folder_name}' to Drive (ID: {root_folder_id})")
    return root_folder_id


def _create_or_find_drive_folder(service, folder_name, parent_folder_id):
    """
    Create a folder in Google Drive or return existing folder ID.

    Parameters
    ----------
    service : googleapiclient.discovery.Resource
        Authenticated Drive service
    folder_name : str
        Name of the folder to create
    parent_folder_id : str
        ID of the parent folder

    Returns
    -------
    str
        ID of the created or existing folder
    """
    # Check if folder already exists
    existing_folder_id = find_file_in_folder(service, folder_name, parent_folder_id)
    if existing_folder_id:
        return existing_folder_id

    # Create new folder
    folder_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_folder_id]
    }

    folder = service.files().create(
        body=folder_metadata,
        fields='id',
        supportsAllDrives=True
    ).execute()

    return folder.get('id')


def _upload_folder_contents(service, local_folder_path, drive_folder_id):
    """
    Recursively upload the contents of a local folder to a Drive folder.

    Parameters
    ----------
    service : googleapiclient.discovery.Resource
        Authenticated Drive service
    local_folder_path : Path
        Path to the local folder
    drive_folder_id : str
        ID of the Drive folder to upload to
    """
    for item in local_folder_path.iterdir():
        if item.is_file():
            # Upload file
            upload_or_replace(str(item), drive_folder_id)
        elif item.is_dir():
            # Create subfolder and recurse
            subfolder_id = _create_or_find_drive_folder(service, item.name, drive_folder_id)
            _upload_folder_contents(service, item, subfolder_id)


# def upload_all_outputs():

#     for filename in os.listdir(OUTPUT_FOLDER):
#         file_path = os.path.join(OUTPUT_FOLDER, filename)
#         if os.path.isfile(file_path):
#             upload_or_replace(file_path, DRIVE_FOLDER_ID)
