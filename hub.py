#!/usr/bin/env python3
"""Hub KorLab Lights: puente WebSocket entre la web de escenas y los LEDs.

- Escucha en el puerto 8765 (WebSocket). Ahi se conectan:
  * los ESP32 del firmware luces_estaticas_kor  (role "device")
  * la web preview-escenas.html                 (role "ui")
  * cualquier script de validacion             (role "controller")
- Responde en el puerto 8767 (UDP) al discovery del firmware con
  "KORLAB_WS <ip> 8765", tal como lo espera udpDiscoverServer() en main.cpp.

Como se usa:
    python3 hub.py                 # autodetecta la IP local
    python3 hub.py --ip 192.168.68.75
    python3 hub.py --discovery off # solo WS, sin responder discovery

Sin dependencias externas: usa asyncio + websockets si estan disponibles y,
si no, un mini servidor WebSocket propio (suficiente para este protocolo).
"""
import argparse
import asyncio
import json
import signal
import socket
import sys
from datetime import datetime

WS_PORT = 8765
DISCOVERY_PORT = 8767
DISCOVERY_MAGIC = "KORLAB_LIGHTS_DISCOVERY"
DISCOVERY_RESPONSE_PREFIX = "KORLAB_WS"

try:
    import websockets  # type: ignore
    HAVE_WEBSOCKETS = True
except Exception:  # pragma: no cover
    HAVE_WEBSOCKETS = False


def log(msg: str) -> None:
    print("[{}] {}".format(datetime.now().strftime("%H:%M:%S"), msg), flush=True)


