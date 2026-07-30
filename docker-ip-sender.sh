#!/bin/bash
#===============================================================================
#  docker-ip-sender.sh  —  WSL2 内网流量追踪 & 实时推送工具 v2.0
#===============================================================================
#
#  功  能：零侵入捕获局域网内真实客户端 IP 访问所有 Docker 业务端口的流量，
#          包含 8888 门户主页，异步推送到 8888 看板进行可视化展示。
#
#  原  理：iptables nat PREROUTING LOG → dmesg --follow → curl POST
#
#  环  境：Windows 11 + WSL2 (Ubuntu) + Docker Desktop
#
#  死循环防御（3 层防护）：
#    第 1 层 — 脚本 curl 带特殊 User-Agent "Internal-Tracker-Robot" 请求头
#    第 2 层 — dmesg 解析器过滤 SRC=127.0.0.1 的本地回环流量
#    第 3 层 — 过滤所有 Docker 网桥网段 (172.17-31.x.x) 的内部流量
#    结论：脚本自己的 POST 绝不会被当成"外部访问"，零死循环风险
#
# ════════════════════════════════════════════════════════════════════════
#  快速上手（请在 WSL2 Ubuntu 终端中执行）
# ════════════════════════════════════════════════════════════════════════
#
#  【第一步：前台试运行，观察彩显日志】
#    sudo bash /mnt/c/Users/Administrator/Documents/Github/claw-dashboard-portal/docker-ip-sender.sh
#    按 Ctrl+C 即可退出（自动清理 iptables 规则，零残留）
#
#  【第二步：确认一切正常后，丢入后台静默运行】
#    sudo nohup bash /mnt/c/Users/Administrator/Documents/Github/claw-dashboard-portal/docker-ip-sender.sh \
#      &>/var/log/docker-ip-sender.log &
#
#  【第三步：查看运行状态】
#    sudo tail -f /var/log/docker-ip-sender.log          # 实时日志
#    ps aux | grep docker-ip-sender | grep -v grep       # 进程检查
#
#  【第四步：安全停止（自动清理 iptables 规则）】
#    sudo kill $(cat /tmp/docker-ip-sender.pid)
#    # 或更暴力的方式：
#    sudo pkill -f docker-ip-sender.sh
#
#  ⚠ 注意：WSL2 重启后 iptables 规则会自动清空，脚本需重新启动。
#          可加入 ~/.bashrc 或 crontab @reboot 实现开机自启。
#
#===============================================================================

# ──────────────────────────────────────────────────────────────────────────────
# §0  自我环境修复（启动即执行，无任何依赖）
# ──────────────────────────────────────────────────────────────────────────────

# ---- 0.1  CRLF → LF 自动修复 ----
# Windows 记事本 / Git 可能把脚本存成 CRLF 换行，
# 导致 WSL2 中执行时出现 "/bin/bash^M: bad interpreter" 错误。
# 这里自动检测并修复自身，修复后会 exit 0，用户只需重新执行一次即可。
if grep -q $'\r' "$0" 2>/dev/null; then
    echo ">>> [自愈] 检测到 Windows 换行符 (\\r)，正在自动修复..."
    sed -i 's/\r$//' "$0"
    echo ">>> [自愈] 修复完成！请重新执行本脚本。"
    exit 0
fi

# ---- 0.2  放开 WSL2 内核日志访问权限 ----
# WSL2 默认 kernel.dmesg_restrict=1，非 root 无法读 dmesg。
# 即使以 root 运行，某些 WSL2 内核编译配置也可能限制 dmesg。
# 这里显式置 0 确保万无一失。
if sysctl -w kernel.dmesg_restrict=0 &>/dev/null; then
    echo ">>> [自愈] kernel.dmesg_restrict 已置为 0"
else
    # WSL2 中 sysctl 对某些内核参数可能是只读的，忽略错误
    echo ">>> [提示] kernel.dmesg_restrict 修改失败（以 root 运行 dmesg 不受影响）"
fi

# ---- 0.3  核心依赖检查 ----
MISSING=()
for cmd in docker curl iptables date grep sed awk sort uniq; do
    command -v "$cmd" &>/dev/null || MISSING+=("$cmd")
