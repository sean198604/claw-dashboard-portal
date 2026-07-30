import os
import json
import time
import sqlite3
import threading
import psutil
import datetime
from flask import Flask, jsonify, send_from_directory, request, abort

app = Flask(__name__, static_folder='static')

@app.route('/health')
def health():
    return 'OK', 200

CONFIG_FILE   = '/app/data/config.json'
COUNTER_FILE  = '/app/data/visit_count.json'
ICONS_DIR     = '/app/data/icons'
CLICK_FILE    = '/app/data/clicks.json'
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '1234')

# 确保数据目录存在
os.makedirs('/app/data', exist_ok=True)
os.makedirs(ICONS_DIR,   exist_ok=True)

# 默认配置
DEFAULT_CONFIG = {
    "groups": [
        {"id": "ai_apps", "name": "AI应用"},
        {"id": "tools", "name": "小工具"},
        {"id": "ai", "name": "企业知识库"},
        {"id": "culture", "name": "企业文化"}
    ],
    "cards": [
        {"id": "chatgpt", "type": "custom", "icon": "🤖", "title": "ChatGPT", "desc": "全能型战士，擅长搜索，写文案", "url": "https://chatgpt.com", "group": "ai_apps"},
        {"id": "gemini", "type": "custom", "icon": "✨", "title": "Gemini", "desc": "Google AI 助手，做图友好", "url": "https://gemini.google.com", "group": "ai_apps"},
        {"id": "perplexity", "type": "custom", "icon": "🔍", "title": "Perplexity 调研", "desc": "做客户调研，竞品分析找我", "url": "https://www.perplexity.ai/", "group": "ai_apps"},
        {"id": "prompt-hub", "type": "custom", "icon": "💡", "title": "提示词库", "desc": "AI 提示词集合，支持分类浏览、搜索和快速复制。", "url": "http://192.168.1.246:7000", "group": "ai_apps"},
        {"id": "excel-slim", "type": "custom", "icon": "⚡", "iconBg": "grad-3", "title": "Office文档瘦身", "desc": "各类office文档大小压缩", "url": "http://192.168.1.246:7001", "group": "tools"},
        {"id": "calc", "type": "custom", "icon": "💰", "title": "利润计算器", "desc": "快速计算外贸订单成本与利润空间", "url": "http://192.168.1.246:7003", "group": "tools"},
        {"id": "container_calc", "type": "custom", "icon": "📦", "title": "智能装柜计算器", "desc": "外贸智能装柜计算器，输入产品尺寸自动计算最优装柜方案", "url": "http://192.168.1.246:7002", "group": "tools"},
        {"id": "usd", "type": "usd", "icon": "💱", "title": "USD 汇率看板", "desc": "实时汇率监控，自动抓取中行数据，展示历史走势图。", "url": "http://192.168.1.246:5050", "group": "tools"},
        {"id": "card", "type": "card", "icon": "📇", "title": "名片识别", "desc": "名片识别与客户调研，智能OCR + AI自动背景调研。", "url": "http://192.168.1.246:8000", "group": "tools"},
        {"id": "customer-research", "type": "custom", "icon": "🔎", "title": "客户背景调研工具", "desc": "调研提示词生成工具", "url": "http://192.168.1.246:7004/", "group": "tools"},
        {"id": "market-research", "type": "custom", "icon": "📊", "title": "产品市场调研", "desc": "产品市场调研工具", "url": "http://192.168.1.246:7005", "group": "tools"},
        {"id": "hr-chat", "type": "custom", "icon": "👥", "title": "人力资源自动问答", "desc": "人力资源智能助理，快速解答HR相关问题。", "url": "http://192.168.1.246:3000/chat/share?shareId=cf0b6DJhUN7FZ4RXpcvCiXQp", "group": "ai"},
        {"id": "fastgpt", "type": "fastgpt", "icon": "🤖", "title": "业务系统自动问答", "desc": "基于大语言模型的知识库问答系统，支持自定义知识库和对话流程。", "url": "http://192.168.1.246:3000/chat/share?shareId=bU7oyxuXwOZvPSIGIo5lZa8j", "group": "ai"},
        {"id": "admin_bot", "type": "custom", "icon": "📋", "title": "行政问题自动问答", "desc": "行政事务智能助理，快速解答公司行政相关问题。", "url": "http://192.168.1.246:3000/chat/share?shareId=euPRu71Dd2vEdcxgkfxMcLCn", "group": "ai"},
        {"id": "culture-score", "type": "custom", "icon": "🏆", "title": "EGO文化积分", "desc": "查看个人和部门文化积分", "url": "http://192.168.1.246:7006/", "group": "culture"},
        {"id": "zh-culture", "type": "custom", "icon": "📖", "title": "《众瀚四季》", "desc": "众瀚企业文化期刊，了解公司动态与文化。", "url": "http://192.168.1.246:7007/", "group": "culture"},
    ]
}

