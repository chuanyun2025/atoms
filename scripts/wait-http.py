"""Wait for an explicitly supplied local health endpoint."""
import sys
import time
import urllib.error
import urllib.request

url=sys.argv[1]
deadline=time.monotonic()+45
while time.monotonic()<deadline:
    try:
        with urllib.request.urlopen(url,timeout=2) as response:
            if response.status==200:
                print("Health endpoint ready");break
    except (urllib.error.URLError,TimeoutError):
        pass
    time.sleep(.5)
else:
    raise SystemExit("Health endpoint did not become ready within 45 seconds")