done
if [ ${#MISSING[@]} -gt 0 ]; then
    echo ">>> [致命] 缺少以下基础命令: ${MISSING[*]}"
    exit 1
fi

# ──────────────────────────────────────────────────────────────────────────────
# §1  配置区（按需修改）
# ──────────────────────────────────────────────────────────────────────────────

# -- 推送地址：8888 看板的接收端点 --
RECEIVER_URL="http://127.0.0.1:8888/api/receive-ip"

# -- 自定义 User-Agent（死循环防御第 1 层）--
#    脚本自身发出的所有 POST 请求都带这个标识
TRACKER_UA="Internal-Tracker-Robot/2.0"

# -- iptables LOG 标记前缀 --
#    最大 29 字符，我们控制在 13 字符（TRACK_IP_ + 5位端口 = 18字符） --
LOG_PREFIX="TRACK_IP_"

# -- 运行时文件 --
PID_FILE="/tmp/docker-ip-sender.pid"                       # 进程 PID，用于外部 kill
DEBOUNCE_DB="/tmp/docker-ip-sender.debounce"               # 去重时间戳库
LOG_FILE="/var/log/docker-ip-sender.log"                   # 脚本自身输出日志

# -- 去重窗口：同一 (IP, 端口) 组合在此秒数内只推送一次 --
DEBOUNCE_SECS=2

# -- 端口刷新间隔：定期重读 docker ps（应对容器启停变化），单位秒 --
RELOAD_INTERVAL=120

# -- curl 超时（秒），防止偶发网络卡顿导致僵尸 curl 进程堆积 --
CURL_TIMEOUT=3

# -- Docker 网桥网段（正则，这些 IP 的流量不记录） --
#    默认 docker0 网桥: 172.17.0.0/16
#    Docker Compose 自定义网络: 172.18.x.x ~ 172.31.x.x
#    WSL2 内部虚拟网卡可能也在 172.x.x.x 段
DOCKER_BRIDGE_REGEX='^(172\.(1[7-9]|2[0-9]|3[01]))\.'

# ──────────────────────────────────────────────────────────────────────────────
# §2  终端彩色输出
# ──────────────────────────────────────────────────────────────────────────────

if [ -t 1 ] && command -v tput &>/dev/null && [ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]; then
    _C=1  # 启用颜色
else
    _C=0  # 非终端输出（如重定向到文件），禁用颜色
fi

_c()  { [ "$_C" = 1 ] && echo -ne "\033[$1m"; }
_ok()    { echo -e "$(_c '32')  ✓  $(_c 0)$*"; }
_info()  { echo -e "$(_c '36')  ℹ  $(_c 0)$*"; }
_warn()  { echo -e "$(_c '33')  ⚠  $(_c 0)$*"; }
_error() { echo -e "$(_c '31')  ✗  $(_c 0)$*"; }
_arrow() { echo -e "$(_c '2')  │  $(_c 0)$*"; }
_trace() { echo -e "     $(_c '2')$*$(_c 0)"; }

ts_log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ──────────────────────────────────────────────────────────────────────────────
# §3  工具函数
# ──────────────────────────────────────────────────────────────────────────────

# ---- 打印横幅 ----
banner() {
    echo ""
    echo -e "$(_c '1')$(_c '35')"
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║   Docker IP Sender — 内网流量追踪 v2.0        ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo -e "$(_c 0)"
}

# ---- Docker 服务可用性检查 ----
check_docker() {
    if ! docker ps &>/dev/null; then
        _error "Docker 服务不可用，请检查 Docker Desktop 是否已启动。"
        _trace "如 Docker Desktop 正在运行，尝试在 PowerShell 中:"
        _trace "  wsl --shutdown"
        _trace "然后重新打开 WSL2 终端。"
        exit 1
    fi
}

# ---- 从 docker ps 提取宿主机映射端口 ----
# 输出: 每行一个端口号（去重、排序、包含 8888）
get_published_ports() {
    docker ps --format '{{.Ports}}' 2>/dev/null \
        | tr ',' '\n' \
        | sed -n 's/.*0\.0\.0\.0:\([0-9]*\)->.*/\1/p' \
        | sort -n \
        | uniq
}

# ---- 端口 → 项目名称（终端展示用） ----
port_label() {
    case "$1" in
        3000)  echo "FastGPT" ;;
        3005)  echo "FastGPT MCP Server" ;;
        4444)  echo "NewsNow" ;;
        5050)  echo "汇率看板" ;;
        7000)  echo "提示词库" ;;
        7001)  echo "文档瘦身工具" ;;
        7002)  echo "装箱计算器" ;;
        7003)  echo "利润计算器" ;;
        7004)  echo "客户调研" ;;
        7005)  echo "产品调研" ;;
        7006)  echo "文化积分系统-前端" ;;
        7007)  echo "众瀚四季-前端" ;;
        8000)  echo "CODX 名片识别" ;;
        8001)  echo "文化积分系统-后端" ;;
        8002)  echo "众瀚四季-后端" ;;
        8888)  echo "🌟 导航门户(含主页+登录)" ;;
        9000)  echo "FastGPT MinIO" ;;
        9001)  echo "FastGPT MinIO Console" ;;
        *)     echo "(未命名项目)" ;;
    esac
}

