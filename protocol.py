"""
protocol.py

Defines all JSON‐over‐TCP “action” names and their required fields.
"""

import base64
from typing import Dict, Any

# ──────────────────────────────────────────────────────────────────────────────
# Standard chat actions
# ──────────────────────────────────────────────────────────────────────────────

# Client → Server
ACTION_CONNECT = "connect"
ACTION_PING = "ping"
ACTION_MESSAGE = "message"
ACTION_DISCONNECT = "disconnect"

# Server → Client
ACTION_CONNECT_RESPONSE = "connect_response"
ACTION_USER_LIST = "user_list"
ACTION_ERROR = "error"

# ──────────────────────────────────────────────────────────────────────────────
# File-transfer actions
# ──────────────────────────────────────────────────────────────────────────────

ACTION_FILE_REQUEST = "file_transfer_request"
ACTION_FILE_ACCEPT = "file_transfer_accept"
ACTION_FILE_CANCEL = "file_transfer_cancel"
ACTION_FILE_DATA = "file_transfer_data"
ACTION_FILE_COMPLETE = "file_transfer_complete"

# ──────────────────────────────────────────────────────────────────────────────
# Payload schemas
# ──────────────────────────────────────────────────────────────────────────────
CONNECT_REQUEST_SCHEMA = {
    "action": ACTION_CONNECT,
    "username": "<string>"        # desired username, e.g. "alice"
}

CONNECT_RESPONSE_OK_SCHEMA = {
    "action": ACTION_CONNECT_RESPONSE,
    "status": "ok"                      # literal string "ok" on success
}

CONNECT_RESPONSE_ERR_SCHEMA = {
    "action": ACTION_CONNECT_RESPONSE,
    "status": "error",                  # literal string "error"
    "error": "<string>"                 # e.g. "username already taken"
}

PING_SCHEMA = {
    "action": ACTION_PING
}

MESSAGE_SCHEMA = {
    "action": ACTION_MESSAGE,
    "to": "<string>",          # recipient username, e.g. "bob"
    "message": "<string>"      # text message to send
}

DISCONNECT_SCHEMA = {
    "action": ACTION_DISCONNECT
}

# Server broadcasts
USER_LIST_SCHEMA = {
    "action": ACTION_USER_LIST,
    "users": ["<username1>", "<username2>", ...]
}

ERROR_SCHEMA = {
    "action": ACTION_ERROR,
    "error": "<string>"      # e.g. "user not found"
}

# file_transfer_request (Client → Server)
# Sent when sender wants to initiate a file/photo transfer.
# Required fields:
#   - "action":         must be ACTION_FILE_REQUEST
#   - "from":           sender username (e.g. "alice")
#   - "to":             recipient username (e.g. "bob")
#   - "filename":       exact filename (e.g. "vacation.jpg")
#   - "filesize":       integer size in bytes (e.g. 2345123)
#   - "filetype":       MIME type, e.g. "jpeg" or "pdf"
FILE_REQUEST_SCHEMA = {
    "action": ACTION_FILE_REQUEST,
    "from": "<string>",       # sender’s username
    "to": "<string>",         # recipient’s username
    "filename": "<string>",   # e.g. "foo.png"
    "filesize": "<int>",      # e.g. 5123456
    "filetype": "<string>"    # e.g. "png"
}

# file_transfer_accept (Receiver → Server)
# Sent when the recipient clicks “Accept.” Forwards to sender.
# Required fields:
#   - "action":    ACTION_FILE_ACCEPT
#   - "from":      recipient’s username (e.g. "bob")
#   - "to":        sender’s username (e.g. "alice")
#   - "filename":  must match the one requested
FILE_ACCEPT_SCHEMA = {
    "action": ACTION_FILE_ACCEPT,
    "from": "<string>",      # recipient’s username
    "to": "<string>",        # sender’s username
    "filename": "<string>"   # same filename as in the original request
}

# file_transfer_cancel (Either side → Server)
# Sent by either sender or receiver to abort a transfer in progress.
# Required fields:
#   - "action":    ACTION_FILE_CANCEL
#   - "from":      who is canceling
#   - "to":        the other party
#   - "filename":  the filename to cancel
#   - "reason":    short error text or user-driven message
FILE_CANCEL_SCHEMA = {
    "action": ACTION_FILE_CANCEL,
    "from": "<string>",
    "to": "<string>",
    "filename": "<string>",
    "reason": "<string (optional)>"
}

# file_transfer_data (Sender → Server, then Server → Receiver)
# Represents a single chunk of the file’s bytes, base64-encoded.
# Required fields:
#   - "action":         ACTION_FILE_DATA
#   - "from":           sender username
#   - "to":             recipient username
#   - "filename":       filename in question
#   - "chunk_index":    integer index (0, 1, 2, …)
#   - "data":           base64-encoded string of this chunk’s bytes
#   - "is_last_chunk":  boolean (True if this is the final chunk)
FILE_DATA_SCHEMA = {
    "action": ACTION_FILE_DATA,
    "from": "<string>",
    "to": "<string>",
    "filename": "<string>",
    "chunk_index": "<int>",
    "data": "<base64-string>",
    "is_last_chunk": "<bool>"
}

# file_transfer_complete (Server → Receiver or Sender)
# Required fields:
#   - "action":    ACTION_FILE_COMPLETE
#   - "from":      original sender
#   - "to":        original recipient
#   - "filename":  filename that just finished
FILE_COMPLETE_SCHEMA = {
    "action": ACTION_FILE_COMPLETE,
    "from": "<string>",
    "to": "<string>",
    "filename": "<string>"
}

# ──────────────────────────────────────────────────────────────────────────────
# Helper functions to build or validate messages
# ──────────────────────────────────────────────────────────────────────────────

def build_file_request(sender: str, recipient: str, filename: str, filesize: int, filetype: str) -> Dict[str, Any]:
    """
    Returns a properly shaped JSON‐serializable dict for a file_transfer_request.
    """
    return {
        "action": ACTION_FILE_REQUEST,
        "from": sender,
        "to": recipient,
        "filename": filename,
        "filesize": filesize,
        "filetype": filetype
    }

def build_file_data(sender: str, recipient: str, filename: str, chunk_index: int, chunk_bytes: bytes, is_last: bool) -> Dict[str, Any]:
    """
    Returns a JSON‐serializable dict for a file_transfer_data,
    encoding chunk_bytes as base64.
    """
    encoded = base64.b64encode(chunk_bytes).decode('ascii')
    return {
        "action": ACTION_FILE_DATA,
        "from": sender,
        "to": recipient,
        "filename": filename,
        "chunk_index": chunk_index,
        "data": encoded,
        "is_last_chunk": is_last
    }

