# Network Messaging Application
The network messaging app with the client-server architecture that follows TCP for communication.

- It allows a real-time messaging and file transfer.
- The client has Tkinter-based GUI.
- The server part is deployed with AWS. 

When you clone the project you can start only clients and it's ready to use.


## Prerequirements
Python version 3.6+ is needed for tkinter.

## Setup Guide
Follow the next steps to run this app locally: 

1. **Clone repository**
   ```console
   git clone https://github.com/leragogogo/messaging_app.git
   cd messaging_app
   ```

2. **Start the server**
   ```console
    python3 -m server.server
    ```
3. **Change server host to localhost**

   in client/client_ui change the main method to:

   ```python
    if __name__ == "__main__":
      # Create the main window and launch ChatUI
      root = tk.Tk()
      ui = ChatUI(root, server_host="127.0.0.1", server_port=7777)
      root.mainloop()
    ```
5. **Start the client**
   ```console
    python3 -m client.chat_ui
    ```