# ──────────────────────────────────────────────────────────────────────────────
# §4  核心：iptables 规则管理（幂等性 + 死循环防御内建）
# ──────────────────────────────────────────────────────────────────────────────

# ---- 4.1  幂等清理所有 TRACK_IP_ 规则 ----
cleanup_iptables() {
    _info "清理旧规则..."
    local deleted=0
    local rules

    # 获取 nat PREROUTING 链中所有带 LOG_PREFIX 的规则行号（倒序）
    rules=$(iptables -t nat -L PREROUTING -n --line-numbers 2>/dev/null \
        | grep "$LOG_PREFIX" \
        | awk '{print $1}' \
        | sort -rn)

    if [ -n "$rules" ]; then
        for num in $rules; do
            iptables -t nat -D PREROUTING "$num" 2>/dev/null && ((deleted++))
        done
    fi
    _ok "已清理 ${deleted} 条旧规则"
}

# ---- 4.2  注入监控规则 ----
install_iptables_rules() {
    local ports
    ports=$(get_published_ports)

    if [ -z "$ports" ]; then
        _warn "docker ps 未检测到任何映射端口，请确认有容器在运行。"
        return 1
    fi

    local port_count
    port_count=$(echo "$ports" | wc -l)

    echo ""
    echo -e "$(_c '1')$(_c '35')"
    echo "  ┌─────────────────────────────────────────────┐"
    printf "  │  正在为 %-2s 个端口注入 TRACK_IP_ 监控规则  │\n" "$port_count"
    echo "  └─────────────────────────────────────────────┘"
    echo -e "$(_c 0)"

    # 打印端口列表
    while IFS= read -r port; do
        printf "     %s►%s 端口 %s%-5s%s  →  %s\n" \
            "$(_c '32')" "$(_c 0)" "$(_c '36')" "$port" "$(_c 0)" "$(port_label "$port")"
    done <<< "$ports"
    echo ""

    # 先清理再注入（幂等性保证）
    cleanup_iptables

    local ok=0 fail=0
    while IFS= read -r port; do
        [ -z "$port" ] && continue
        local prefix="${LOG_PREFIX}${port}"

        # ── 死循环防御内建说明 ──
        # iptables LOG 规则工作在 OSI 第 3/4 层（网络/传输层），
        # 无法过滤 HTTP User-Agent（那是第 7 层的事）。
        # 死循环的真正防线在 §6 的 dmesg 解析器中（过滤 127.0.0.1）。
        # 这里每条规则都只记录最简信息（SRC+DPT），由解析器做智能过滤。
        if iptables -t nat -I PREROUTING 1 \
            -p tcp --dport "$port" \
            -j LOG \
            --log-prefix "${prefix} " \
            --log-level 6 \
            --log-ip-options 2>/dev/null; then
            ((ok++))
            _ok "端口 ${port} — 规则注入成功"
        else
            ((fail++))
            _error "端口 ${port} — 注入失败"
        fi
    done <<< "$ports"

    # 汇总
    echo ""
    if [ $fail -eq 0 ]; then
        echo -e "  $(_c '32')╔══════════════════════════════════════╗$(_c 0)"
        printf "  $(_c '32')║$(_c 0)  全部 %-2s 个端口注入成功！              $(_c '32')║$(_c 0)\n" "$ok"
        echo -e "  $(_c '32')╚══════════════════════════════════════╝$(_c 0)"
    else
        printf "  $(_c '33')⚠  成功 %s 个，失败 %s 个$(_c 0)\n" "$ok" "$fail"
    fi
    echo ""

    return 0
}

