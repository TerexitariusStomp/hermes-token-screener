#!/bin/bash
# ============================================================================
# SSH Self-Heal Diagnostics & Recovery Script
# Checks SSH daemon health, memory pressure, Tailscale, network stability
# Auto-fixes common issues before they cascade into disconnects
# ============================================================================
set -euo pipefail

RESULTS=()
FAILURES=0
CRITICAL=0

log() {
    echo "[$(date '+%H:%M:%S')] [SSH self-heal] $1"
}

alert() {
    local msg="SSH Self-Heal Alert: $1"
    echo "  >> ALERT: $msg"
    # Send Telegram notification if credentials exist
    if command -v python3 &>/dev/null; then
        python3 -c "
import os, urllib.request, urllib.parse
from dotenv import load_dotenv
from pathlib import Path
env_path = Path.home() / '.hermes' / '.env'
if env_path.exists():
    load_dotenv(env_path)
token = os.environ.get('TELEGRAM_BOT_TOKEN')
chat_id = os.environ.get('TELEGRAM_CHAT_ID')
if token and chat_id:
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    data = urllib.parse.urlencode({'chat_id': chat_id, 'text': '${msg}'}).encode()
    try:
        req = urllib.request.Request(url, data=data)
        urllib.request.urlopen(req, timeout=10)
    except: pass
" 2>/dev/null || true
    fi
}

# ================================================================
# CHECK 1: CRITICAL - Memory Health (prevent OOM cascades)
# ================================================================
MEM_AVAIL=$(cat /proc/meminfo | grep MemAvailable | awk '{print $2}')
MEM_TOTAL=$(cat /proc/meminfo | grep MemTotal | awk '{print $2}')
MEM_USED_PCT=$(( (MEM_TOTAL - MEM_AVAIL) * 100 / MEM_TOTAL ))

if [ "$MEM_USED_PCT" -ge 95 ]; then
    log "!! CRITICAL: Memory ${MEM_USED_PCT}% used - OOM cascade imminent!"
    RESULTS+=("CRITICAL: Memory ${MEM_USED_PCT}% used")
    CRITICAL=$((CRITICAL + 1))
    alert "Server memory at ${MEM_USED_PCT}% - OOM cascade risk! Top consumers: $(ps aux --sort=-%mem | awk 'NR<=4{print $11}' | tr '\n' ' ')"
    
    # Emergency: free filesystem caches immediately
    sync
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    log "Emergency: dropped filesystem caches"
    
elif [ "$MEM_USED_PCT" -ge 85 ]; then
    log "WARNING: Memory ${MEM_USED_PCT}% used - high memory pressure"
    RESULTS+=("WARNING: Memory ${MEM_USED_PCT}% used")
    FAILURES=$((FAILURES + 1))
    # Proactive: drop caches to prevent cascade
    echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    log "Proactive: dropped filesystem caches"
else
    RESULTS+=("Memory OK (${MEM_USED_PCT}% used, ${MEM_AVAIL}KB available)")
fi

# Check swap usage
SWAP_TOTAL=$(cat /proc/meminfo | grep SwapTotal | awk '{print $2}')
SWAP_FREE=$(cat /proc/meminfo | grep SwapFree | awk '{print $2}')
if [ "$SWAP_TOTAL" -gt 0 ]; then
    SWAP_USED_PCT=$(( (SWAP_TOTAL - SWAP_FREE) * 100 / SWAP_TOTAL ))
    if [ "$SWAP_USED_PCT" -ge 90 ]; then
        log "WARNING: Swap ${SWAP_USED_PCT}% full - system may OOM soon"
        RESULTS+=("Swap nearly full: ${SWAP_USED_PCT}%")
        FAILURES=$((FAILURES + 1))
    fi
fi

# ================================================================
# CHECK 2: OOM killer recent activity
# ================================================================
OOM_RECENT=$(journalctl -k --since "1 hour ago" --no-pager 2>/dev/null | grep -c -i "oom-kill\|Out of memory" || true)
OOM_RECENT=$(echo "$OOM_RECENT" | tr -d '[:space:]')
if [ -z "$OOM_RECENT" ]; then OOM_RECENT=0; fi
if [ "$OOM_RECENT" -gt 0 ] 2>/dev/null; then
    log "WARNING: OOM killer triggered ${OOM_RECENT} time(s) in last hour"
    RESULTS+=("OOM triggered ${OOM_RECENT}x in last hour")
    FAILURES=$((FAILURES + 1))
fi

# ================================================================
# CHECK 3: Tailscale health
# ================================================================
if command -v tailscale &>/dev/null; then
    if tailscale status >/dev/null 2>&1; then
        log "Tailscale status: OK"
        RESULTS+=("Tailscale OK")
    else
        log "WARNING: Tailscale status check failed"
        RESULTS+=("Tailscale DEGRADED")
        FAILURES=$((FAILURES + 1))
        # Try to restart tailscaled
        if systemctl restart tailscaled 2>/dev/null; then
            log "Restarted tailscaled service"
            sleep 3
            if tailscale status >/dev/null 2>&1; then
                log "Tailscale recovered after restart"
                RESULTS+=("Tailscale recovered")
            else
                log "WARNING: Tailscale still degraded after restart"
                RESULTS+=("Tailscale restart failed")
            fi
        else
            log "ERROR: Cannot restart tailscaled"
            RESULTS+=("Tailscale restart failed")
        fi
    fi
else
    RESULTS+=("Tailscale not installed")
