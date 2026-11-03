#!/usr/bin/env python3
"""Exercise local account/character services; creates one diagnostic player."""
import argparse
import http.client
import json
import secrets
import socket
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pkxd_server import wire
from pkxd_server.accounts import AUTH, SIGN_UP, USER
from pkxd_server.startup import PET_STORE_ID, STORE_IDS


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
            expected = {"p", "o", "wa", "j", "s", "i", "hs", "k", "m", "A", "I", "r"}
            received = set()
            for _ in range(14):
                name, payload = wire.parse_event(wire.receive(sock))
                if name == "tbulv":
                    _, key, value = wire.parse_variable(payload)
                    received.add(key)
                    if key == "p":
                        if value[:1] != b"\x06" or len(value) <= 1 or (len(value) - 1) % 8:
                            raise ValueError("Inventário inicial ausente ou sem pares ID/quantidade")
                        if any(wire.I32.unpack(value[offset:offset + 4])[0] <= 0
                               for offset in range(1, len(value), 4)):
                            raise ValueError("ID ou quantidade inválida no inventário inicial")
            if not expected <= received:
                raise ValueError("Faltaram variáveis do personagem inicial")
            return sock, response, wire.I32.unpack(connected[1:5])[0]
        except BaseException:
            sock.close()
            raise

    first_socket, _, transport_id = login()
    with first_socket as sock:
        print("OK: conexão, login e estado inicial do personagem")
        # Client writes omit owner ID; server notifications include it.
        skin = b"\x05\x10\x20\x30"
        sock.sendall(wire.frame(wire.event("tbulv", wire.client_variable_update("j", skin), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        if name != "tbulv" or wire.parse_variable(payload) != (transport_id, "j", skin):
            raise ValueError("Atualização de variável no formato nativo não confirmada")
        print("OK: atualização de variável no formato nativo sem desconexão")
        # The client chooses its spawn from the Unity scene. Use synthetic finite
        # coordinates only to verify server reception, not to claim an APK spawn.
        world_requests = [("slot_interaction", wire.number(1, 2) + wire.string(3, user["userId"])),
                          ("pet", wire.number(1, 13)), ("vhc", b""), ("vhc", wire.number(1, 5))]
        for event_name, body in world_requests:
            sock.sendall(wire.frame(wire.event(event_name, body, room=True)))
        expected_world = [("n", b""), ("pet", b"\x08\x13"), ("vhc", b"\x10\x01"), ("vhc", b"\x08\x05")]
        for expected in expected_world:
            if wire.parse_event(wire.receive(sock)) != expected:
                raise ValueError("Resposta de inicialização da sala inválida")
        for event_name, body in (("C", struct.pack(">BBffff", 1, 255, 1., 2., 3., 90.)),
                                 ("PL", struct.pack(">iBffff", 0, 0, 1., 2., 3., 90.))):
            sock.sendall(wire.frame(wire.event(event_name, body, room=True)))
        sock.sendall(wire.frame(bytes((wire.PING,))))
        if wire.receive(sock) != bytes((wire.PONG,)):
            raise ValueError("A sala não manteve a conexão após posição e camada")
        print("OK: sala local, consultas de veículos/pets, posição e camada sem desconexão")
        # These requests blocked the reported Android startup before profile creation.
        requests = [("time", b"", "time", None)]
        requests += [("store_tree", wire.string(2, store_id), "L", store_id) for store_id in STORE_IDS]
        requests += [("pet_store_tree", wire.string(2, PET_STORE_ID), "PST", PET_STORE_ID)]
        sock.sendall(b"".join(wire.frame(wire.event(name, payload, room=True))
                              for name, payload, _, _ in requests))
        for _, _, expected, store_id in requests:
            name, payload = wire.parse_event(wire.receive(sock))
            response = wire.Proto(payload)
            if name != expected:
                raise ValueError("Evento de inicialização incorreto")
            if expected == "time":
                if abs(response.integer(2) - time.time()) > 5:
                    raise ValueError("Horário do servidor não está em segundos Unix")
            elif (not response.integer(1)
                  or response.message(4 if expected == "PST" else 3).text(1) != store_id):
                raise ValueError("Catálogo de inicialização não confirmado")
        print("OK: horário do servidor e catálogos locais de inicialização")
        sock.sendall(wire.frame(wire.event("backpack", b"\x08\x02", room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        favorites = wire.Proto(payload)
        if name != "backpack" or favorites.integer(1) != 2 or 2 not in favorites.fields:
            raise ValueError("Resposta inicial de favoritos não confirmada")
        sock.sendall(wire.frame(wire.event("pet", wire.number(1, 16) + wire.string(2, user["userId"]), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        if name != "pet" or wire.Proto(payload).integer(1) != 21:
            raise ValueError("Resposta de necessidades de pets não confirmada")
        print("OK: inventário inicial, favoritos da mochila e necessidades de pets")
        post_inventory = [("hair_style", b"", "get_hair_styles", b"\x08\x01"),
                          ("lb", b"", "lb", b"\x18\x01"),
                          ("init_pos", b"", "C", b"\x03\x00"),
                          ("init_day_night", b"", "G", b"\x10\x01"),
                          ("pet", b"\x08\x13", "pet", b"\x08\x18"),
                          ("pet", b"\x08\x18", "pet", b"\x08\x20")]
        sock.sendall(b"".join(wire.frame(wire.event(name, payload, room=True))
                              for name, payload, _, _ in post_inventory))
        for _, _, expected_name, expected_payload in post_inventory:
            if wire.parse_event(wire.receive(sock)) != (expected_name, expected_payload):
                raise ValueError("Resposta de inicialização após o inventário não confirmada")
        print("OK: cabelo, lootboxes, detalhes de pets/ovos e estado inicial da sala")
        nickname = "Local" + secrets.token_hex(4)
        sock.sendall(wire.frame(wire.event("profile_update", wire.string(2, nickname), room=True)))
        name, payload = wire.parse_event(wire.receive(sock))
        if name != "set_name_result" or wire.Proto(payload).text(1) != nickname:
            raise ValueError("Nome não confirmado pelo servidor")
    sock, response, _ = login()
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
