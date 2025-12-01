import os
import sys
import shutil
import subprocess
from typing import Optional

# 统一控制台编码（兼容 Windows）
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore
    except AttributeError:
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

APP_NAME = "captain"
OUTPUT_DIR = ".build"
WORK_DIR = os.path.join(OUTPUT_DIR, "pyinstaller-work")
SPEC_DIR = OUTPUT_DIR

# 需要完整收集的模块/包（包含本地与第三方）
COLLECT_ALL_PACKAGES = [
    # 本地包
    "agent",
    "chat",
    "tools",
    "utils",
    # LangChain 相关
    "langchain",
    "langchain_core",
    "langchain_community",
    "langgraph",
    "deepagents",
    "langchain_deepseek",
    "langchain_openai",
    "langchain_ollama",
    "langchain_anthropic",
    "langchain_groq",
    "langchain_mcp_adapters",
    "langchain_google_genai",
    "langchain_mistralai",
    "langchain_huggingface",
    "langchain_xai",
    "langchain_huggingface",
    "langchain_qwq",
    "langchain_google_vertexai",
    "chromadb",
    "langchain_chroma",
    # 其他依赖
    "mcp",
    "pydantic",
    "pydantic_core",
    "httpx",
    "openai",
    "anthropic",
    "rich",
    "aiosqlite",
    "tavily",
    "langgraph_checkpoint_sqlite",
    "prompt_toolkit",
]


def clean() -> None:
    """清理历史构建产物，保证可重复构建"""
    print("[*] Cleaning up previous builds...")
    paths = [
        OUTPUT_DIR,
        "build",
        "dist",
        "main.dist",
        "main.app",
        "captain.dist",
        "captain.app",
    ]

    for path in paths:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            print(f"    Removed directory {path}")
        elif os.path.isfile(path):
            try:
                os.remove(path)
                print(f"    Removed file {path}")
            except OSError:
                pass


def ensure_pyinstaller_installed() -> None:
    """保证 PyInstaller 可用"""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[*] PyInstaller not found. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build() -> Optional[str]:
    """执行 PyInstaller 构建，返回标准化后的产物目录"""
    print("[+] Starting PyInstaller build...")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(WORK_DIR, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--console",
        f"--name={APP_NAME}",
        f"--distpath={OUTPUT_DIR}",
        f"--workpath={WORK_DIR}",
        f"--specpath={SPEC_DIR}",
    ]

    for package in COLLECT_ALL_PACKAGES:
        cmd.append(f"--collect-all={package}")

    cmd.append("main.py")

    print(f"[>] Command: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        print("[ERROR] PyInstaller build failed.")
        sys.exit(1)

    normalized_path = normalize_output_directory()
    if normalized_path:
        print(f"[SUCCESS] Build finished. Output: {normalized_path}")
    else:
        print("[WARNING] Unable to locate PyInstaller output folder.")
    return normalized_path


def normalize_output_directory() -> Optional[str]:
    """
    PyInstaller 默认输出 captain 或 captain.app，
    这里统一重命名为 captain.dist/captain.app。
    """
    app_bundle_src = os.path.join(OUTPUT_DIR, f"{APP_NAME}.app")
    folder_src = os.path.join(OUTPUT_DIR, APP_NAME)
    app_target = os.path.join(OUTPUT_DIR, "captain.app")
    folder_target = os.path.join(OUTPUT_DIR, "captain.dist")

    if os.path.exists(app_bundle_src):
        _replace_path(app_target)
        shutil.move(app_bundle_src, app_target)
        return app_target

    if os.path.exists(folder_src):
        _replace_path(folder_target)
        shutil.move(folder_src, folder_target)
        return folder_target

    return None


def _replace_path(path: str) -> None:
    """删除已有路径（文件或目录），避免移动时冲突"""
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.isfile(path):
        try:
            os.remove(path)
        except OSError:
            pass


def post_build(dist_path: Optional[str]) -> None:
    """构建后复制配置示例文件"""
    if not dist_path or not os.path.exists(dist_path):
        print("[WARNING] Dist directory missing, skip post-build tasks.")
        return

    print("[*] Running post-build tasks...")
    config_template = "config.example.toml"

    if not os.path.exists(config_template):
        print(f"    [WARNING] Template file not found: {config_template}")
        return

    target_dir = dist_path
    if dist_path.endswith(".app"):
        macos_dir = os.path.join(dist_path, "Contents", "MacOS")
        if os.path.exists(macos_dir):
            target_dir = macos_dir

    os.makedirs(target_dir, exist_ok=True)
    target_config = os.path.join(target_dir, "config.toml")
    shutil.copy2(config_template, target_config)
    print(f"    Copied template '{config_template}' to '{target_config}'")

    # 复制 README.md 文件
    readme_source = "README.md"
    if os.path.exists(readme_source):
        try:
            readme_target = os.path.join(target_dir, "README.md")
            shutil.copy2(readme_source, readme_target)
            print(f"    Copied '{readme_source}' to '{readme_target}'")
        except Exception as e:
            print(f"    Failed to copy README file: {e}")
    else:
        print(f"    [WARNING] README.md not found: {readme_source}")

    print(f"\n[DONE] All done! Build output is in '{dist_path}'.")


if __name__ == "__main__":
    ensure_pyinstaller_installed()
    clean()
    output_path = build()
    post_build(output_path)

