#!/usr/bin/env python3
"""Собирает системную статистику и пишет HTML-фрагмент для QML-обоев Plasma.

Вывод — ~/.cache/conky-dash/dash.html, читается плагином обоев по таймеру.
Пишем через временный файл + os.replace, чтобы читатель никогда не увидел
наполовину записанный файл.
"""
import os, re, time, socket, subprocess, glob, html, json

# Кадр перезаписывается каждые 2 с. На диске это ~10 ГБ записи в сутки,
# поэтому пишем в tmpfs (оперативная память) — на SSD не попадает ничего.
_RUN = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
CACHE = os.path.join(_RUN, "conky-dash") if os.path.isdir(_RUN) \
        else os.path.expanduser("~/.cache/conky-dash")
OUT = os.path.join(CACHE, "dash.png")

C_LABEL = "#5fa85a"   # подписи полей
C_VALUE = "#a8e6a3"   # значения
C_HEAD  = "#ffffff"   # заголовки секций
C_ACCENT= "#ffd479"   # акценты

def read(p, default=""):
    try:
        with open(p) as f:
            return f.read().strip()
    except OSError:
        return default

def human(n, suffix="B"):
    n = float(n)
    for u in ("", "K", "M", "G", "T"):
        if abs(n) < 1024:
            return f"{n:.1f}{u}{suffix}" if u else f"{n:.0f}{suffix}"
        n /= 1024
    return f"{n:.1f}P{suffix}"