def detectar_ip() -> str:
    """IP local en la subred del WiFi (misma tecnica que usaría el ESP32)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def log_hub_socket(sock: socket.socket) -> None:
    ip = sock.getsockname()[0]
    log("UDP discovery escuchando en 0.0.0.0:{} (respondere {} {} {})".format(
        DISCOVERY_PORT, DISCOVERY_RESPONSE_PREFIX, ip, WS_PORT))


async def udp_discovery_server(ip: str) -> None:
    """Responde 'KORLAB_WS <ip> 8765' a cada paquete discovery del firmware."""
    loop = asyncio.get_event_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", DISCOVERY_PORT))
    sock.setblocking(False)
    log_hub_socket(sock)
    respuesta = "{} {} {}".format(DISCOVERY_RESPONSE_PREFIX, ip, WS_PORT).encode()
    while True:
        data, addr = await loop.sock_recvfrom(sock, 256)
        texto = data.decode("utf-8", "replace").strip()
        if not texto.startswith(DISCOVERY_MAGIC):
            continue
        log("UDP discovery de {} -> respuesta {}".format(addr[0], respuesta.decode()))
        await loop.sock_sendto(sock, respuesta, addr)


class Hub:
    def __init__(self):
        self.clientes = {}  # websocket -> {"role": str, "ip": str}

    def broadcast(self, texto: str, excluir=None) -> None:
        for ws, info in list(self.clientes.items()):
            if ws is excluir:
                continue
            try:
                asyncio.ensure_future(self._enviar(ws, texto))
            except Exception:
                pass

    async def _enviar(self, ws, texto: str) -> None:
        try:
            await ws.send(texto)
        except Exception:
            self.quitar(ws)

    def quitar(self, ws) -> None:
        info = self.clientes.pop(ws, None)
        if info:
            log("{} {} desconectado ({})".format(info["role"], info["ip"], info.get("nombre", "")))

    def es_dispositivo(self, info) -> bool:
        return info and info.get("role") == "device"

    def dispositivos(self):
        return [i for i in self.clientes.values() if i.get("role") == "device"]

    async def manejar(self, ws) -> None:
        ip = getattr(ws, "remote_address", ("?", 0))[0]
        nombre = ""
        registrado = False
        info = {"role": "", "ip": ip, "nombre": ""}
        self.clientes[ws] = info
        log("conexion entrante desde {}".format(ip))
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                tipo = msg.get("type", "")

                if tipo == "hello":
                    role = msg.get("role", "")
                    mac = msg.get("mac", "")
                    if role == "device" and mac:
                        nombre = "ESP32 " + mac
                    elif role:
                        nombre = role
                    info["role"] = role or "desconocido"
                    info["nombre"] = nombre or info["role"]
                    if not registrado:
                        registrado = True
                        log("hello: {} {} ({} dispositivos en el hub)".format(
                            info["role"], nombre or "", len(self.dispositivos())))
                    await ws.send(json.dumps({
                        "type": "welcome", "role": info["role"], "ip": ip}))
                    continue

                if tipo == "ping":
                    await ws.send(json.dumps({"type": "pong"}))
                    continue

                if not registrado:
                    log("mensaje sin hello, ignorado: {}".format(tipo))
                    continue

                # Todo lo demas se difunde tal cual al resto.
                log("-> {}".format(raw[:180]))
                if self.es_dispositivo(info):
                    # El ESP32 habla: eventos como timer_mode van a la UI.
                    self.broadcast(raw, excluir=ws)
                else:
                    # La web habla: load_scene/config/etc van a los ESP32.
                    destino = [w for w, i in self.clientes.items()
                               if self.es_dispositivo(i)]
                    log("   a {} dispositivo(s)".format(len(destino)))
                    for w in destino:
                        await self._enviar(w, raw)
        except Exception as e:
            log("error de conexion {}: {}".format(ip, e))
        finally:
            self.quitar(ws)


# ---------------------------------------------------------------------------
# Fallback: mini servidor WS sin dependencias (RFC 6455 minimo: handshake,
# texto y close). Solo se usa si 'websockets' no esta instalado.
# ---------------------------------------------------------------------------
class MiniWS:
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader, self.writer = reader, writer
        self.remote_address = writer.get_extra_info("peername")
        self.abierto = True

    async def handshake(self) -> bool:
        datos = b""
        while b"\r\n\r\n" not in datos:
            chunk = await self.reader.read(4096)
            if not chunk:
                return False
            datos += chunk
            if len(datos) > 16384:
                return False
        cabeceras = {}
        for linea in datos.split(b"\r\n"):
            if b":" in linea:
                k, v = linea.split(b":", 1)
                cabeceras[k.strip().lower().decode()] = v.strip().decode()
        if "websocket" not in cabeceras.get("upgrade", "").lower():
            return False
        import base64, hashlib
        accept = base64.b64encode(
            hashlib.sha1((cabeceras.get("sec-websocket-key", "") + self.GUID).encode()).digest()
        ).decode()
        resp = ("HTTP/1.1 101 Switching Protocols\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                "Sec-WebSocket-Accept: {}\r\n\r\n").format(accept)
        self.writer.write(resp.encode())
        await self.writer.drain()
        return True

    async def recv(self) -> bytes:
        if not self.abierto:
            return b""
        cab = await self.reader.readexactly(2)
        fin_opcode = cab[0]
        mascara = (cab[1] & 0x80) != 0
        largo = cab[1] & 0x7F
        if largo == 126:
            largo = int.from_bytes(await self.reader.readexactly(2), "big")
        elif largo == 127:
            largo = int.from_bytes(await self.reader.readexactly(8), "big")
        clave = await self.reader.readexactly(4) if mascara else b""
        payload = await self.reader.readexactly(largo) if largo else b""
        if mascara:
            payload = bytes(b ^ clave[i % 4] for i, b in enumerate(payload))
        if fin_opcode & 0x0F == 8:  # close
            self.abierto = False
            self.writer.write(b"\x88\x00")
            await self.writer.drain()
            return b""
        if fin_opcode & 0x0F == 9:  # ping
            pong = b"\x8A\x00"
            self.writer.write(pong)
            await self.writer.drain()
            return await self.recv()
        return payload

    async def send(self, texto: str) -> None:
        payload = texto.encode()
        cab = bytearray([0x81])
        n = len(payload)
        if n < 126:
            cab.append(n)
        elif n < 65536:
            cab.append(126)
            cab += n.to_bytes(2, "big")
        else:
            cab.append(127)
            cab += n.to_bytes(8, "big")
        self.writer.write(bytes(cab) + payload)
        await self.writer.drain()

    async def cerrar(self) -> None:
        self.abierto = False
        try:
            self.writer.close()
        except Exception:
            pass


async def mini_manejar(reader, writer, hub: Hub) -> None:
    ws = MiniWS(reader, writer)
    if not await ws.handshake():
        writer.close()
        return
    ip = (ws.remote_address or ("?", 0))[0]
    info = {"role": "", "ip": ip, "nombre": ""}
    hub.clientes[ws] = info
    log("conexion entrante desde {} (mini servidor)".format(ip))
    try:
        while True:
            raw_b = await ws.recv()
            if not raw_b:
                break
            raw = raw_b.decode("utf-8", "replace")
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            tipo = msg.get("type", "")
            if tipo == "hello":
                info["role"] = msg.get("role", "desconocido")
                info["nombre"] = msg.get("mac", "") or info["role"]
                log("hello: {} {} ({} dispositivos en el hub)".format(
                    info["role"], info["nombre"], len(hub.dispositivos())))
                await ws.send(json.dumps({"type": "welcome", "role": info["role"], "ip": ip}))
                continue
            if tipo == "ping":
                await ws.send(json.dumps({"type": "pong"}))
                continue
            log("-> {}".format(raw[:180]))
            if hub.es_dispositivo(info):
                hub.broadcast(raw, excluir=ws)
            else:
                for w, i in list(hub.clientes.items()):
                    if hub.es_dispositivo(i):
                        await w.send(raw)
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        hub.quitar(ws)
        await ws.cerrar()


async def main() -> None:
    ap = argparse.ArgumentParser(description="Hub KorLab Lights (WS 8765 + discovery UDP 8767)")
    ap.add_argument("--ip", default=None, help="IP que se anuncia por discovery")
    ap.add_argument("--discovery", default="on", choices=["on", "off"])
    args = ap.parse_args()

    ip = args.ip or detectar_ip()
    hub = Hub()

    if args.discovery == "on":
        asyncio.ensure_future(udp_discovery_server(ip))
    else:
        log("discovery UDP desactivado")

    log("IP anunciada: {} | WS en 0.0.0.0:{}".format(ip, WS_PORT))
    log("esperando ESP32 (role=device) y la web preview-escenas.html (role=ui)...")

    if HAVE_WEBSOCKETS:
        import websockets  # type: ignore

        async with websockets.serve(hub.manejar, "0.0.0.0", WS_PORT):
            await asyncio.Future()
    else:
        log("AVISO: 'websockets' no instalado; usando mini servidor propio")
        servidor = await asyncio.start_server(
            lambda r, w: mini_manejar(r, w, hub), "0.0.0.0", WS_PORT)
        await servidor.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("hub detenido")
        sys.exit(0)
