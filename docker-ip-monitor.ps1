<#
==============================================================================
 docker-ip-monitor.ps1 -- Windows Host Traffic Monitor v1.0
==============================================================================
 Principle: Use Get-NetTCPConnection at Windows level to capture real LAN client IPs
 Advantage: Bypasses WSL2/Docker NAT; Windows is the first hop

 Start:
   powershell -File docker-ip-monitor.ps1

 Stop:
   Get-Job -Name DockerIPMonitor | Stop-Job | Remove-Job

 View logs:
   Get-Job -Name DockerIPMonitor | Receive-Job -Keep
#>

param(
    [int]$PollInterval = 2,
    [string]$ReceiverUrl = "http://127.0.0.1:8888/api/receive-ip"
)

# Port -> Project name map (static whitelist — only these ports are monitored)
$PortLabels = @{
    3000 = "FastGPT"
    3005 = "FastGPT MCP"
    3306 = "Points MySQL"
    3308 = "Journal MySQL"
    5050 = "FX Dashboard"
    7000 = "Prompt Library"
    7001 = "Doc Slim"
    7002 = "Container Calc"
    7003 = "Profit Calc"
    7004 = "Customer Research"
    7005 = "Product Research"
    7006 = "Culture Points"
    7007 = "Zhonghan Seasons"
    8000 = "BizCard OCR"
    8001 = "Culture API"
    8002 = "Zhonghan API"
    8888 = "Portal Home"
}

function Test-RealClientIP {
    param([string]$IP)
    if ($IP -eq "127.0.0.1" -or $IP -eq "::1" -or $IP -like "127.*") { return $false }
    if ($IP -eq "192.168.1.246") { return $false }      # 排除服务器自身
    if ($IP -match '^172\.(1[7-9]|2[0-9]|3[01])\.') { return $false }
    if ($IP -match ':') { return $false }
    if ($IP -match '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)') { return $true }
    if ($IP -match '^\d+\.\d+\.\d+\.\d+$') { return $true }
    return $false
}

# Global state -- v1.1: time-window dedup (IP+port, not connection tuple)
$cooldown = @{}                         # key="$ip:$port" -> DateTime of last POST
$COOLDOWN_SECS = 30                     # same IP+port only recorded once per 30s
$postCount = 0

# Initial port scan — use static whitelist from $PortLabels keys
$ports = @($PortLabels.Keys) | Sort-Object
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "  Windows Host Traffic Monitor v1.1" -ForegroundColor Magenta
Write-Host "  Polling every ${PollInterval}s | POST to $ReceiverUrl" -ForegroundColor DarkGray
Write-Host "========================================" -ForegroundColor Magenta
Write-Host "Monitor ports: $($ports -join ', ')" -ForegroundColor Cyan

Write-Host "Monitoring started. Press Ctrl+C to stop." -ForegroundColor Green
Write-Host ""

while ($true) {
    try {
        if ($ports) {
            $conns = Get-NetTCPConnection -State Established,TimeWait,CloseWait -ErrorAction SilentlyContinue `
                | Where-Object { $_.LocalPort -in $ports }

            foreach ($c in $conns) {
                $rip = $c.RemoteAddress.ToString()
                $lport = [int]$c.LocalPort    # cast to [int] to fix hashtable key type mismatch

                if (-not (Test-RealClientIP $rip)) { continue }

                # Time-window dedup: same (IP, target_port) only once per COOLDOWN_SECS
                $key = "$rip`:$lport"
                $now = Get-Date
                if ($cooldown.ContainsKey($key)) {
                    if (($now - $cooldown[$key]).TotalSeconds -lt $COOLDOWN_SECS) { continue }
                }
                $cooldown[$key] = $now

                $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
                $label = if ($PortLabels.ContainsKey($lport)) { $PortLabels[$lport] } else { "Port$lport" }

                Write-Host "  OK  [$ts] $rip -> :$lport ($label)" -ForegroundColor Green

                # Async POST
                $json = (@{ time = $ts; client_ip = $rip; target_port = "$lport" } | ConvertTo-Json -Compress)
                $url = $ReceiverUrl
                Start-Job -Name "TP_$(Get-Random)" -ScriptBlock {
                    param($u, $j)
                    try {
                        $null = Invoke-RestMethod -Uri $u -Method Post -Body $j `
                            -ContentType "application/json" -UserAgent "Internal-Tracker-Robot/1.0" -TimeoutSec 3
                    } catch {}
                } -ArgumentList $url, $json | Out-Null
                $postCount++
            }
        }

        # Cleanup completed jobs every 50 posts
        if ($postCount % 50 -eq 0 -and $postCount -gt 0) {
            Get-Job -Name "TP_*" -State Completed 2>$null | Remove-Job -Force
        }

        # Periodic cooldown cache cleanup: remove entries older than 2x COOLDOWN_SECS
        if ($postCount % 50 -eq 0 -and $postCount -gt 0) {
            $cutoff = (Get-Date).AddSeconds(-2 * $COOLDOWN_SECS)
            $stale = @($cooldown.GetEnumerator() | Where-Object { $_.Value -lt $cutoff })
            foreach ($s in $stale) { $cooldown.Remove($s.Key) }
        }
    } catch {
        # silently continue
    }

    Start-Sleep -Seconds $PollInterval
}
