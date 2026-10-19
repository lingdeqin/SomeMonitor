"""打包入口（PyInstaller）：源码运行仍用 `python -m app.main`。"""
from app.main import main

if __name__ == "__main__":
    raise SystemExit(main())
