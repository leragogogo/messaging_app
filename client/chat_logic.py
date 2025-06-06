import socket
import threading
import json
import time
import protocol


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

    def connect(self, username: str):
        """
        Attempt to establish a TCP connection and send {"action":"connect","username":...}.
        After reading the server’s response, invoke on_connect_result(success, error).
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

        # Send the “connect” request
        payload = {"action": protocol.ACTION_CONNECT, "username": username}
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

        # Check server’s answer
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

        payload = {"action": protocol.ACTION_MESSAGE, "to": to, "message": message}
        try:
            self._send_json(payload)
        except Exception as e:
            if self.on_error:
                self.on_error(f"Send error: {e}")

    def disconnect(self):
        """
        Stop background threads, send {"action":"disconnect"} to the server,
        and close the socket.
        """
        if not self.running:
            return

        try:
            self._send_json({"action": protocol.ACTION_DISCONNECT})
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

        # Exiting loop means the connection is gone
        self.running = False
        if self.on_disconnected:
            self.on_disconnected()

    def _ping_loop(self):
        """
        Background thread that sleeps for ping_interval seconds,
        then sends {"action":"ping"} to let the server know we’re still alive.
        """
        while self.running:
            time.sleep(self.ping_interval)
            try:
                self._send_json({"action":protocol.ACTION_PING})
            except:
                break  # Failed to send a ping–exit loop

        # If ping loop ends, mark as disconnected
        self.running = False
        if self.on_disconnected:
            self.on_disconnected()
