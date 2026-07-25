#!/usr/bin/env python3
"""Loopback TCP proxy transported through an SSH remote `nc` command."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import threading


def copy_socket_to_pipe(client: socket.socket, pipe) -> None:
    try:
        while chunk := client.recv(65536):
            os.write(pipe.fileno(), chunk)
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    finally:
        try:
            pipe.close()
        except OSError:
            pass


def copy_pipe_to_socket(pipe, client: socket.socket) -> None:
    try:
        while chunk := os.read(pipe.fileno(), 65536):
            client.sendall(chunk)
    except (BrokenPipeError, ConnectionError, OSError):
        pass
    finally:
        try:
            client.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def handle(client: socket.socket, ssh_host: str, target_host: str, target_port: int) -> None:
    process = subprocess.Popen(
        ["ssh", "-T", ssh_host, "nc", target_host, str(target_port)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    assert process.stdin is not None and process.stdout is not None
    upstream = threading.Thread(
        target=copy_socket_to_pipe, args=(client, process.stdin), daemon=True
    )
    downstream = threading.Thread(
        target=copy_pipe_to_socket, args=(process.stdout, client), daemon=True
    )
    upstream.start()
    downstream.start()
    upstream.join()
    downstream.join()
    client.close()
    if process.poll() is None:
        process.terminate()
    process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen-port", type=int, required=True)
    parser.add_argument("--ssh-host", required=True)
    parser.add_argument("--target-host", default="127.0.0.1")
    parser.add_argument("--target-port", type=int, required=True)
    args = parser.parse_args()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", args.listen_port))
        server.listen(8)
        while True:
            client, _ = server.accept()
            threading.Thread(
                target=handle,
                args=(client, args.ssh_host, args.target_host, args.target_port),
                daemon=True,
            ).start()


if __name__ == "__main__":
    main()
