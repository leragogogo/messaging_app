import os
import threading
import queue
from .chat_logic import ChatClient  # Import networking logic


def _on_message_received(sender, text):
    print(f"{sender}: {text}")


class ChatConsoleUI:
    """
    Console UI for chat:
      - Command input via input()
      - Event output via print()
      - Interaction with ChatClient via callbacks
    """

    def __init__(self, server_host: str, server_port: int):
        self.username = None
        self._receiving_files = {}  # (sender, filename) -> save_path
        self._pending_file_send = None  # (to_user, file_path, filename)
        self.running = True
        self._event_queue = queue.Queue()
        self._setup_networking(server_host, server_port)

    def _setup_networking(self, server_host: str, server_port: int):
        self.chat_client = ChatClient(server_host, server_port, ping_interval=60)
        self.chat_client.on_connect_result = self._on_connect_result
        self.chat_client.on_message_received = _on_message_received
        self.chat_client.on_user_list_updated = self._on_user_list_updated
        self.chat_client.on_error = self._on_error
        self.chat_client.on_disconnected = self._on_disconnected
        self.chat_client.on_file_request = self._on_file_request
        self.chat_client.on_file_accept = self._on_file_accept
        self.chat_client.on_file_cancel = self._on_file_cancel
        self.chat_client.on_file_data = self._on_file_data
        self.chat_client.on_file_complete = self._on_file_complete

    def run(self):
        print("Welcome to the console chat!")
        print("Available commands:")
        print("  connect <username>         - Connect to the server")
        print("  send <user> <message>      - Send a message to a user")
        print("  sendfile <user> <path>     - Send a file to a user")
        print("  users                      - Show list of users")
        print("  quit                       - Exit chat")
        print()
        self._input_loop()

    def _input_loop(self):
        while self.running:
            # If there is an event, process it immediately
            try:
                event = self._event_queue.get(timeout=0.1)
                if event[0] == 'file_request':
                    sender, filename, filesize, filetype = event[1:]
                    print(f"User {sender} offers to send file '{filename}' ({filesize} bytes, type {filetype}). "
                          f"Accept? (y/n)")
                    while True:
                        ans = input('> ').strip().lower()
                        if ans == 'y':
                            save_dir = input("Enter directory path to save the file: ").strip()
                            if not save_dir or not os.path.isdir(save_dir):
                                print("[Error] Directory not found. Refused.")
                                self.chat_client.send_file_cancel(sender, filename, "User canceled the file selection")
                                print(f"[Refused] {sender} -> {self.username}: refused file '{filename}' (directory "
                                      f"not selected)")
                                break
                            save_path = os.path.join(save_dir, filename)
                            self._receiving_files[(sender, filename)] = save_path
                            self.chat_client.send_file_accept(sender, filename)
                            print(f"[Success] {sender} -> {self.username}: file accepted '{filename}'")
                            break
                        elif ans == 'n':
                            self.chat_client.send_file_cancel(sender, filename, "User refused.")
                            print(f"[Refused] {sender} -> {self.username}: refused file '{filename}'")
                            break
                        else:
                            print("Enter 'y' or 'n'.")
                    continue  # After event, check for more events before prompting for command
            except queue.Empty:
                pass  # No event, proceed to command input

            # If no event, prompt for command
            try:
                cmd = input('> ').strip()
            except EOFError:
                self.running = False
                break
            if not cmd:
                continue
            parts = cmd.split()
            if not parts:
                continue
            command = parts[0].lower()
            if command == 'connect' and len(parts) == 2:
                self._try_connect(parts[1])
            elif command == 'send' and len(parts) >= 3:
                to_user = parts[1]
                text = ' '.join(parts[2:])
                self._send_message(to_user, text)
            elif command == 'sendfile' and len(parts) == 3:
                to_user = parts[1]
                file_path = parts[2]
                self._send_file(to_user, file_path)
            elif command == 'users':
                self._request_users()
            elif command == 'quit':
                self._on_closing()
            else:
                print("Unknown command or invalid arguments.")

    def _try_connect(self, username):
        if self.chat_client.running:
            print("[Info] Already connected.")
            return
        self.username = username
        print(f"[Info] Connecting as {username}...")
        self.chat_client.connect(username)

    def _on_connect_result(self, success, error):
        if success:
            print(f"*** Connected as {self.username} ***")
        else:
            print(f"[Error] Failed to connect: {error}")
            self.username = None

    def _on_user_list_updated(self, users):
        print("[Online users]:", ', '.join(u for u in users if u != self.username))

    def _on_error(self, error_text):
        print(f"[Error] {error_text}")

    def _on_disconnected(self):
        print("*** Disconnected from server ***")
        self.username = None

    def _send_message(self, to_user, text):
        if not self.chat_client.running:
            print("[Error] Not connected to server.")
            return
        self.chat_client.send_message(to_user, text)
        print(f"Me -> {to_user}: {text}")

    def _send_file(self, to_user, file_path):
        if not self.chat_client.running:
            print("[Error] Not connected to server.")
            return
        if not os.path.isfile(file_path):
            print(f"[Error] File not found: {file_path}")
            return
        filename = os.path.basename(file_path)
        self._pending_file_send = (to_user, file_path, filename)
        self.chat_client.send_file_request(to_user, file_path)
        print(f"Me -> {to_user}: sending file '{filename}'...")

    def _on_file_request(self, sender, filename, filesize, filetype):
        print(f"\n[Incoming file request from {sender}! Press Enter to respond.]")
        self._event_queue.put(('file_request', sender, filename, filesize, filetype))

    def _on_file_accept(self, sender, filename):
        print(f"{sender} accepted file '{filename}'.")
        if self._pending_file_send and self._pending_file_send[0] == sender \
                and self._pending_file_send[2] == filename:
            to_user, file_path, _ = self._pending_file_send
            threading.Thread(
                target=self._send_file_chunks,
                args=(to_user, file_path, filename),
                daemon=True
            ).start()
            self._pending_file_send = None

    def _on_file_cancel(self, sender, filename, reason):
        if reason:
            print(f"[Refused] {sender} canceled file transfer '{filename}': {reason}")
        else:
            print(f"[Refused] {sender} canceled file transfer '{filename}'")

    def _on_file_data(self, sender, filename, data, is_last_chunk):
        key = (sender, filename)
        save_path = self._receiving_files.get(key)
        if not save_path:
            print(f"[Error] Unknown file '{filename}' from {sender}, chunk ignored.")
            return
        with open(save_path, "ab") as f:
            f.write(data)
        if is_last_chunk:
            del self._receiving_files[key]

    def _on_file_complete(self, sender, filename):
        print(f"[Success] {sender} -> {self.username}: file transfer '{filename}' completed.")

    def _request_users(self):
        # Just trigger user list update (if server supports it)
        self.chat_client.request_user_list() if hasattr(self.chat_client, 'request_user_list') else None

    def _on_closing(self):
        self.running = False
        if self.chat_client.running:
            self.chat_client.disconnect()
        print("[Info] Exiting.")

    def _send_file_chunks(self, to_user, file_path, filename, chunk_size=4096):
        try:
            with open(file_path, "rb") as f:
                chunk_index = 0
                while True:
                    data = f.read(chunk_size)
                    if not data:
                        break
                    is_last = f.tell() == os.path.getsize(file_path)
                    self.chat_client.send_file_data(to_user, filename, chunk_index, data, is_last)
                    chunk_index += 1
            self.chat_client.send_file_complete(to_user, filename)
        except Exception as e:
            print(f"[Error] Failed to send file '{filename}': {e}")


if __name__ == "__main__":
    ui = ChatConsoleUI(server_host="16.170.226.19", server_port=7777)
    ui.run()
