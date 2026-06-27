import os, sys
import subprocess
# Check Windows Firewall rules for Soulseek
result = subprocess.run(
    "netsh advfirewall firewall show rule name=all dir=in | findstr /i soulseek",
    shell=True, capture_output=True, text=True, timeout=5)
out = result.stdout.strip() or "(no matching firewall rules)"
print("FW rules:", out)

# Check UPnP status on router
result2 = subprocess.run(
    "netsh interface portproxy show all",
    shell=True, capture_output=True, text=True, timeout=5)
out2 = result2.stdout.strip() or "(no port proxies)"
print("Port proxies:", out2)

# Check listening ports
result3 = subprocess.run(
    "netstat -ano | findstr 6000",
    shell=True, capture_output=True, text=True, timeout=5)
out3 = result3.stdout.strip() or "(nothing on 6000x)"
print("Listening:", out3[:500])
