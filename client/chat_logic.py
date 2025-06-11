import socket
import threading
import json
import time
import protocol
import os
import base64
import mimetypes


class ChatClient:
    """
    ChatClient handles all low-level network logic:
      - opening/closing the TCP connection
      - sending JSON commands (connect, message, ping, disconnect)
      - receiving server responses in a background thread
      - invoking application-level callbacks on events
    """

    def __init__(self, server_host: str, server_port: int, ping_interval: int = 60):
        self.server_host = server_host
        self.server_port = server_port
        self.ping_interval = ping_interval

        self.sock = None
        self.sock_file = None

        self.running = False  # Indicates whether background threads should keep running
        self.receiver_thread = None
        self.pinger_thread = None

        # Application‐level callbacks (to be set by UI)
        self.on_connect_result = None  # signature: fn(success: bool, error: str|None)
        self.on_message_received = None  # signature: fn(sender: str, text: str)
        self.on_user_list_updated = None  # signature: fn(list_of_users: list[str])
        self.on_error = None  # signature: fn(error_text: str)
        self.on_disconnected = None  # signature: fn()

        # File transfer callbacks (to be set by UI)
        self.on_file_request = None  # signature: fn(sender: str, filename: str, filesize: int, filetype: str)
        self.on_file_accept = None  # signature: fn(sender: str, filename: str)
        self.on_file_cancel = None  # signature: fn(sender: str, filename: str, reason: str)
        self.on_file_data = None  # signature: fn(sender: str, filename: str, chunk_index: int, data: bytes, is_last_chunk: bool)
        self.on_file_complete = None  # signature: fn(sender: str, filename: str)

    def connect(self, username: str):
        """
        Attempt to establish a TCP connection and send {"action":"connect","username":...}.
        After reading the server's response, invoke on_connect_result(success, error).
        If successful, start background receiver and ping threads.
        """
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.server_host, self.server_port))
            self.sock_file = self.sock.makefile(mode='r', encoding='utf-8')
        except Exception as e:
            # Failed to connect at all
            if self.on_connect_result:
                self.on_connect_result(False, f"Cannot connect to server: {e}")
            return

        # Send the "connect" request
        payload = protocol.build_connect(username)
        try:
            self._send_json(payload)
        except Exception as e:
            if self.on_connect_result:
                self.on_connect_result(False, f"Send error: {e}")
            self.sock.close()
            return

        # Wait synchronously for a single response line
        try:
            response_line = self.sock_file.readline()
            if not response_line:
                raise Exception("No response from server.")
            resp = json.loads(response_line)
        except Exception as e:
            if self.on_connect_result:
                self.on_connect_result(False, f"Invalid response: {e}")
            self.sock.close()
            return

        # Check server's answer
        if resp.get("action") == protocol.ACTION_CONNECT and resp.get("status") == "ok":
            # Successfully registered
            if self.on_connect_result:
                self.on_connect_result(True, None)
            # Start background threads: receiver and pinger
            self.running = True
            self.receiver_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receiver_thread.start()
            self.pinger_thread = threading.Thread(target=self._ping_loop, daemon=True)
            self.pinger_thread.start()
        else:
            # Received an error (e.g., username already taken)
            err = resp.get("error", "unknown error")
            if self.on_connect_result:
                self.on_connect_result(False, err)
            self.sock.close()

    def send_message(self, to: str, message: str):
        """
        Send a private message: {"action":"message","to":to,"message":message}
        """
        if not self.running:
            return

        payload = protocol.build_message(to, message)
        try:
            self._send_json(payload)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Send error: {e}")

    def send_file_request(self, to: str, file_path: str):
        """
        Initiates a file transfer.
        Reads the file, determines its size and type,
        then sends a request (file_transfer_request) to the recipient.
        """
        if not self.running:
            return
        try:
            filesize = os.path.getsize(file_path)
            filetype, _ = mimetypes.guess_type(file_path, strict=False)
            if filetype is None:
                filetype = "application/octet-stream"
            filename = os.path.basename(file_path)
            payload = protocol.build_file_request("", to, filename, filesize, filetype)
            self._send_json(payload)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Send file request error: {e}")

    def send_file_accept(self, to: str, filename: str):
        """
        Send message (file_transfer_accept) from recipient to sender.
        """
        if not self.running:
            return
        payload = protocol.build_file_accept("", to, filename)
        try:
            self._send_json(payload)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Send file accept error: {e}")

    def send_file_cancel(self, to: str, filename: str, reason: str = ""):
        """
        Send message (file_transfer_cancel) when user refused or an error is occurred.
        """
        if not self.running:
            return
        payload = protocol.build_file_cancel("", to, filename, reason)
        try:
            self._send_json(payload)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Send file cancel error: {e}")

    def send_file_data(self, to: str, filename: str, chunk_index: int, data: bytes, is_last_chunk: bool):
        """
        Send file chunk (file_transfer_data) to recipient.
        """
        if not self.running:
            return
        payload = protocol.build_file_data("", to, filename, chunk_index, data, is_last_chunk)
        try:
            self._send_json(payload)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Send file data error: {e}")

    def send_file_complete(self, to: str, filename: str):
        """
        Send message (file_transfer_complete) when the transfer is completed.
        """
        if not self.running:
            return
        payload = protocol.build_file_complete("", to, filename)
        try:
            self._send_json(payload)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Send file complete error: {e}")

    def disconnect(self):
        """
        Stop background threads, send {"action":"disconnect"} to the server,
        and close the socket.
        """
        if not self.running:
            return

        try:
            self._send_json(protocol.build_disconnect())
        except:
            pass

        self.running = False
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
            self.sock.close()
        except:
            pass

    def _send_json(self, data: dict):
        """
        Helper method: serialize `data` to JSON + '\n' and send over the socket.
        """
        text = json.dumps(data, ensure_ascii=False) + "\n"
        self.sock.sendall(text.encode("utf-8"))

    def _receive_loop(self):
        """
        Background thread that continuously reads lines from self.sock_file,
        parses JSON, and invokes the appropriate callbacks based on action.
        """
        while self.running:
            try:
                line = self.sock_file.readline()
                if not line:
                    # Server closed the connection
                    break
                msg = json.loads(line)
            except Exception:
                continue

            action = msg.get("action")
            if action == protocol.ACTION_MESSAGE:
                sender = msg.get("from")
                text = msg.get("message")
                if self.on_message_received:
                    self.on_message_received(sender, text)
            elif action == protocol.ACTION_USER_LIST:
                users = msg.get("users", [])
                if self.on_user_list_updated:
                    self.on_user_list_updated(users)
            elif action == protocol.ACTION_ERROR:
                err = msg.get("error", "unknown")
                if self.on_error:
                    self.on_error(err)
            # File transfer events handlers
            elif action == protocol.ACTION_FILE_REQUEST:
                sender = msg.get("from")
                filename = msg.get("filename")
                filesize = msg.get("filesize")
                filetype = msg.get("filetype")
                if self.on_file_request:
                    self.on_file_request(sender, filename, filesize, filetype)
            elif action == protocol.ACTION_FILE_ACCEPT:
                sender = msg.get("from")
                filename = msg.get("filename")
                if self.on_file_accept:
                    self.on_file_accept(sender, filename)
            elif action == protocol.ACTION_FILE_CANCEL:
                sender = msg.get("from")
                filename = msg.get("filename")
                reason = msg.get("reason", "")
                if self.on_file_cancel:
                    self.on_file_cancel(sender, filename, reason)
            elif action == protocol.ACTION_FILE_DATA:
                sender = msg.get("from")
                filename = msg.get("filename")
                data_b64 = msg.get("data")
                is_last_chunk = msg.get("is_last_chunk", False)
                try:
                    data = base64.b64decode(data_b64)
                except Exception as e:
                    if self.on_error:
                        self.on_error(f"Decode file data error: {e}")
                    continue
                if self.on_file_data:
                    self.on_file_data(sender, filename, data, is_last_chunk)
            elif action == protocol.ACTION_FILE_COMPLETE:
                sender = msg.get("from")
                filename = msg.get("filename")
                if self.on_file_complete:
                    self.on_file_complete(sender, filename)

        # Exiting loop means the connection is gone
        self.running = False
        if self.on_disconnected:
            self.on_disconnected()

    def _ping_loop(self):
        """
        Background thread that sleeps for ping_interval seconds,
        then sends {"action":"ping"} to let the server know we're still alive.
        """
        while self.running:
            time.sleep(self.ping_interval)
            try:
                self._send_json(protocol.build_ping())
            except:
                break  # Failed to send a ping–exit loop

        # If ping loop ends, mark as disconnected
        self.running = False
        if self.on_disconnected:
            self.on_disconnected()
