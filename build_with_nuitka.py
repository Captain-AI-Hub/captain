import os
import sys
import shutil
import platform
import subprocess

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')  # type: ignore
    except AttributeError:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def clean():
    """清理之前的构建文件"""
    print("[*] Cleaning up previous builds...")
    dirs_to_remove = [".build", "build", "main.build", "main.dist", "main.onefile-build", "captain.build", "captain.dist", "captain.onefile-build"]
    for d in dirs_to_remove:
        if os.path.exists(d):
            try:
                shutil.rmtree(d)
                print(f"    Removed {d}")
            except Exception as e:
                print(f"    Failed to remove {d}: {e}")

def get_os_specific_flags():
    """获取特定操作系统的 Nuitka 参数"""
    system = platform.system()
    flags = []
    
    if system == "Windows":
        # Windows 使用 MinGW-w64 编译器
        flags.append("--mingw64")
    elif system == "Linux":
        # Linux 特定参数
        pass
    elif system == "Darwin":
        # MacOS 特定参数
        flags.append("--macos-create-app-bundle")
    
    return flags

def prepare_compiler_environment():
    """Return a copy of the current environment for the subprocess call."""
    return os.environ.copy()


def ensure_windows_mingw():
    """Validate that MinGW-w64 toolchain is available on Windows."""
    if platform.system() != "Windows":
        return

    gcc_path = shutil.which("gcc")
    if not gcc_path:
        print("[ERROR] MinGW-w64 (gcc) not found in PATH. Make sure MinGW is installed and added to PATH.")
        sys.exit(1)

    print(f"[*] Using MinGW-w64 compiler at: {gcc_path}")
def build():
    """执行 Nuitka 构建"""
    print("[+] Starting Nuitka build...")

    ensure_windows_mingw()

    output_dir = ".build"
    main_file = "main.py"
    # 基础命令
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",           # 独立环境，不依赖系统 Python
        # "--onefile",              # 打包成单文件
        "--assume-yes-for-downloads", # 自动下载必要的编译器/依赖
        f"--output-dir={output_dir}", # 输出目录
        "--output-filename=captain",  # 指定输出可执行文件名为 captain
        "--remove-output",        # 构建后删除临时文件
        "--show-progress",        # 显示进度条
        "--show-memory",          # 显示内存使用
        
        # ====== 让 Nuitka 自动追踪所有导入 ======
        "--follow-imports",       # 跟踪所有导入（这是关键！）
        
        # 手动包含本地包
        "--include-package=utils",
        "--include-package=tools",
        "--include-package=chat",
        "--include-package=agent",

        # 强制包含 LangChain 核心库及其所有子模块（使用延迟加载，必须显式包含）
        "--include-package=langchain",
        "--include-package=langchain_core",
        "--include-package=langchain_core.load",
        "--include-module=langchain_core.load.dump",
        "--include-module=langchain_core.load.load",
        "--include-module=langchain_core.load.serializable",
        "--include-package=langchain_core.runnables",
        "--include-package=langchain_core.tracers",
        "--include-package=langchain_core.callbacks",
        "--include-package=langgraph",
        "--include-package=deepagents",
        "--include-package=langchain_community",
        
        # 手动包含 LangChain 动态加载的扩展（通过配置字符串加载，静态分析无法追踪）
        "--include-package=langchain_deepseek",
        "--include-package=langchain_openai",
        "--include-package=langchain_ollama",
        "--include-package=langchain_anthropic",
        "--include-package=langchain_groq",
        "--include-package=langchain_google_genai",
        "--include-package=langchain_mistralai",
        "--include-package=langchain_huggingface",
        "--include-package=langchain_xai",
        "--include-package=langchain_huggingface",
        "--include-package=langchain_qwq",
        "--include-package=chromadb",
        "--include-package=langchain_chroma",
        "--include-package=langchain_google_vertexai",
        
        # 包含 MCP 相关包（可能也使用动态导入）
        "--include-package=mcp",
        "--include-package=langchain_mcp_adapters",
        
        # 包含其他可能动态导入的包
        "--include-package=pydantic",
        "--include-package=pydantic_core",
        "--include-package=httpx",
        "--include-package=openai",
        "--include-package=anthropic",
        "--include-package=rich",
        "--include-package=aiosqlite",
        
        # 包含数据文件
        # "--include-data-dir=./data=data",

        # 优化选项
        "--noinclude-pytest-mode=nofollow",
        "--noinclude-setuptools-mode=nofollow",
        
        # 显式禁止 aiosqlite 导入测试模块（消除 anti-bloat 警告）
        "--nofollow-import-to=aiosqlite.tests",
        "--nofollow-import-to=unittest",
        "--nofollow-import-to=doctest",
    ]
    
    print("[*] Using Nuitka's automatic import tracking (--follow-imports)")
    print("    This will automatically detect and include all required packages")

    # 添加系统特定参数
    cmd.extend(get_os_specific_flags())

    # 指定入口文件
    cmd.append(main_file)

    # 打印并执行命令
    print(f"[>] Command: {' '.join(cmd)}")
    env = prepare_compiler_environment()

    try:
        subprocess.check_call(cmd, env=env)
        print("[SUCCESS] Build finished successfully!")
    except subprocess.CalledProcessError as e:
        print("[ERROR] Build failed!")
        sys.exit(1)

