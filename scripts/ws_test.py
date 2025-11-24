import json
import ssl
import threading
import time

try:
    import websocket
except Exception:
    websocket = None

URL = "https://crash.turbogg4u.online/ws/v2/game/?playerId=playnabet-weebet%3Aplayer63314&token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJjdXN0b21lcklkIjo3MTgsImlkIjoicGxheWVyNjMzMTQiLCJkaXNwbGF5TmFtZSI6IkRFTk5JUyIsInN1YiI6InBsYXluYWJldC13ZWViZXRAcGxheWVyNjMzMTQiLCJ0b2tlbiI6ImV5SjBlWEFpT2lKS1YxUWlMQ0poYkdjaU9pSklVekkxTmlKOS5Xell6TXpFMFhRLjFCeFJHYWw2MnBvdWgyVFU5Z2JlQ3NJak9mUFBVUDFXcVFZNVp1blZpc28iLCJjdXJyZW5jeSI6ImJybCIsImlzVGVzdCI6ZmFsc2UsImN1c3RvbWVyUGxheWVySWQiOiJwbGF5ZXI2MzMxNCIsInNpZCI6IjAxOWFiMjk3LTQzNjUtNzE0NS1hNzQ5LTNkZGRiODhmNGQ1NyIsImlhdCI6MTc2MzkzMzE1NX0.3jbw4fuRyIe_cq0TY_j4fxwagIqex9VwD8KgrrRseOM"

def to_wss(u: str) -> str:
    if u.startswith("https://"):
        return "wss://" + u[len("https://"):]
    if u.startswith("http://"):
        return "ws://" + u[len("http://"):]
    return u

def pretty(obj: str) -> str:
    try:
        return json.dumps(json.loads(obj), ensure_ascii=False, indent=2)
    except Exception:
        return obj

def main():
    if websocket is None:
        print("Biblioteca websocket-client não encontrada. Instale com: pip install websocket-client")
        return

    url = to_wss(URL)
    print(f"Conectando a: {url}")
    msgs = []
    closed = threading.Event()

    def on_open(ws):
        print("WS aberto")

    def on_message(ws, message):
        msgs.append(message)
        print("Mensagem recebida:")
        print(pretty(message))

    def on_error(ws, error):
        print(f"Erro: {error}")

    def on_close(ws, close_status_code, close_msg):
        print(f"WS fechado: code={close_status_code} reason={close_msg}")
        closed.set()

    ws = websocket.WebSocketApp(
        url,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    def stopper():
        try:
            time.sleep(30)
            try:
                ws.close()
            except Exception:
                pass
        except Exception:
            pass

    threading.Thread(target=stopper, daemon=True).start()

    try:
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
    except KeyboardInterrupt:
        try:
            ws.close()
        except Exception:
            pass

    print("Resumo:")
    print(f"Total de mensagens: {len(msgs)}")
    if msgs:
        print("Primeira mensagem:")
        print(pretty(msgs[0]))

if __name__ == "__main__":
    main()

