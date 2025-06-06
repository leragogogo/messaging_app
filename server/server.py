import socket
import threading
import json
import time
import protocol

HOST = '0.0.0.0'  # listen to all interfaces
PORT = 7777

# Dictionary of all active clients:
#  username -> {'conn': socket_obj, 'addr': (ip,port), 'last_ping': timestamp}
clients = {}
clients_lock = threading.Lock()


def send_json(conn, data: dict):
    """
    Write in JSON socket a line + '\n'
    """
    try:
        text = json.dumps(data, ensure_ascii=False) + '\n'
        conn.sendall(text.encode('utf-8'))
    except Exception as e:
        print(f"Error sending to {conn}: {e}")


def broadcast_user_list():
    """
    Send all connected clients a list of active users.
    """
    with clients_lock:
        user_list = list(clients.keys())
        payload = {'action': protocol.ACTION_USER_LIST, 'users': user_list}
        for username, data in clients.items():
            try:
                send_json(data['conn'], payload)
            except:
                pass


def remove_client(username: str):
    """
    Remove `username` from the active clients dictionary and broadcast the new list.
    """
    with clients_lock:
        if username in clients:
            print(f"[REMOVE CLIENT] Removing '{username}' from active list.")
            try:
                clients[username]['conn'].close()
            except Exception:
                pass
            del clients[username]
    broadcast_user_list()


def register_client(conn: socket.socket, addr) -> (str | None, str | None):
    """
    Handle the initial registration packet from a connecting socket.
    Expects a line like: {"action":"connect","username":"desired_name"}.
    Returns a tuple (username, error_message):
      - If registration succeeds, returns (username, None).
      - If registration fails (malformed JSON, missing fields, or name taken),
        returns (None, "<error_description>").
    """
    try:
        # Wrap socket with a file‐like object for readline()
        file_obj = conn.makefile(mode='r', encoding='utf-8')
        line = file_obj.readline()
        if not line:
            return None, "no data received"

        data = json.loads(line)
        if data.get('action') != protocol.ACTION_CONNECT or 'username' not in data:
            return None, "invalid connect protocol"

        requested_user = data['username']
    except json.JSONDecodeError:
        return None, "malformed JSON"
    except Exception as e:
        return None, f"error reading registration: {e}"

    # Check if username is already taken
    with clients_lock:
        if requested_user in clients:
            return None, "username already taken"

        # Otherwise, register the new client
        clients[requested_user] = {
            'conn': conn,
            'addr': addr,
            'last_ping': time.time()
        }
        print(f"[REGISTERED] '{requested_user}' from {addr}")

    return requested_user, None


def handle_client(conn: socket.socket, addr):
    """
    Handle all communication with a single client socket `conn`.
    Steps:
      1. Read the initial registration ("connect") packet.
      2. If registration fails, send an error and close.
      3. If succeeds, send back {"action":"connect","status":"ok"} and broadcast new user list.
      4. Enter a loop to process incoming JSON lines:
         - "ping" -> update last_ping timestamp
         - "message" -> forward to the specified recipient
         - "disconnect" -> break and clean up
         - Anything else -> send back an error
      5. When loop ends (client closed or timed out), remove client and broadcast updated list.
    """
    print(f"[NEW CONNECTION] Client from {addr} connected.")

    # Step 1: Register the client
    username, err = register_client(conn, addr)
    if not username:
        # Registration failed: send error and close socket
        error_payload = {'action': protocol.ACTION_CONNECT, 'status': 'error', 'error': err}
        send_json(conn, error_payload)
        print(f"[REGISTRATION FAILED] {addr} -> {err}")
        conn.close()
        return

    # Step 2: Inform client that registration succeeded
    send_json(conn, {'action': protocol.ACTION_CONNECT, 'status': 'ok'})
    broadcast_user_list()

    file_obj = conn.makefile(mode='r', encoding='utf-8')
    try:
        while True:
            line = file_obj.readline()
            if not line:
                # Client closed the socket
                print(f"[DISCONNECT] '{username}' closed connection.")
                break

            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                # Skip any malformed JSON
                continue

            action = msg.get('action')

            if action == protocol.ACTION_PING:
                # Client heartbeat: update last_ping
                with clients_lock:
                    if username in clients:
                        clients[username]['last_ping'] = time.time()

            elif action == protocol.ACTION_MESSAGE:
                # Private message: {"action":"message","to":"bob","message":"Hello"}
                target = msg.get('to')
                text = msg.get('message', '')

                if not target or not text:
                    send_json(conn, {'action': protocol.ACTION_ERROR, 'error': 'wrong message format'})
                    continue

                with clients_lock:
                    if target in clients:
                        # Forward message to the recipient
                        payload = {'action': protocol.ACTION_MESSAGE, 'from': username, 'message': text}
                        send_json(clients[target]['conn'], payload)
                    else:
                        # Recipient not found or offline
                        send_json(conn, {'action': protocol.ACTION_ERROR, 'error': f'user {target} not found'})

            elif action == protocol.ACTION_DISCONNECT:
                # Client requested a clean disconnect
                print(f"[DISCONNECT REQUEST] '{username}' requested disconnect.")
                break

            else:
                # Unknown action: inform the client
                send_json(conn, {'action': protocol.ACTION_ERROR, 'error': 'unknown action'})

    except Exception as e:
        print(f"[EXCEPTION] Error handling '{username}': {e}")

    finally:
        # Step 5: Clean up
        remove_client(username)
        try:
            conn.close()
        except:
            pass


def inactive_checker():
    """
    Background thread, which every 30 seconds checks all clients,
    and if a client didn't ping for more that 120 seconds, doesn't count them as active.
    """
    while True:
        time.sleep(30)
        now = time.time()
        removed = []
        with clients_lock:
            for user, data in list(clients.items()):
                if now - data['last_ping'] > 120:
                    print(f"[TIMEOUT] {user}")
                    try:
                        data['conn'].shutdown(socket.SHUT_RDWR)
                        data['conn'].close()
                    except:
                        pass
                    removed.append(user)
                    del clients[user]
        if removed:
            broadcast_user_list()


def start_server():
    """
    Create a socket, listen to connections, for each run handle_client in a separate thread.
    """
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()
    print(f"[STARTED] Server is listening on {HOST}:{PORT}")

    # Run background thread to check inactive clients.
    checker_thread = threading.Thread(target=inactive_checker, daemon=True)
    checker_thread.start()

    try:
        while True:
            conn, addr = server.accept()
            client_thread = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            client_thread.start()
    except KeyboardInterrupt:
        print("\n[SHUTTING DOWN] Server is shutting down.")
    finally:
        server.close()


if __name__ == '__main__':
    start_server()
