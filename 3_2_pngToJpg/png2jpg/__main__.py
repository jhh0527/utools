import sys
from pathlib import Path

# ``python -m png2jpg`` 시 상위 폴더를 path 에 추가
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from png_to_jpg import main  # noqa: E402

raise SystemExit(main())
