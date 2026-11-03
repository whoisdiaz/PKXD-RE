#!/usr/bin/env python3
"""Exercise local account/character services; creates one diagnostic player."""
import argparse
import http.client
import json
import secrets
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pkxd_server import wire
from pkxd_server.accounts import AUTH, SIGN_UP, USER


def check(host, port):
    def post(path, body):
        connection = http.client.HTTPConnection(host, port, timeout=5)
        try:
            connection.request("POST", path, json.dumps(body), {"Content-Type": "application/json"})
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError(f"{path}: HTTP {response.status}")
            return json.loads(response.read())
        finally:
            connection.close()

    identity = post(SIGN_UP, {"deviceInfo": {}})
    auth = post(AUTH, {"identityProvider": "FASTER", "credentials": {"type": "TOKEN", "token": identity["token"]}})
    user = post(USER, {"authToken": auth["authToken"]})
    print("OK: identidade anônima e sessões locais")
    allocation = post("/lobby/allocation", {"userToken": user["userToken"],
                      "gameServerProtocolVersion": "0.2.49", "isPrivate": False})
    if not allocation["successful"]:
        raise ValueError("A versão não foi liberada pelo lobby")
    destination = allocation["gameServerAddress"], allocation["gameServerPort"]
    print("OK: permissão de versão e destino TCP")

    def login():
        sock = socket.create_connection(destination, timeout=5)
        try:
            sock.sendall(wire.frame(b"\x03"))
            connected = wire.receive(sock)
            if connected[0] != 3 or len(connected) < 6:
                raise ValueError("Resposta TCP Connected inválida")
            sock.sendall(wire.frame(wire.event("login", wire.string(1, user["userToken"]) + wire.string(3, "1.38.4"))))
            name, payload = wire.parse_event(wire.receive(sock))
            response = wire.Proto(payload)
            if name != "login" or not response.integer(1):
                raise ValueError("Login TCP recusado")
            if wire.receive(sock)[0] != 6:
                raise ValueError("A sala inicial não chegou")
            expected = {"p", "o", "wa", "j", "s", "i", "hs", "k", "m"}
            received = set()
            for _ in range(11):
                name, payload = wire.parse_event(wire.receive(sock))
                if name == "tbulv":
                    received.add(wire.parse_variable(payload)[1])
            if not expected <= received:
                raise ValueError("Faltaram variáveis do personagem inicial")
            return sock, response
        except BaseException:
            sock.close()
            raise

    with login()[0] as sock:
        print("OK: conexão, login e estado inicial do personagem")
        nickname = "Local" + secrets.token_hex(4)
        sock.sendall(wire.frame(wire.event("profile_update", wire.string(2, nickname), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        if name != "set_name_result" or wire.Proto(payload).text(1) != nickname:
            raise ValueError("Nome não confirmado pelo servidor")
    sock, response = login()
    with sock:
        if response.integer(3):
            raise ValueError("O personagem voltou como novo após reconectar")
    print("OK: nome salvo e personagem recuperado na reconexão")
    print("Diagnóstico concluído. A tela do APK ainda precisa ser testada no aparelho.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    try:
        check(args.host, args.port)
    except (OSError, ValueError, KeyError, EOFError) as error:
        # No request/response dumps: they contain account credentials.
        parser.exit(1, f"Falha no diagnóstico local: {type(error).__name__}. Confira as portas e o console do servidor.\n")


if __name__ == "__main__":
    main()
