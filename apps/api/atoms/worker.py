"""Process entrypoint (`python -m atoms.worker`) and alias for runtime worker."""

import asyncio
import sys

from atoms.runtime import worker as _worker

if __name__ == "__main__":
    asyncio.run(_worker.main())
else:
    sys.modules[__name__] = _worker
