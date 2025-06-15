import tkinter as tk
from tkinter import messagebox, scrolledtext
from tkinter import filedialog
import os
import threading
from .chat_logic import ChatClient  # Import the networking logic


class ChatUI:
    """
    ChatUI handles all Tkinter-based GUI:
      - creating widgets (frames, buttons, text areas, listboxes)
      - wiring button callbacks to ChatClient methods (connect, send_message, disconnect)
      - registering ChatClient callbacks (on_connect_result, on_message_received, etc.)
      - using root.after(...) to ensure thread-safe UI updates
    """

    def __init__(self, root: tk.Tk, server_host: str, server_port: int):
        self.root = root
        self.root.title("Chat Client")

        # Initialize instance variables
        self.username = None
        self._receiving_files = {}  # (sender, filename) -> save_path
        self._pending_file_send = None  # (to_user, file_path, filename)

        # Set up the ChatClient and register callbacks
        self._setup_networking(server_host, server_port)

        # Build the login UI (username entry + Connect button)
        self._create_login_ui()

        # Build the main chat UI (but do not show it yet)
        self._create_chat_ui()
        self._create_send_ui()

        # Configure window close behavior
        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _setup_networking(self, server_host: str, server_port: int):
        """
        Create the ChatClient instance, set ping interval, and register all callbacks.
        """
        self.chat_client = ChatClient(server_host, server_port, ping_interval=60)

        # Register callbacks so ChatClient can notify us of events
        self.chat_client.on_connect_result = self._on_connect_result
        self.chat_client.on_message_received = self._on_message_received
        self.chat_client.on_user_list_updated = self._on_user_list_updated
        self.chat_client.on_error = self._on_error
        self.chat_client.on_disconnected = self._on_disconnected

        # Register callbacks for file transfer
        self.chat_client.on_file_request = self._on_file_request
        self.chat_client.on_file_accept = self._on_file_accept
        self.chat_client.on_file_cancel = self._on_file_cancel
        self.chat_client.on_file_data = self._on_file_data
        self.chat_client.on_file_complete = self._on_file_complete

    def _create_login_ui(self):
        """
        Create and pack the widgets for the login screen (username entry + Connect button).
        """
        self.login_frame = tk.Frame(self.root)
        self.login_frame.pack(padx=10, pady=10)

        tk.Label(self.login_frame, text="Username:").grid(row=0, column=0, padx=5, pady=5)
        self.username_entry = tk.Entry(self.login_frame)
        self.username_entry.grid(row=0, column=1, padx=5, pady=5)

        self.connect_btn = tk.Button(
            self.login_frame, text="Connect", command=self._try_connect
        )
        self.connect_btn.grid(row=0, column=2, padx=5, pady=5)

    def _create_chat_ui(self):
        """
        Create the widgets for displaying active users and chat messages.
        Do not pack them yet; packing happens after successful login.
        """
        self.chat_frame = tk.Frame(self.root)

        # Active users list
        self.users_label = tk.Label(self.chat_frame, text="Active Users:")
        self.users_label.grid(row=0, column=0, padx=5, pady=5, sticky="nw")
        self.users_listbox = tk.Listbox(self.chat_frame, width=20, height=15)
        self.users_listbox.grid(row=1, column=0, padx=5, pady=5, sticky="n")

        # Chat history text area
        self.chat_label = tk.Label(self.chat_frame, text="Chat:")
        self.chat_label.grid(row=0, column=1, padx=5, pady=5, sticky="nw")
        self.chat_text = scrolledtext.ScrolledText(
            self.chat_frame, width=50, height=15, state="disabled"
        )
        self.chat_text.grid(row=1, column=1, padx=5, pady=5, sticky="n")

    def _create_send_ui(self):
        """
        Create the widgets for sending a message (To: entry, Message: entry, Send button).
        Do not pack them yet; packing happens after successful login.
        """
        self.send_frame = tk.Frame(self.root)

        tk.Label(self.send_frame, text="To:").grid(row=0, column=0, padx=5, pady=5)
        self.to_entry = tk.Entry(self.send_frame, width=15)
        self.to_entry.grid(row=0, column=1, padx=5, pady=5)

        tk.Label(self.send_frame, text="Message:").grid(row=0, column=2, padx=5, pady=5)
        self.msg_entry = tk.Entry(self.send_frame, width=40)
        self.msg_entry.grid(row=0, column=3, padx=5, pady=5)

        self.send_btn = tk.Button(
            self.send_frame, text="Send", command=self._send_message, state="disabled"
        )
        self.send_btn.grid(row=0, column=4, padx=5, pady=5)

        # Send file button
        self.send_file_btn = tk.Button(
            self.send_frame, text="Send file", command=self._send_file, state="disabled"
        )
        self.send_file_btn.grid(row=0, column=5, padx=5, pady=5)

    def _try_connect(self):
        """
        Called when the user clicks "Connect".
        Grab the username and call chat_client.connect(username).
        """
        username = self.username_entry.get().strip()
        if not username:
            messagebox.showwarning("Warning", "Please enter a username.")
            return

        # Disable the Connect button to prevent double-click
        self.connect_btn.config(state="disabled")
        self.chat_client.connect(username)

    def _on_connect_result(self, success: bool, error: str | None):
        """
        Callback from ChatClient indicating whether connect succeeded.
        Runs in a background thread, so wrap UI updates in root.after().
        """

        def handle():
            if success:
                # Save the username, show chat UI, and enable Send button
                self.username = self.username_entry.get().strip()
                self._show_chat_ui()
                self._append_chat(f"*** Connected as {self.username} ***\n")
                self.send_btn.config(state="normal")
                self.send_file_btn.config(state="normal")
            else:
                # Show error and re-enable Connect button
                messagebox.showerror("Error", f"Connection refused: {error}")
                self.connect_btn.config(state="normal")

        self.root.after(0, handle)

    def _show_chat_ui(self):
        """
        Hide the login frame and show the main chat + send frames.
        """
        self.login_frame.pack_forget()
        self.chat_frame.pack(padx=10, pady=5)
        self.send_frame.pack(padx=10, pady=5)

    def _on_message_received(self, sender: str, text: str):
        """
        Callback: a private message arrived from `sender`.
        Wrap in root.after to ensure we update widgets on the GUI thread.
        """

        def handle():
            self._append_chat(f"{sender}: {text}\n")

        self.root.after(0, handle)

    def _on_user_list_updated(self, users: list[str]):
        """
        Callback: the list of active users updated.
        Wrap in root.after to update the Listbox on the GUI thread.
        """

        def handle():
            self.users_listbox.delete(0, tk.END)
            for u in users:
                if u != self.username:
                    self.users_listbox.insert(tk.END, u)

        self.root.after(0, handle)

    def _on_error(self, error_text: str):
        """
        Callback: the server returned an error action.
        Display it in the chat area (wrapped in root.after for thread safety).
        """

        def handle():
            self._append_chat(f"[Error] {error_text}\n")

        self.root.after(0, handle)

    def _on_disconnected(self):
        """
        Callback: the connection to the server was lost (or client disconnected).
        """

        def handle():
            self._append_chat("*** Disconnected from server ***\n")
            self.send_btn.config(state="disabled")
            self.send_file_btn.config(state="disabled")

        self.root.after(0, handle)

    def _send_message(self):
        """
        Called when the user clicks "Send".
        Reads "To" and "Message" fields, calls chat_client.send_message,
        and appends the local "Me ->" line to the chat widget.
        """
        to_user = self.to_entry.get().strip()
        text = self.msg_entry.get().strip()
        if not to_user or not text:
            messagebox.showwarning("Warning", "Both 'To' and 'Message' fields must be filled.")
            return

        self.chat_client.send_message(to_user, text)
        self._append_chat(f"Me -> {to_user}: {text}\n")
        self.msg_entry.delete(0, tk.END)

    def _send_file(self):
        """
        "Send file" button handler.
        Opens a file selection dialog and initiates sending to the selected user.
        """
        to_user = self.to_entry.get().strip()
        if not to_user:
            messagebox.showwarning("Warning", "'To' field must be filled to send a file.")
            return
        file_path = filedialog.askopenfilename(title="Select file to send")
        if not file_path:
            return  # User canceled the file selection
        filename = os.path.basename(file_path)
        self._pending_file_send = (to_user, file_path, filename)
        self.chat_client.send_file_request(to_user, file_path)
        self._append_chat(f"Me -> {to_user}: sends a file '{filename}'.\n")

    def _on_file_request(self, sender: str, filename: str, filesize: int, filetype: str):
        """
        Callback: a request to transfer a file was received from the sender.
        Shows a dialog asking about accepting the file.
        If you agree, opens a dialog to select a folder and saves the path for further chunks.
        """

        def handle():
            msg = f"User {sender} offers to accept the file '{filename}' ({filesize} bytes, typ {filetype}). Accept?"
            if messagebox.askyesno("Accept file?", msg):
                save_dir = filedialog.askdirectory(title="Select a folder to save the file")
                if not save_dir:
                    self.chat_client.send_file_cancel(sender, filename, "User canceled the file selection")
                    self._append_chat(f"[Failure] {sender} -> {self.username}: refusal to accept file '{filename}' ("
                                      f"folder is not selected).\n")
                    return
                save_path = os.path.join(save_dir, filename)
                self._receiving_files[(sender, filename)] = save_path
                self.chat_client.send_file_accept(sender, filename)
                self._append_chat(f"[Success] {sender} -> {self.username}: file accepted '{filename}'.\n")
            else:
                self.chat_client.send_file_cancel(sender, filename, "User refused.")
                self._append_chat(f"[Failure] {sender} -> {self.username}: refusal to accept file '{filename}'.\n")

        self.root.after(0, handle)

    def _on_file_accept(self, sender: str, filename: str):
        """
        Callback: sender accepted the file transfer request.
        If this is our file, we start sending chunks.
        """

        def handle():
            self._append_chat(f"{sender} accepted file '{filename}'.\n")
            if self._pending_file_send and self._pending_file_send[0] == sender \
                    and self._pending_file_send[2] == filename:
                to_user, file_path, _ = self._pending_file_send
                threading.Thread(
                    target=self._send_file_chunks,
                    args=(to_user, file_path, filename),
                    daemon=True
                ).start()
                self._pending_file_send = None

        self.root.after(0, handle)

    def _on_file_cancel(self, sender: str, filename: str, reason: str):
        """
        Callback: sender or recipient canceled file transfer.
        A cancellation message (with a reason, if specified) is recorded in the chat.
        """

        def handle():
            if reason:
                self._append_chat(f"[Refusal] {sender} canceled file transfer '{filename}': {reason}.\n")
            else:
                self._append_chat(f"[Refusal] {sender} canceled file transfer '{filename}'.\n")

        self.root.after(0, handle)

    def _on_file_data(self, sender: str, filename: str, data: bytes, is_last_chunk: bool):
        """
        Callback: received a file chunk from the sender.
        Saves the chunk to a file at the path selected when accepting the file.
        """

        def handle():
            key = (sender, filename)
            save_path = self._receiving_files.get(key)
            if not save_path:
                # If the path is not found, ignore the chunk or display an error
                self._append_chat(f"[Error] Unknown file '{filename}' from {sender}, chunk is ignored.\n")
                return
            with open(save_path, "ab") as f:
                f.write(data)
            if is_last_chunk:
                # self._append_chat(f"[Success] {sender} -> {self.username}: file transfer '{filename}' completed.\n")
                del self._receiving_files[key]

        self.root.after(0, handle)

    def _on_file_complete(self, sender: str, filename: str):
        """
        Callback: file transfer is completed.
        A success message is recorded in the chat.
        """

        def handle():
            self._append_chat(f"[Success] {sender} -> {self.username}: file transfer '{filename}' is completed.\n")

        self.root.after(0, handle)

    def _append_chat(self, text: str):
        """
        Inserts a line of text into the chat Text widget.
        Always called from the GUI thread (via root.after).
        """
        self.chat_text.config(state="normal")
        self.chat_text.insert(tk.END, text)
        self.chat_text.see(tk.END)
        self.chat_text.config(state="disabled")

    def _on_closing(self):
        """
        Called when the user attempts to close the window (WM_DELETE_WINDOW).
        Cleanly disconnect from the server and destroy the GUI.
        """
        if self.chat_client.running:
            self.chat_client.disconnect()
        self.root.destroy()

    def _send_file_chunks(self, to_user, file_path, filename, chunk_size=4096):
        """
        Reads the file in chunks and sends the chunks via chat_client.send_file_data,
        then sends file_complete.
        """
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
            self._append_chat(f"[Error] Failed to send file '{filename}': {e}\n")


if __name__ == "__main__":
    # Create the main window and launch ChatUI
    root = tk.Tk()
    ui = ChatUI(root, server_host="16.170.226.19", server_port=7777)
    root.mainloop()