# 确保数据中的卡片都有 hidden 字段
def normalize_config(cfg):
    if 'cards' in cfg:
        for card in cfg['cards']:
            if 'hidden' not in card:
                card['hidden'] = False
    return cfg

# 配置读写 ──────────────────────────────────────────
def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return normalize_config(json.load(f))
    except Exception:
        pass
    return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg):
    # 保存前确保 hidden 字段存在
    cfg = normalize_config(cfg)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

# ── 访问计数读写 ──────────────────────────────────────
def load_counter():
    try:
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_counter(data):
    with open(COUNTER_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False)

def get_today_key():
    return datetime.datetime.now().strftime('%Y-%m-%d')

def increment_visit():
    data = load_counter()
    today = get_today_key()
    data[today] = data.get(today, 0) + 1
    # 只保留最近 30 天
    keys = sorted(data.keys())
    if len(keys) > 30:
        for k in keys[:-30]:
            del data[k]
    save_counter(data)
    return data[today]

def get_today_visits():
    data = load_counter()
    return data.get(get_today_key(), 0)

# ── 页面路由 ──────────────────────────────────────────
@app.route('/')
def index():
    increment_visit()
    return send_from_directory('/app', 'index.html')

@app.route('/admin')
def admin():
    return send_from_directory('/app', 'admin.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('/app/static', filename)

@app.route('/data/icons/<path:filename>')
def icon_files(filename):
    return send_from_directory(ICONS_DIR, filename)

# ── 配置 API ──────────────────────────────────────────
@app.route('/api/config', methods=['GET'])
def get_config():
    return jsonify(load_config())

@app.route('/api/config', methods=['POST'])
def set_config():
    data = request.get_json(silent=True)
    if not data:
        abort(400)
    if data.get('password', '') != ADMIN_PASSWORD:
        return jsonify({'error': 'unauthorized'}), 401
    cfg = data.get('config')
    if not cfg:
        abort(400)
    save_config(cfg)
    return jsonify({'ok': True})

@app.route('/api/verify', methods=['POST'])
def verify():
    data = request.get_json(silent=True) or {}
    if data.get('password') == ADMIN_PASSWORD:
        return jsonify({'ok': True})
    return jsonify({'error': 'wrong password'}), 401

# ── 图标上传 API ──────────────────────────────────────
@app.route('/api/upload_icon', methods=['POST'])
def upload_icon():
    # 验证密码
    password = request.form.get('password', '')
    if password != ADMIN_PASSWORD:
        return jsonify({'error': 'unauthorized'}), 401

    card_id = request.form.get('card_id', '').strip()
    if not card_id:
        return jsonify({'error': 'card_id required'}), 400

    if 'file' not in request.files:
        return jsonify({'error': 'no file'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'empty filename'}), 400

    # 只允许图片格式
    allowed = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'}
    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed:
        return jsonify({'error': 'invalid file type'}), 400

    # 限制 2MB
    f.seek(0, 2)
    size = f.tell()
    f.seek(0)
    if size > 2 * 1024 * 1024:
        return jsonify({'error': 'file too large (max 2MB)'}), 400

    # 保存，文件名固定为 card_id.ext，覆盖旧文件
    filename = f'{card_id}.{ext}'
    save_path = os.path.join(ICONS_DIR, filename)
    # 删除旧图标（可能是不同扩展名）
    for old in os.listdir(ICONS_DIR):
        if old.rsplit('.', 1)[0] == card_id:
            os.remove(os.path.join(ICONS_DIR, old))
    f.save(save_path)

    icon_url = f'/data/icons/{filename}'
    return jsonify({'ok': True, 'icon_url': icon_url})

# ── 访问统计 API ──────────────────────────────────────
@app.route('/api/visits')
def visits():
    return jsonify({'today': get_today_visits()})

# ── 点击记录 ──────────────────────────────────────────
def load_clicks():
    try:
        if os.path.exists(CLICK_FILE):
            with open(CLICK_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_clicks(data):
    with open(CLICK_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@app.route('/api/click', methods=['POST'])
def record_click():
    data_req = request.get_json(silent=True) or {}
    card_id = data_req.get('card_id', '')
    if not card_id:
        return jsonify({'error': 'card_id required'}), 400

    # 优先使用客户端上报的IP（WebRTC获取，最准确）
    client_ip = data_req.get('client_ip', '')
    
    # 其次尝试从请求头获取
    ip = request.headers.get('X-Forwarded-For', '')
    if ip:
        ip = ip.split(',')[0].strip()
    if not ip:
        ip = request.headers.get('X-Real-IP', '')
    if not ip:
        ip = request.remote_addr or 'unknown'
    
    # 如果客户端上报了IP，使用它（更准确）
    if client_ip and not client_ip.startswith(('0.', '127.', '255.')):
        ip = client_ip

    now = datetime.datetime.now()
    date_key = now.strftime('%Y-%m-%d')
    time_key = now.strftime('%H:%M:%S')

    clicks = load_clicks()

    # 数据结构: { date: { ip: { card_id: { count, note, first_time, last_time } } } }
    if date_key not in clicks:
        clicks[date_key] = {}
    if ip not in clicks[date_key]:
        clicks[date_key][ip] = {}
    if card_id not in clicks[date_key][ip]:
        clicks[date_key][ip][card_id] = {'count': 0, 'note': '', 'first': time_key, 'last': time_key}

    clicks[date_key][ip][card_id]['count'] += 1
    clicks[date_key][ip][card_id]['last'] = time_key

    # 只保留最近 30 天
    keys = sorted(clicks.keys())
    if len(keys) > 30:
        for k in keys[:-30]:
            del clicks[k]

    save_clicks(clicks)
    return jsonify({'ok': True})

@app.route('/api/clicks', methods=['GET'])
def get_clicks():
    password = request.args.get('password', '')
    if password != ADMIN_PASSWORD:
        return jsonify({'error': 'unauthorized'}), 401
    clicks = load_clicks()
    return jsonify(clicks)

@app.route('/api/ip_note', methods=['POST'])
def update_ip_note():
    data_req = request.get_json(silent=True) or {}
    if data_req.get('password', '') != ADMIN_PASSWORD:
        return jsonify({'error': 'unauthorized'}), 401
    date_key = data_req.get('date', '')
    ip = data_req.get('ip', '')
    note = data_req.get('note', '')
    card_id = data_req.get('card_id', '')

    if not date_key or not ip or not card_id:
        return jsonify({'error': 'missing fields'}), 400

    clicks = load_clicks()
    if date_key in clicks and ip in clicks[date_key] and card_id in clicks[date_key][ip]:
        clicks[date_key][ip][card_id]['note'] = note
        save_clicks(clicks)
        return jsonify({'ok': True})
    return jsonify({'error': 'record not found'}), 404

# ── 系统状态 API ──────────────────────────────────────
@app.route('/api/sysinfo')
def sysinfo():
    cpu_percent = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    mem_total_gb = round(mem.total / 1024**3, 1)
    mem_used_gb  = round(mem.used  / 1024**3, 1)
    mem_percent  = mem.percent

    boot_ts = psutil.boot_time()
    boot_dt = datetime.datetime.fromtimestamp(boot_ts)
    now     = datetime.datetime.now()
    uptime_secs = int((now - boot_dt).total_seconds())
    days,  rem  = divmod(uptime_secs, 86400)
    hours, rem  = divmod(rem, 3600)
    mins        = rem // 60
    uptime_str  = f"{days}天{hours}小时{mins}分" if days > 0 else f"{hours}小时{mins}分"
    boot_str    = boot_dt.strftime('%Y-%m-%d %H:%M')

    return jsonify({
        'cpu_percent':  cpu_percent,
        'mem_percent':  mem_percent,
        'mem_used_gb':  mem_used_gb,
        'mem_total_gb': mem_total_gb,
        'uptime':       uptime_str,
        'boot_time':    boot_str,
        'today_visits': get_today_visits(),
    })

# ── 汇率代理 API（解决跨域 + 转换汇率） ─────────────────────
import urllib.request
@app.route('/api/exchange-rate')
def exchange_rate():
    try:
        # 从 usd-cny-app 获取汇率（容器内网）
        req = urllib.request.urlopen('http://host.docker.internal:5050/api/rates?days=1', timeout=5)
        data = json.loads(req.read().decode())
        if data and len(data) > 0:
            latest = data[-1]
            # rate 直接返回
            rate = float(latest['rate'])
            return jsonify({
                'rate': round(rate, 4),
                'date': latest.get('date', ''),
                'time': latest.get('pub_time', '')
            })
        return jsonify({'error': 'no data'})
    except Exception as e:
        return jsonify({'error': str(e)})

# ═══════════════════════════════════════════════════════════
#  IP 流量追踪 — SQLite 存储 + API
# ═══════════════════════════════════════════════════════════

TRAFFIC_DB = '/app/data/ip_traffic.db'
_traffic_db_lock = threading.Lock()  # 线程安全锁

def init_traffic_db():
    """初始化流量数据库表结构"""
    os.makedirs('/app/data', exist_ok=True)
    with sqlite3.connect(TRAFFIC_DB) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS traffic_logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                time       TEXT    NOT NULL,
                client_ip  TEXT    NOT NULL,
                target_port TEXT   NOT NULL
            )
        ''')
        # 索引加速常用查询
        conn.execute('CREATE INDEX IF NOT EXISTS idx_traffic_ip   ON traffic_logs(client_ip)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_traffic_port ON traffic_logs(target_port)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_traffic_time ON traffic_logs(time)')
        # IP 备注表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS traffic_notes (
                client_ip  TEXT PRIMARY KEY,
                note       TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now','localtime'))
            )
        ''')
        conn.commit()

# 启动时初始化
init_traffic_db()

def insert_traffic_log(time_str, client_ip, target_port):
    """插入一条访问记录（线程安全）"""
    with _traffic_db_lock:
        try:
            with sqlite3.connect(TRAFFIC_DB) as conn:
                conn.execute(
                    'INSERT INTO traffic_logs (time, client_ip, target_port) VALUES (?, ?, ?)',
                    (time_str, client_ip, target_port)
                )
                conn.commit()
            return True
        except Exception as e:
            print(f"[traffic] 写入失败: {e}", flush=True)
            return False

def query_traffic(sql, params=()):
    """通用查询（带锁）"""
    with _traffic_db_lock:
        with sqlite3.connect(TRAFFIC_DB) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

# ── 接收 WSL2 脚本推送的 IP 数据 ──
@app.route('/api/receive-ip', methods=['POST'])
def receive_ip():
    """
    接收 docker-ip-sender.sh 推送的访问数据
    JSON: {"time": "2026-05-25 19:30:00", "client_ip": "192.168.1.142", "target_port": "8001"}
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'invalid json'}), 400

    time_str   = data.get('time', '')
    client_ip  = data.get('client_ip', '')
    target_port = data.get('target_port', '')

    if not time_str or not client_ip or not target_port:
        return jsonify({'error': 'missing required fields (time, client_ip, target_port)'}), 400

    # 基本校验
    if not client_ip.replace('.', '').isdigit():
        return jsonify({'error': 'invalid client_ip'}), 400

    # 排除服务器自身 IP（避免记录自己的监控请求）
    if client_ip == '192.168.1.246':
        return jsonify({'ok': True, 'skipped': 'self'})

    if not insert_traffic_log(time_str, client_ip, target_port):
        return jsonify({'error': 'db write failed'}), 500

    return jsonify({'ok': True})

# ── 清除流量数据（管理用） ──
@app.route('/api/traffic/clear', methods=['POST'])
def clear_traffic():
    data = request.get_json(silent=True) or {}
    if data.get('password', '') != ADMIN_PASSWORD:
        return jsonify({'error': 'unauthorized'}), 401
    with _traffic_db_lock:
        with sqlite3.connect(TRAFFIC_DB) as conn:
            conn.execute('DELETE FROM traffic_logs')
            conn.commit()
    return jsonify({'ok': True})

# ── Top 20 活跃 IP（24小时内，排除服务器自身） ──
@app.route('/api/traffic/top-ips')
def traffic_top_ips():
    """返回 24 小时内访问次数最多的 Top 20 IP（排除 192.168.1.246）"""
    rows = query_traffic('''
        SELECT client_ip, COUNT(*) AS count
        FROM traffic_logs
        WHERE time >= datetime('now', '-1 day', 'localtime')
          AND client_ip != '192.168.1.246'
        GROUP BY client_ip
        ORDER BY count DESC
        LIMIT 20
    ''')
    return jsonify(rows)

# ── 各端口访问分布（排除服务器自身） ──
@app.route('/api/traffic/port-stats')
def traffic_port_stats():
    """返回各端口的访问次数分布（24小时内，排除 192.168.1.246）"""
    rows = query_traffic('''
        SELECT target_port, COUNT(*) AS count
        FROM traffic_logs
        WHERE time >= datetime('now', '-1 day', 'localtime')
          AND client_ip != '192.168.1.246'
        GROUP BY target_port
        ORDER BY count DESC
    ''')
    return jsonify(rows)

# ── 最近访问记录 ──
@app.route('/api/traffic/recent')
def traffic_recent():
    """返回最近 50 条访问记录"""
    limit = request.args.get('limit', 50, type=int)
    if limit > 200:
        limit = 200
    rows = query_traffic('''
        SELECT time, client_ip, target_port
        FROM traffic_logs
        ORDER BY id DESC
        LIMIT ?
    ''', (limit,))
    return jsonify(rows)

# ── 汇总统计（排除服务器自身） ──
@app.route('/api/traffic/summary')
def traffic_summary():
    """返回今日与历史汇总数据（排除 192.168.1.246）"""
    today_total = query_traffic('''
        SELECT COUNT(*) AS cnt FROM traffic_logs
        WHERE time >= datetime('now', 'start of day', 'localtime')
          AND client_ip != '192.168.1.246'
    ''')
    total = query_traffic("SELECT COUNT(*) AS cnt FROM traffic_logs WHERE client_ip != '192.168.1.246'")
    unique_ips = query_traffic('''
        SELECT COUNT(DISTINCT client_ip) AS cnt FROM traffic_logs
        WHERE time >= datetime('now', '-1 day', 'localtime')
          AND client_ip != '192.168.1.246'
    ''')
    return jsonify({
        'today_visits': today_total[0]['cnt'] if today_total else 0,
        'total_records': total[0]['cnt'] if total else 0,
        'unique_ips_24h': unique_ips[0]['cnt'] if unique_ips else 0,
    })

# ── 分时访问量统计（24小时，排除服务器自身） ──
@app.route('/api/traffic/hourly-stats')
def traffic_hourly_stats():
    """返回最近 24 小时按小时分组的访问量（排除 192.168.1.246）"""
    rows = query_traffic('''
        SELECT substr(time, 1, 13) AS hour, COUNT(*) AS count
        FROM traffic_logs
        WHERE time >= datetime('now', '-1 day', 'localtime')
          AND client_ip != '192.168.1.246'
        GROUP BY hour
        ORDER BY hour
    ''')
    return jsonify(rows)

# ── IP 聚合摘要（24h，按 IP 分组，含备注） ──
@app.route('/api/traffic/ip-summary')
def traffic_ip_summary():
    """返回每个 IP 的最新访问时间、端口、24h 总次数、访问端口列表及备注"""
    rows = query_traffic('''
        SELECT t.client_ip,
               MAX(t.time) AS last_time,
               COUNT(*) AS total_count,
               GROUP_CONCAT(DISTINCT t.target_port) AS ports_visited
        FROM traffic_logs t
        WHERE t.time >= datetime('now', '-1 day', 'localtime')
          AND t.client_ip != '192.168.1.246'
        GROUP BY t.client_ip
        ORDER BY last_time DESC
    ''')
    # 为每个 IP 补充 last_port 和 note
    result = []
    for row in rows:
        ip = row['client_ip']
        # 获取最近一次访问的端口
        last = query_traffic(
            'SELECT target_port FROM traffic_logs WHERE client_ip = ? ORDER BY id DESC LIMIT 1',
            (ip,)
        )
        last_port = last[0]['target_port'] if last else ''
        # 获取备注
        note_row = query_traffic(
            'SELECT note FROM traffic_notes WHERE client_ip = ?', (ip,)
        )
        note = note_row[0]['note'] if note_row else ''
        result.append({
            'client_ip': ip,
            'last_time': row['last_time'],
            'last_port': last_port,
            'total_count': row['total_count'],
            'ports_visited': row['ports_visited'].split(',') if row['ports_visited'] else [],
            'note': note
        })
    return jsonify(result)

# ── 单个 IP 的详细访问记录 ──
@app.route('/api/traffic/ip-detail')
def traffic_ip_detail():
    """返回指定 IP 的详细访问记录（最近 200 条）"""
    ip = request.args.get('ip', '')
    if not ip:
        return jsonify({'error': 'missing ip parameter'}), 400
    rows = query_traffic('''
        SELECT time, target_port
        FROM traffic_logs
        WHERE client_ip = ?
        ORDER BY id DESC
        LIMIT 200
    ''', (ip,))
    return jsonify(rows)

# ── IP 备注读写 ──
@app.route('/api/traffic/ip-note', methods=['GET', 'POST'])
def traffic_ip_note():
    """GET: 读取指定 IP 备注; POST: 保存备注"""
    if request.method == 'GET':
        ip = request.args.get('ip', '')
        if not ip:
            return jsonify({'error': 'missing ip parameter'}), 400
        with _traffic_db_lock:
            with sqlite3.connect(TRAFFIC_DB) as conn:
                conn.row_factory = sqlite3.Row
                cur = conn.execute('SELECT note FROM traffic_notes WHERE client_ip = ?', (ip,))
                row = cur.fetchone()
                return jsonify({'note': row['note'] if row else ''})
    else:  # POST
        data = request.get_json(silent=True) or {}
        if data.get('password', '') != ADMIN_PASSWORD:
            return jsonify({'error': 'unauthorized'}), 401
        ip = data.get('ip', '')
        note = data.get('note', '')
        if not ip:
            return jsonify({'error': 'missing ip'}), 400
        with _traffic_db_lock:
            with sqlite3.connect(TRAFFIC_DB) as conn:
                conn.execute(
                    'INSERT OR REPLACE INTO traffic_notes (client_ip, note, updated_at) VALUES (?, ?, datetime(\'now\',\'localtime\'))',
                    (ip, note)
                )
                conn.commit()
        return jsonify({'ok': True})

# ── 导出原始日志 ──
@app.route('/api/traffic/export')
def traffic_export():
    """导出最近 10000 条记录为纯文本（排除服务器自身）"""
    rows = query_traffic('''
        SELECT time, client_ip, target_port
        FROM traffic_logs
        WHERE client_ip != '192.168.1.246'
        ORDER BY id DESC
        LIMIT 10000
    ''')
    lines = []
    for row in reversed(rows):
        lines.append(f"{row['time']}  {row['client_ip']}  ->  :{row['target_port']}")
    return '\n'.join(lines), 200, {'Content-Type': 'text/plain; charset=utf-8'}
@app.route('/traffic')
def traffic_page():
    return send_from_directory('/app', 'traffic.html')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888, debug=False)
