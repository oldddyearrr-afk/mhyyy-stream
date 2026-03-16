import os
import subprocess
import time
import threading
import zmq
import urllib.request
import json

INPUT_URL  = os.environ.get("INPUT_URL",  "")
OUTPUT_URL = os.environ.get("OUTPUT_URL", "")
GIST_ID    = os.environ.get("GIST_ID",   "")
GH_TOKEN   = os.environ.get("GH_TOKEN",  "")

ZMQ_PORT = 5556

overlay_config = {
    "text": "",
    "visible": False,
    "style": "scroll",
    "position_y": 90,
    "font_size": 48,
    "color": "white",
    "bg": True
}

# ── ZMQ ──
zmq_context = zmq.Context()

def send_zmq(command):
    try:
        sock = zmq_context.socket(zmq.REQ)
        sock.setsockopt(zmq.LINGER, 0)
        sock.setsockopt(zmq.RCVTIMEO, 1000)
        sock.setsockopt(zmq.SNDTIMEO, 1000)
        sock.connect(f"tcp://127.0.0.1:{ZMQ_PORT}")
        sock.send_string(command)
        reply = sock.recv_string()
        sock.close()
        return True
    except:
        return False

def apply_overlay(config):
    text      = config.get("text", "")
    visible   = config.get("visible", False)
    color     = config.get("color", "white")
    font_size = config.get("font_size", 48)
    pos_y     = config.get("position_y", 90)
    style     = config.get("style", "scroll")
    bg        = config.get("bg", True)

    if not visible or not text.strip():
        send_zmq("Parsed_drawtext_0 reinit text= :fontcolor=black@0")
        return

    safe = text.replace("'","").replace("\\","").replace(":","　").replace("\n"," ")
    x    = "W-mod(t*150\\,W+tw)" if style == "scroll" else "(W-tw)/2"
    y    = f"h*{pos_y}/100-th/2"
    bg_s = ":box=1:boxcolor=black@0.5:boxborderw=12" if bg else ""

    cmd = f"Parsed_drawtext_0 reinit text='{safe}':fontsize={font_size}:fontcolor={color}:x={x}:y={y}{bg_s}"
    ok = send_zmq(cmd)
    print(f"ZMQ {'✅' if ok else '❌'} → {safe[:30]}")

# ── قراءة Gist كل ثانية ──
last_etag   = ""
last_config = {}

def poll_gist():
    global last_etag, last_config, overlay_config
    while True:
        try:
            req = urllib.request.Request(
                f"https://api.github.com/gists/{GIST_ID}",
                headers={
                    "Authorization": f"token {GH_TOKEN}",
                    "If-None-Match": last_etag,
                    "User-Agent": "stream-bot"
                }
            )
            with urllib.request.urlopen(req, timeout=5) as r:
                last_etag = r.headers.get("ETag", "")
                data      = json.loads(r.read())
                content   = data["files"]["overlay.json"]["content"]
                config    = json.loads(content)

                if config != last_config:
                    last_config    = config
                    overlay_config = config
                    apply_overlay(config)
                    print(f"📡 Overlay updated: {config.get('text','')[:30]}")

        except urllib.error.HTTPError as e:
            if e.code != 304:  # 304 = لا يوجد تغيير
                print(f"⚠️ Gist error: {e.code}")
        except Exception as e:
            print(f"⚠️ Poll error: {e}")

        time.sleep(1)

# ── FFmpeg ──
def build_cmd():
    fc = (
        "[0:v]fps=30,scale=1280:-2,"
        "drawtext=text=' ':fontsize=48:fontcolor=white@0:x=10:y=10"
        "[txt];[txt]zmq[out]"
    )
    return [
        'ffmpeg',
        '-loglevel', 'warning',
        '-err_detect', 'ignore_err',
        '-fflags', '+genpts+discardcorrupt',
        '-re',
        '-reconnect', '1', '-reconnect_at_eof', '1',
        '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
        '-timeout', '10000000',
        '-i', INPUT_URL,
        '-filter_complex', fc,
        '-map', '[out]', '-map', '0:a',
        '-vcodec', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
        '-b:v', '2500k', '-maxrate', '2500k', '-bufsize', '5000k',
        '-pix_fmt', 'yuv420p', '-g', '60', '-keyint_min', '60', '-sc_threshold', '0',
        '-acodec', 'aac', '-b:a', '96k', '-ar', '44100', '-ac', '2',
        '-af', 'aresample=async=1000',
        '-f', 'flv', '-flvflags', 'no_duration_filesize',
        OUTPUT_URL
    ]

def start_stream():
    if not INPUT_URL or not OUTPUT_URL:
        print("❌ INPUT_URL أو OUTPUT_URL غير موجود!")
        return
    retries = 0
    while True:
        try:
            print(f"🚀 Starting stream... (attempt {retries + 1})")
            p = subprocess.Popen(build_cmd(), stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, universal_newlines=True)

            def reapply():
                time.sleep(5)
                apply_overlay(overlay_config)
            threading.Thread(target=reapply, daemon=True).start()

            for line in p.stdout:
                line = line.strip()
                if line and any(x in line for x in ['Error','error','fail','Invalid']):
                    print(f"⚠️ {line}")
            p.wait()
        except Exception as e:
            print(f"❌ {e}")
        finally:
            retries += 1
            print("🔄 Reconnecting in 3s...")
            time.sleep(3)

if __name__ == "__main__":
    threading.Thread(target=poll_gist,   daemon=True).start()
    start_stream()