# ---------- система ----------
def uptime():
    s = float(read("/proc/uptime", "0").split()[0])
    d, r = divmod(int(s), 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return (f"{d}д " if d else "") + f"{h}ч {m}м"

# ---------- CPU ----------
_prev = {}
def cpu_percents():
    """Загрузка по ядрам между двумя вызовами."""
    out = {}
    for line in read("/proc/stat").splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        name = parts[0]
        vals = [int(x) for x in parts[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        total = sum(vals)
        p_total, p_idle = _prev.get(name, (0, 0))
        dt, di = total - p_total, idle - p_idle
        _prev[name] = (total, idle)
        out[name] = max(0.0, min(100.0, 100.0 * (dt - di) / dt)) if dt > 0 else 0.0
    return out

def cpu_freq_ghz():
    fs = glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")
    vals = [int(read(f, "0") or 0) for f in fs]
    vals = [v for v in vals if v]
    return sum(vals) / len(vals) / 1e6 if vals else 0.0

def hwmon_temp(name, idx=1):
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if read(os.path.join(h, "name")) == name:
            v = read(os.path.join(h, f"temp{idx}_input"))
            if v:
                return int(v) / 1000
    return None

# ---------- память ----------
def meminfo():
    d = {}
    for line in read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        d[k] = int(v.split()[0]) * 1024
    total = d.get("MemTotal", 0)
    avail = d.get("MemAvailable", 0)
    used = total - avail
    sw_t = d.get("SwapTotal", 0)
    sw_u = sw_t - d.get("SwapFree", 0)
    return used, total, sw_u, sw_t

# ---------- батарея ----------
def battery():
    base = "/sys/class/power_supply/BAT0"
    if not os.path.isdir(base):
        return None
    cap = read(os.path.join(base, "capacity"))
    status = read(os.path.join(base, "status"))
    ru = {"Discharging": "разряд", "Charging": "заряд",
          "Full": "заряжена", "Not charging": "не заряжается"}.get(status, status)
    return (int(cap) if cap else 0), ru

# ---------- сеть ----------
def default_routes():
    phys = gw = tun = None
    try:
        out = subprocess.run(["ip", "route", "show", "default"],
                             capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return None, None, None
    for line in out.splitlines():
        f = line.split()
        dev = f[f.index("dev") + 1] if "dev" in f else None
        if "via" in f and phys is None:
            phys, gw = dev, f[f.index("via") + 1]
        elif "via" not in f and tun is None:
            tun = dev
    return phys, gw, tun

def ipv4(dev):
    try:
        out = subprocess.run(["ip", "-4", "-br", "addr", "show", dev],
                             capture_output=True, text=True, timeout=3).stdout.split()
        return out[2] if len(out) > 2 else "—"
    except Exception:
        return "—"

def wifi(dev):
    if not os.path.isdir(f"/sys/class/net/{dev}/wireless"):
        return None
    ssid = sig = None
    try:
        out = subprocess.run(["iw", "dev", dev, "link"],
                             capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"SSID:\s*(.+)", out)
        ssid = m.group(1).strip() if m else None
    except Exception:
        pass
    for line in read("/proc/net/wireless").splitlines():
        if line.strip().startswith(dev + ":"):
            try:
                sig = int(float(line.split()[3]))
            except (IndexError, ValueError):
                pass
    return ssid or "—", sig

def vnstat_traffic(dev):
    """Накопленный трафик по vnstat: (сегодня, в этом месяце) в байтах.

    В отличие от rx/tx из /sys, который сбрасывается на каждой перезагрузке,
    vnstatd хранит историю на диске — это и есть настоящий "потраченный
    трафик". None — если интерфейс ещё не заведён в базе vnstat.
    """
    try:
        out = subprocess.run(["vnstat", "-i", dev, "--json"],
                             capture_output=True, text=True, timeout=3).stdout
        tr = json.loads(out)["interfaces"][0]["traffic"]
    except Exception:
        return None
    now = time.localtime()
    today_b = next((d["rx"] + d["tx"] for d in tr.get("day", [])
                    if (d["date"]["year"], d["date"]["month"], d["date"]["day"])
                    == (now.tm_year, now.tm_mon, now.tm_mday)), 0)
    month_b = next((m["rx"] + m["tx"] for m in tr.get("month", [])
                    if (m["date"]["year"], m["date"]["month"]) == (now.tm_year, now.tm_mon)), 0)
    return today_b, month_b

_prevnet = {}
def net_speed(dev, dt):
    rx = int(read(f"/sys/class/net/{dev}/statistics/rx_bytes", "0") or 0)
    tx = int(read(f"/sys/class/net/{dev}/statistics/tx_bytes", "0") or 0)
    prx, ptx = _prevnet.get(dev, (rx, tx))
    _prevnet[dev] = (rx, tx)
    if dt <= 0:
        return 0, 0
    return max(0, (rx - prx) / dt), max(0, (tx - ptx) / dt)

def connections():
    """Установленные TCP-соединения с именами процессов.

    ss -tnp без root показывает процессы только текущего пользователя —
    для чужих строк имя будет пустым. Это осознанное ограничение:
    полный обзор по всем процессам требует root.
    """
    try:
        out = subprocess.run(["ss", "-tnpH", "state", "established"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return [], 0
    total = 0
    ext = []
    for line in out.splitlines():
        f = line.split()
        if len(f) < 4:
            continue
        total += 1
        local, remote = f[2], f[3]
        rip, _, rport = remote.rpartition(":")
        rip = rip.strip("[]")
        if rip in ("127.0.0.1", "::1"):
            continue
        lport = local.rpartition(":")[2]
        m = re.search(r'users:\(\("([^"]+)"', line)
        proc = m.group(1) if m else ""
        ext.append((proc, lport, rip, rport))
    seen, uniq = set(), []
    for e in ext:
        if e not in seen:
            seen.add(e); uniq.append(e)
    return uniq, total

def routes():
    """Таблица маршрутов: (назначение, через, устройство, метрика)."""
    try:
        out = subprocess.run(["ip", "route", "show"],
                             capture_output=True, text=True, timeout=3).stdout
    except Exception:
        return []
    res = []
    for line in out.splitlines():
        f = line.split()
        if not f:
            continue
        dst = f[0]
        via = f[f.index("via") + 1] if "via" in f else ""
        dev = f[f.index("dev") + 1] if "dev" in f else ""
        met = f[f.index("metric") + 1] if "metric" in f else ""
        res.append((dst, via, dev, met))
    return res

def dns_servers():
    servers, search = [], ""
    try:
        with open("/etc/resolv.conf") as fh:
            for line in fh:
                if line.startswith("nameserver"):
                    servers.append(line.split()[1])
                elif line.startswith("search"):
                    search = " ".join(line.split()[1:])
    except OSError:
        pass
    return servers, search

def interfaces():
    """Все интерфейсы кроме lo: (имя, состояние, ip, принято, отдано)."""
    res = []
    for dev in sorted(os.listdir("/sys/class/net")):
        if dev == "lo":
            continue
        state = read(f"/sys/class/net/{dev}/operstate", "?")
        rx = int(read(f"/sys/class/net/{dev}/statistics/rx_bytes", "0") or 0)
        tx = int(read(f"/sys/class/net/{dev}/statistics/tx_bytes", "0") or 0)
        res.append((dev, state, ipv4(dev), rx, tx))
    return res

# ---------- топ процессов ----------
def top_procs(n=3):
    try:
        out = subprocess.run(["ps", "-eo", "comm,pcpu,pmem", "--sort=-pcpu"],
                             capture_output=True, text=True, timeout=4).stdout
    except Exception:
        return []
    rows = []
    for line in out.splitlines()[1:]:
        f = line.rsplit(None, 2)
        if len(f) == 3 and f[0] not in ("ps", "python3"):
            rows.append((f[0][:18], f[1], f[2]))
        if len(rows) >= n:
            break
    return rows

# ---------- отрисовка PNG ----------
from PIL import Image, ImageDraw, ImageFont

FONT_PATH = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"
FONT_BOLD = "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf"
FS = 25
FONT = ImageFont.truetype(FONT_PATH, FS)
FONTB = ImageFont.truetype(FONT_BOLD, FS)
CW = FONT.getlength("0")   # ширина моноширинного знака
LH = FS + 7
PAD = 20
GAP = 46                 # зазор между колонками
# Блок прижат к правому краю экрана, поэтому плавающая ширина картинки
# двигала бы его при каждом обновлении. Держим ширину постоянной.
FIXED_W = 1860
C_DIM = "#3a6b37"

def seg(text, color=C_VALUE, bold=False):
    return (str(text), color, bold)

class Bar:
    """Полоса-заполнение. Рисуется прямоугольниками: блочные символы
    \u2588/\u2591 дают видимые швы между глифами."""
    def __init__(self, pct, cells=22):
        self.pct = max(0.0, min(100.0, pct))
        self.cells = cells
    @property
    def w(self):
        return self.cells * CW

def bar(pct, width=22):
    return [Bar(pct, width)]

def hdr(L, title):
    if L:
        L.append([])
    L.append([seg(title, C_HEAD, True)])
    L.append([seg("\u2500" * 44, C_DIM)])

# ---------- левая колонка: система и ресурсы ----------
def col_system(dt, slow):
    L = []
    cpus = cpu_percents()
    used, total, sw_u, sw_t = meminfo()
    st = os.statvfs("/")
    d_total = st.f_blocks * st.f_frsize
    d_used = d_total - st.f_bavail * st.f_frsize

    hdr(L, "СИСТЕМА")
    L.append([seg("Хост      ", C_LABEL), seg(socket.gethostname())])
    L.append([seg("Ядро      ", C_LABEL), seg(os.uname().release)])
    L.append([seg("Аптайм    ", C_LABEL), seg(uptime())])
    L.append([seg("Время     ", C_LABEL), seg(time.strftime("%d.%m.%Y  %H:%M:%S"))])
    b = battery()
    if b:
        pct, status = b
        L.append([seg("Батарея   ", C_LABEL), seg(f"{pct:3d}%  ", C_ACCENT)]
                 + bar(pct, 16) + [seg("  " + status, C_LABEL)])

    hdr(L, "РЕСУРСЫ")
    agg = cpus.get("cpu", 0)
    t = hwmon_temp("coretemp") or 0
    L.append([seg("CPU       ", C_LABEL), seg(f"{agg:3.0f}%  ")] + bar(agg)
             + [seg(f"  {cpu_freq_ghz():.2f}ГГц {t:.0f}°C", C_LABEL)])
    cores = sorted(k for k in cpus if k != "cpu")
    row = []
    for i, c in enumerate(cores):
        row.append(seg(f"  {i+1}", C_LABEL))
        row.append(seg(f"{cpus[c]:3.0f}%"))
    if row:
        L.append(row)
    la = os.getloadavg()
    L.append([seg("Нагрузка  ", C_LABEL), seg(f"{la[0]:.2f}  {la[1]:.2f}  {la[2]:.2f}")])
    L.append([])
    L.append([seg("RAM       ", C_LABEL), seg(f"{human(used)} / {human(total)}".ljust(20))]
             + bar(100 * used / total if total else 0, 14))
    if sw_t:
        L.append([seg("Swap      ", C_LABEL), seg(f"{human(sw_u)} / {human(sw_t)}")])
    L.append([seg("Диск /    ", C_LABEL), seg(f"{human(d_used)} / {human(d_total)}".ljust(20))]
             + bar(100 * d_used / d_total if d_total else 0, 14))
    nvme = hwmon_temp("nvme")
    if nvme:
        L.append([seg("NVMe      ", C_LABEL), seg(f"{nvme:.0f}°C")])

    tp = slow["top"]
    if tp:
        L.append([])
        L.append([seg("Топ по CPU", C_LABEL)])
        for name, pc, pm in tp:
            L.append([seg("  " + name.ljust(18), C_LABEL), seg(f"{pc:>5}%"),
                      seg(f"  {pm:>5}%", C_LABEL)])
    return L

# ---------- правая колонка: сеть целиком ----------
def col_network(dt, slow):
    L = []
    hdr(L, "СЕТЬ")
    phys, gw, tun = slow["defroute"]
    if not phys and not tun:
        L.append([seg("нет сетевого подключения", "#ff6b6b")])
        return L

    rts = slow["routes"]
    # какой маршрут по умолчанию реально выигрывает — у кого метрика меньше
    defaults = [r for r in rts if r[0] == "default"]
    winner = min(defaults, key=lambda r: int(r[3]) if r[3] else 0) if defaults else None
    if winner:
        note = "туннель" if winner[2] != phys else "напрямую"
        L.append([seg("Трафик    ", C_LABEL), seg(winner[2].ljust(12), C_ACCENT),
                  seg(f"{note}, metric {winner[3] or '0'}", C_LABEL)])

    dev = phys or tun
    w = slow["wifi"]
    if w:
        ssid, sig = w
        L.append([seg("Аплинк    ", C_LABEL), seg(dev.ljust(12)),
                  seg(f"Wi-Fi {ssid}" + (f"  {sig}dBm" if sig is not None else ""), C_LABEL)])
    else:
        L.append([seg("Аплинк    ", C_LABEL), seg(dev)])
    L.append([seg("IP        ", C_LABEL), seg(slow["ip"].get(dev, "—").ljust(20)),
              seg("шлюз ", C_LABEL), seg(gw or "—")])
    srv, search = slow["dns"]
    if srv:
        L.append([seg("DNS       ", C_LABEL), seg(", ".join(srv[:2]).ljust(20)),
                  seg(f"домен {search}" if search else "", C_LABEL)])
    down, up = net_speed(dev, dt)
    L.append([seg("Скорость  ", C_LABEL), seg(f"\u2193 {human(down)}/с".ljust(16)),
              seg(f"\u2191 {human(up)}/с")])
    tf = slow.get("traffic")
    if tf:
        today_b, month_b = tf
        L.append([seg("Трафик    ", C_LABEL), seg(f"сегодня {human(today_b)}".ljust(18), C_ACCENT),
                  seg(f"за месяц {human(month_b)}", C_LABEL)])

    L.append([])
    L.append([seg("Маршруты", C_LABEL)])
    for dst, via, rdev, met in rts[:6]:
        target = via if via else rdev
        arrow = f"{dst} \u2192 {target}"
        tail = f"  ({rdev}, metric {met})" if via and met else (f"  metric {met}" if met else "")
        col = C_ACCENT if (dst == "default" and winner and rdev == winner[2]) else C_VALUE
        L.append([seg("  " + arrow.ljust(30), col), seg(tail, C_LABEL)])

    L.append([])
    L.append([seg("Интерфейсы", C_LABEL)])
    for name, state, ip, rx, tx in slow["ifaces"]:
        col = C_VALUE if state == "up" else (C_ACCENT if state == "unknown" else C_DIM)
        L.append([seg("  " + name.ljust(11), col), seg(state.ljust(9), C_LABEL),
                  seg(ip.ljust(20)),
                  seg(f"\u2193{human(rx)} \u2191{human(tx)}", C_LABEL)])

    ext, tot = slow["conns"]
    byproc = {}
    for proc, _, _, _ in ext:
        byproc[proc or "—"] = byproc.get(proc or "—", 0) + 1
    if byproc:
        L.append([])
        L.append([seg("Кто держит соединения", C_LABEL)])
        for name, cnt in sorted(byproc.items(), key=lambda kv: -kv[1])[:4]:
            label = name if name != "—" else "(чужой процесс)"
            L.append([seg("  " + label.ljust(22), C_LABEL), seg(f"{cnt:>4}")])

    L.append([])
    L.append([seg("Соединения  ", C_LABEL), seg(f"внешних {len(ext)}"),
              seg(f"   всего {tot}", C_LABEL)])
    # группируем по удалённому адресу: 20 строк с одним и тем же IP бесполезны
    byaddr = {}
    for proc, _, rip, rport in ext:
        key = f"{rip}:{rport}"
        cnt, procs = byaddr.get(key, (0, set()))
        if proc:
            procs.add(proc)
        byaddr[key] = (cnt + 1, procs)
    rows = sorted(byaddr.items(), key=lambda kv: -kv[1][0])
    for addr, (cnt, procs) in rows[:7]:
        who = ", ".join(sorted(procs))[:18] if procs else "—"
        L.append([seg("  " + addr.ljust(23)), seg(f"x{cnt:<4}", C_ACCENT if cnt > 1 else C_LABEL),
                  seg(who, C_LABEL)])
    if len(rows) > 7:
        L.append([seg(f"  … ещё {len(rows) - 7} адресов", C_LABEL)])
    return L

def item_width(it):
    return it.w if isinstance(it, Bar) else FONT.getlength(it[0])

def slow_data():
    """Данные, которые тянут внешние процессы (ss, ip, ps, iw).

    Они меняются медленно, а стоят дорого — поэтому обновляются раз в
    SLOW_EVERY тиков, а не каждый кадр. Часы, CPU, память и скорость сети
    при этом остаются полностью живыми.
    """
    phys, gw, tun = default_routes()
    dev = phys or tun
    ipmap = {}
    ifaces = []
    for name in sorted(os.listdir("/sys/class/net")):
        if name == "lo":
            continue
        ip = ipv4(name)
        ipmap[name] = ip
        ifaces.append((name, read(f"/sys/class/net/{name}/operstate", "?"), ip,
                       int(read(f"/sys/class/net/{name}/statistics/rx_bytes", "0") or 0),
                       int(read(f"/sys/class/net/{name}/statistics/tx_bytes", "0") or 0)))
    return {
        "defroute": (phys, gw, tun),
        "routes": routes(),
        "dns": dns_servers(),
        "ifaces": ifaces,
        "ip": ipmap,
        "wifi": wifi(dev) if dev else None,
        "conns": connections(),
        "top": top_procs(4),
        "traffic": vnstat_traffic(dev) if dev else None,
    }

def measure(lines):
    w = 0
    for ln in lines:
        w = max(w, sum(item_width(i) for i in ln))
    return w

def draw_col(d, lines, x0, y0):
    y = y0
    for ln in lines:
        x = x0
        for it in ln:
            if isinstance(it, Bar):
                h = FS - 8
                top = y + 6
                d.rounded_rectangle([x, top, x + it.w, top + h], radius=3,
                                    fill="#1d2b1f")
                fw = it.w * it.pct / 100.0
                if fw >= 2:
                    d.rounded_rectangle([x, top, x + fw, top + h], radius=3,
                                        fill=C_VALUE)
                x += it.w
            else:
                text, color, bold = it
                f = FONTB if bold else FONT
                d.text((x, y), text, font=f, fill=color)
                x += f.getlength(text)
        y += LH

def render(left, right):
    wl, wr = measure(left), measure(right)
    W = max(FIXED_W, int(wl + GAP + wr) + PAD * 2)
    H = max(len(left), len(right)) * LH + PAD * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=12, fill=(0, 0, 0, 120))
    draw_col(d, left, PAD, PAD)
    draw_col(d, right, PAD + wl + GAP, PAD)
    return img

SLOW_EVERY = 5          # медленные данные обновляем раз в 5 тиков = 10 с

def main():
    os.makedirs(CACHE, exist_ok=True)
    # Кадр пишется во временный файл и атомарно подменяет dash.png, поэтому
    # копий не возникает. Но если процесс убить ровно между save и replace,
    # огрызок .tmp.png останется — подчищаем его на старте.
    for stale in os.listdir(CACHE):
        if stale.endswith(".tmp.png"):
            try:
                os.remove(os.path.join(CACHE, stale))
            except OSError:
                pass
    cpu_percents()
    last = time.monotonic()
    for dev in os.listdir("/sys/class/net"):
        net_speed(dev, 0)
    time.sleep(1)
    slow = slow_data()
    tick = 0
    while True:
        now = time.monotonic()
        dt, last = now - last, now
        if tick % SLOW_EVERY == 0 and tick:
            try:
                slow = slow_data()
            except Exception:
                pass                        # оставляем прошлый снимок
        tick += 1
        try:
            img = render(col_system(dt, slow), col_network(dt, slow))
        except Exception as e:
            img = Image.new("RGBA", (900, 60), (0, 0, 0, 160))
            ImageDraw.Draw(img).text((12, 18), f"ошибка сбора данных: {e}",
                                     font=FONT, fill="#ff6b6b")
        tmp = OUT + ".tmp.png"
        img.save(tmp, compress_level=1)
        os.replace(tmp, OUT)
        time.sleep(2)

if __name__ == "__main__":
    main()