# ──────────────────────────────────────────────────────────────────────────────
# §5  异步非阻塞 HTTP POST 推送
# ──────────────────────────────────────────────────────────────────────────────

send_to_receiver() {
    local time_str="$1"
    local client_ip="$2"
    local target_port="$3"

    [ -z "$time_str" ] || [ -z "$client_ip" ] || [ -z "$target_port" ] && return

    # 构造 JSON（用 printf 避免手动转义）
    local json
    json=$(printf '{"time":"%s","client_ip":"%s","target_port":"%s"}' \
        "$time_str" "$client_ip" "$target_port")

    # ── 异步非阻塞发送（核心） ──
    # 整个 curl 丢到子 shell 后台 (&)，主循环完全不被阻塞。
    # --connect-timeout + --max-time 确保卡死时也能被内核回收。
    # -A "Internal-Tracker-Robot" 是死循环防御第 1 层标识。
    (
        curl -s -X POST "$RECEIVER_URL" \
            -H "Content-Type: application/json" \
            -A "$TRACKER_UA" \
            -d "$json" \
            --connect-timeout "$CURL_TIMEOUT" \
            --max-time "$CURL_TIMEOUT" \
            -o /dev/null -w "%{http_code}" \
            > /tmp/docker-ip-sender.last_http 2>/dev/null
    ) &
}

# ──────────────────────────────────────────────────────────────────────────────
# §6  核心：dmesg 实时监听 + 智能过滤（含死循环防御第 2/3 层）
# ──────────────────────────────────────────────────────────────────────────────

# ---- 去重检查 ----
is_duplicate() {
    local key="${1}:${2}"  # IP:PORT
    local now
    now=$(date +%s)

    if [ -f "$DEBOUNCE_DB" ]; then
        local last
        last=$(grep "^${key}=" "$DEBOUNCE_DB" 2>/dev/null | cut -d= -f2)
        if [ -n "$last" ] && [ $((now - last)) -lt $DEBOUNCE_SECS ]; then
            return 0  # 重复
        fi
    fi

    # 更新时间戳（自动清理 60 秒以前的记录）
    { awk -F= -v n="$now" '$2 >= n-60' "$DEBOUNCE_DB" 2>/dev/null; echo "${key}=${now}"; } \
        > "${DEBOUNCE_DB}.tmp" 2>/dev/null
    mv "${DEBOUNCE_DB}.tmp" "$DEBOUNCE_DB" 2>/dev/null
    return 1  # 非重复
}

# ---- 主监听循环 ----
monitor_dmesg() {
    echo ""
    echo -e "$(_c '1')$(_c '36')"
    echo "  ██████████████████████████████████████████"
    echo "  █  开始实时监听内核访问日志...           █"
    echo "  █  推送地址: $RECEIVER_URL"
    echo "  █  死循环防御: 3 层 (UA + 回环 + 网桥)  █"
    echo "  ██████████████████████████████████████████"
    echo -e "$(_c 0)"
    echo ""

    # dmesg --follow 实时跟踪内核日志
    # 注意: 必须以 root 运行（前面已校验过）
    dmesg --follow 2>/dev/null | while IFS= read -r line; do

        # 只处理带我们标记的日志行
        [[ "$line" != *"$LOG_PREFIX"* ]] && continue

        # ── 字段提取 ──
        local port
        port=$(echo "$line" | grep -oP '(?<=TRACK_IP_)\d+')

        local src_ip
        src_ip=$(echo "$line" | grep -oP 'SRC=\K[\d.]+')

        [ -z "$src_ip" ] || [ -z "$port" ] && continue

        # ═══════════════════════════════════════════════════════════
        #  死循环防御 — 第 2 层：过滤本地回环地址
        # ═══════════════════════════════════════════════════════════
        #
        # 当脚本自己的 curl POST 请求通过 127.0.0.1 访问 8888 端口时，
        # iptables PREROUTING 链中 SRC=127.0.0.1。
        # 这里直接丢弃所有 127.0.0.0/8 的流量。
        [[ "$src_ip" == 127.* ]] && continue

        # ═══════════════════════════════════════════════════════════
        #  死循环防御 — 第 3 层：过滤 Docker 网桥内部流量
        # ═══════════════════════════════════════════════════════════
        #
        # Docker 默认网桥 docker0: 172.17.0.0/16
        # Docker Compose 自定义网络: 172.18.0.0/16 ~ 172.31.0.0/16
        # WSL2 内部虚拟网卡 IP 也可能落在此范围。
        # 这些流量是容器间通信或 Docker 代理转发，不是真实客户端。
        [[ "$src_ip" =~ $DOCKER_BRIDGE_REGEX ]] && continue

        # ── 去重 ──
        is_duplicate "$src_ip" "$port" && continue

        # ── 时间戳 ──
        local now
        now=$(date '+%Y-%m-%d %H:%M:%S')

        # ── 控制台输出 ──
        echo -e "  $(_c '35')►$(_c 0) $(_c '2')${now}$(_c 0) │ $(_c '33')${src_ip}$(_c 0) → $(_c '36')端口 ${port}$(_c 0) │ $(port_label "$port")"

        # ── 异步推送（不阻塞主循环） ──
        send_to_receiver "$now" "$src_ip" "$port"

    done
}