fi

# ================================================================
# CHECK 4: sshd process running
# ================================================================
if pgrep -x sshd >/dev/null 2>&1; then
    PID=$(pgrep -x sshd | head -1)
    log "sshd is running (PID: $PID)"
    RESULTS+=("sshd OK (PID $PID)")
else
    log "!! CRITICAL: sshd process NOT found!"
    RESULTS+=("sshd NOT RUNNING")
    FAILURES=$((FAILURES + 1))
fi

# ================================================================
# CHECK 5: sshd service status
# ================================================================
STATE=$(systemctl is-active sshd 2>/dev/null || echo "unknown")
if [ "$STATE" = "active" ]; then
    log "sshd service: active"
    RESULTS+=("service active")
else
    log "WARNING: sshd service: $STATE"
    RESULTS+=("service $STATE")
    FAILURES=$((FAILURES + 1))
fi

# ================================================================
# CHECK 6: SSH port 22 listening
# ================================================================
if ss -tlnp 2>/dev/null | grep -q ":22 "; then
    log "Port 22 is listening"
    RESULTS+=("port 22 OK")
else
    log "!! WARNING: Port 22 NOT listening!"
    RESULTS+=("port 22 DOWN")
    FAILURES=$((FAILURES + 1))
fi

# ================================================================
# CHECK 7: sshd config validity
# ================================================================
if sudo /usr/sbin/sshd -t >/dev/null 2>&1; then
    log "sshd config test passed"
    RESULTS+=("config OK")
else
    log "!! WARNING: sshd config test failed!"
    RESULTS+=("config BROKEN")
    FAILURES=$((FAILURES + 1))
fi

# ================================================================
# CHECK 8: Entropy
# ================================================================
ENTROPY=$(cat /proc/sys/kernel/random/entropy_avail 2>/dev/null || echo "0")
if [ "$ENTROPY" -lt 100 ] 2>/dev/null; then
    log "WARNING: Low entropy ($ENTROPY)"
    RESULTS+=("entropy LOW ($ENTROPY)")
    FAILURES=$((FAILURES + 1))
else
    RESULTS+=("entropy OK ($ENTROPY)")
fi

# ================================================================
# CHECK 9: Network connectivity
# ================================================================
if ping -c1 -W2 8.8.8.8 >/dev/null 2>&1 || ping -c1 -W2 1.1.1.1 >/dev/null 2>&1; then
    RESULTS+=("network OK")
else
    log "WARNING: No internet connectivity"
    RESULTS+=("no internet")
    FAILURES=$((FAILURES + 1))
fi

# ================================================================
# CHECK 10: Recent reboots
# ================================================================
REBOOT_COUNT=$(journalctl --list-boots 2>/dev/null | wc -l)
if [ "$REBOOT_COUNT" -gt 3 ]; then
    log "WARNING: ${REBOOT_COUNT} boots in journal - system unstable"
    RESULTS+=("${REBOOT_COUNT} recent reboots")
    FAILURES=$((FAILURES + 1))
fi

# ================================================================
# ACTION: Targeted recovery
# ================================================================
SSH_ISSUES=$((FAILURES + CRITICAL))

# Only restart sshd if SSH-specific checks failed (service, process, port, config)
SSHD_FAILED=0
for r in "${RESULTS[@]}"; do
    case "$r" in
        *NOT*RUNNING*|"service unknown"|"port 22 DOWN"|"config BROKEN"*)
            SSHD_FAILED=1
            ;;
    esac
done

if [ $SSHD_FAILED -eq 1 ]; then
    log ""
    log "SSH issues detected - attempting restart..."
    
    # Restart sshd
    if sudo systemctl restart sshd 2>/dev/null; then
        log "sshd restarted successfully"
        RESULTS+=("restarted OK")
    else
        log "ERROR: Failed to restart sshd"
        RESULTS+=("restart FAILED")
        CRITICAL=$((CRITICAL + 1))
    fi
    
    # Verify recovery
    sleep 2
    if systemctl is-active sshd >/dev/null 2>&1 && pgrep -x sshd >/dev/null 2>&1; then
        log "SSH verified OK after restart"
        RESULTS+=("final OK")
    else
        log "ERROR: SSH still failing after restart!"
        RESULTS+=("final FAIL")
    fi
fi

# Send alert for critical issues
if [ $CRITICAL -gt 0 ]; then
    alert "CRITICAL: ${CRITICAL} critical issue(s) on ${HOSTNAME}. Memory: ${MEM_USED_PCT}%, sshd: $STATE"
fi

# Log to file for historical tracking
mkdir -p ~/.hermes/logs 2>/dev/null || true
echo "$(date '+%Y-%m-%d %H:%M:%S') | Memory: ${MEM_USED_PCT}% | Issues: $CRITICAL crit, $FAILURES warn | Results: ${RESULTS[*]}" >> ~/.hermes/logs/ssh-self-heal.log 2>/dev/null || true

echo ""
echo "=== Summary ==="
for r in "${RESULTS[@]}"; do
    echo "  - $r"
done

# Exit code: 0 = SSH is connectable, non-zero = SSH has issues
# Warnings like "6 recent reboots" or memory warnings don't mean SSH is down
if [ $SSHD_FAILED -eq 0 ]; then
    echo "SSH OK ($(date '+%H:%M:%S'))"
    exit 0
else
    echo "SSH ISSUES: ${CRITICAL} critical, ${FAILURES} warnings"
    exit 1
fi
