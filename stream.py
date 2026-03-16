import os, subprocess, time, threading, urllib.request, json

INPUT_URL  = os.environ.get("INPUT_URL",  "")
OUTPUT_URL = os.environ.get("OUTPUT_URL", "")
GIST_ID    = os.environ.get("GIST_ID",   "")
GH_TOKEN   = os.environ.get("GH_TOKEN",  "")

TEXT_FILE = "/tmp/overlay.txt"

overlay_config = {
    "text": "", "visible": False, "style": "scroll",
    "position_y": 90, "font_size": 48, "color": "white", "bg": True
}

# كتابة النص في الملف — ffmpeg يقرأه مباشرة
def write_text(config):
    text    = config.get("text", "")
    visible = config.get("visible", False)
    with open(TEXT_FILE, "w", encoding="utf-8") as f:
        f.write(text if (visible and text.strip()) else " ")

# تهيئة الملف
write_text(overlay_config)

# قراءة Gist كل ثانية
last_etag   = ""
last_config = {}

def poll_gist():
    global last_etag, last_config, overlay_config
    time.sleep(5)
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
                data   = json.loads(r.read())
                config = json.loads(data["files"]["overlay.json"]["content"])
                if config != last_config:
                    last_config    = config
                    overlay_config = config
                    write_text(config)
                    txt = config.get("text","")
                    vis = config.get("visible", False)
                    print(f"📡 {'✅ ' + txt[:30] if vis else '🔇 hidden'}")
        except urllib.error.HTTPError as e:
            if e.code != 304:
                print(f"⚠️ Gist {e.code}")
        except Exception as e:
            print(f"⚠️ {e}")
        time.sleep(1)

# بناء أمر ffmpeg
def build_cmd():
    cfg       = overlay_config
    pos_y     = cfg.get("position_y", 90)
    font_size = cfg.get("font_size", 48)
    color     = cfg.get("color", "white")
    style     = cfg.get("style", "scroll")
    bg        = cfg.get("bg", True)

    color_map = {
        "white":"white","yellow":"yellow","red":"red",
        "cyan":"cyan","lime":"lime","orange":"orange"
    }
    fc = color_map.get(color, "white")
    bg_str = ":box=1:boxcolor=black@0.5:boxborderw=12" if bg else ""

    if style == "scroll":
        x = "W-mod(t*150\\,W+tw)"
    else:
        x = "(W-tw)/2"

    y = f"h*{pos_y}/100-th/2"

    vf = (
        f"fps=30,scale=1280:-2,"
        f"drawtext="
        f"textfile={TEXT_FILE}:"
        f"fontsize={font_size}:"
        f"fontcolor={fc}:"
        f"x={x}:"
        f"y={y}:"
        f"reload=1"
        f"{bg_str}"
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
        '-vf', vf,
        '-map', '0:v', '-map', '0:a',
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
            p = subprocess.Popen(
                build_cmd(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
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
    threading.Thread(target=poll_gist, daemon=True).start()
    start_stream()