# ──────────────────────────────────────────────────────────────────────────────
# §7  后台端口刷新 + 退出清理
# ──────────────────────────────────────────────────────────────────────────────

# ---- 定期刷新端口列表（应对容器启停变化） ----
reload_loop() {
    while true; do
        sleep "$RELOAD_INTERVAL"
        ts_log "定时刷新端口列表..."
        install_iptables_rules
    done
}

# ---- 优雅退出清理 ----
cleanup_all() {
    echo ""
    _info "收到退出信号，正在优雅清理..."
    cleanup_iptables
    rm -f "$PID_FILE" "$DEBOUNCE_DB"
    _ok "所有 iptables 规则已清空，临时文件已删除。脚本已安全退出。"
    echo ""
}

# 捕获所有退出/终止信号
trap cleanup_all SIGINT SIGTERM EXIT

# ──────────────────────────────────────────────────────────────────────────────
# §8  主入口
# ──────────────────────────────────────────────────────────────────────────────

main() {
    banner

    # ── 权限检查 ──
    if [ "$(id -u)" -ne 0 ]; then
        _error "需要 root 权限（iptables 和 dmesg 操作必需）。"
        _trace "请使用: sudo bash $0"
        exit 1
    fi

    # ── Docker 可用性 ──
    check_docker

    # ── 防重复运行 ──
    if [ -f "$PID_FILE" ]; then
        local old_pid
        old_pid=$(cat "$PID_FILE")
        if kill -0 "$old_pid" 2>/dev/null; then
            _error "脚本已在运行 (PID: $old_pid)。"
            _trace "如需重启请先: sudo kill $old_pid"
            exit 1
        fi
    fi
    echo $$ > "$PID_FILE"

    # ── 检查 8888 接收端连通性（非致命） ──
    _info "检查接收端连通性..."
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        --connect-timeout 3 -A "$TRACKER_UA" "$RECEIVER_URL" 2>/dev/null || echo "000")
    if [ "$http_code" = "200" ] || [ "$http_code" = "405" ]; then
        _ok "接收端 $RECEIVER_URL 可达 (HTTP $http_code)"
    else
        _warn "接收端暂时不可达 (HTTP $http_code)，将在后台持续重试..."
    fi

    # ── 注入 iptables 规则 ──
    install_iptables_rules

    # ── 启动后台端口刷新 ──
    reload_loop &
    RELOAD_PID=$!
    _info "后台端口刷新已启动 (PID: $RELOAD_PID, 每 ${RELOAD_INTERVAL}s 刷新)"

    # ── 进入主监听循环 ──
    monitor_dmesg

    # 正常情况下不会执行到这里（dmesg --follow 是持久阻塞的），
    # 但如果 dmesg 意外退出，也要做清理：
    kill $RELOAD_PID 2>/dev/null || true
    cleanup_all
}

main
