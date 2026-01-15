import socket
import struct

HOST = '0.0.0.0'
PORT = 211

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind((HOST, PORT))
s.listen(5)

print("Listening on port 211...")

while True:
    conn, addr = s.accept()
    print("Connection from", addr)

    data = conn.recv(1024)
    print("Received request:")
    print(data.decode(errors="ignore"))


    conn.sendall(
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Length: 100\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Hello, this will be reset"
    )

    conn.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_LINGER,
        struct.pack('ii', 1, 0)
    )

    conn.close()