def post_build():
    """构建后处理：复制配置文件等"""
    print("[*] Running post-build tasks...")
    
    # 在 standalone 模式下，Nuitka 会创建一个 .dist 文件夹
    # 目录名基于入口文件名（main.py），所以会创建 main.dist
    # 但在 macOS 上使用 --macos-create-app-bundle 时会创建 main.app
    system = platform.system()
    dist_dir = None
    config_target_dir = None
    
    if system == "Darwin":
        # macOS: 检查是否存在 main.app bundle
        app_bundle = os.path.join(".build", "main.app")
        if os.path.exists(app_bundle):
            dist_dir = app_bundle
            # 在 app bundle 中，可执行文件在 Contents/MacOS/ 目录下
            config_target_dir = os.path.join(app_bundle, "Contents", "MacOS")
            if not os.path.exists(config_target_dir):
                # 如果 Contents/MacOS 不存在，尝试直接在 app bundle 根目录
                config_target_dir = app_bundle
        else:
            # 回退到 main.dist
            dist_dir = os.path.join(".build", "main.dist")
            config_target_dir = dist_dir
    else:
        # Windows/Linux: 使用 main.dist
        dist_dir = os.path.join(".build", "main.dist")
        config_target_dir = dist_dir
    
    if not os.path.exists(dist_dir):
        print(f"    [WARNING] Dist directory {dist_dir} not found. Did the build fail or using onefile mode?")
        dist_dir = ".build"
        config_target_dir = ".build"

    # 查找示例配置文件
    # 找 config.example.toml
    possible_configs = "config.example.toml"
    source_config = None
    
    if os.path.exists(possible_configs):
        source_config = possible_configs
            
    if source_config:
        # 确保目标目录存在
        os.makedirs(config_target_dir, exist_ok=True)
        # 目标文件名 config.toml，放入 dist 目录与可执行文件同级
        target_config = os.path.join(config_target_dir, "config.toml")
        try:
            shutil.copy2(source_config, target_config)
            print(f"    Copied template '{source_config}' to '{target_config}'")
        except Exception as e:
            print(f"    Failed to copy config file: {e}")
    else:
        print(f"    [WARNING] No example config file found: {possible_configs}")

    # 复制 README.md 文件
    readme_source = "README.md"
    if os.path.exists(readme_source):
        try:
            readme_target = os.path.join(config_target_dir, "README.md")
            shutil.copy2(readme_source, readme_target)
            print(f"    Copied '{readme_source}' to '{readme_target}'")
        except Exception as e:
            print(f"    Failed to copy README file: {e}")
    else:
        print(f"    [WARNING] README.md not found: {readme_source}")

    print(f"\n[DONE] All done! Build output is in '{dist_dir}' folder.")

if __name__ == "__main__":
    # 确保安装了 Nuitka
    try:
        import nuitka
    except ImportError:
        print("[*] Nuitka not installed. Installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "nuitka", "zstandard"])

    clean()
    build()
    post_build()
