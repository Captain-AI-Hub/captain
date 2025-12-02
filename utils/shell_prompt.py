"""
Shell Prompt utilities using prompt_toolkit
提供命令补全、历史记录等功能
"""
import os
import sys
from pathlib import Path
from typing import List, Optional, Callable, Set

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import (
    Completer, Completion, WordCompleter, 
    NestedCompleter, merge_completers
)
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.keys import Keys
from prompt_toolkit.key_binding import KeyBindings

from utils.utils import get_workspace_path, list_prompt_templates
import glob


def is_path_like(text: str) -> bool:
    """检查文本是否像文件路径（仅限 workspace 内的相对路径）"""
    if not text:
        return False
    # 只允许 ./ 开头的相对路径（不允许 ../ 防止目录穿越）
    if text.startswith("./"):
        return True
    return False


def get_file_completions(partial_path: str, extensions: Optional[List[str]] = None):
    """
    获取文件路径补全（限制在 workspace 内）
    
    Args:
        partial_path: 部分路径（用户已输入的部分）
        extensions: 可选的文件扩展名过滤（如 ['.md', '.txt']）
    
    Yields:
        Completion 对象
    """
    workspace = get_workspace_path() or "."
    workspace_resolved = os.path.realpath(workspace)
    
    # 处理路径
    if not partial_path:
        partial_path = "./"
    
    # 安全检查：不允许 ../ 和绝对路径
    if ".." in partial_path or os.path.isabs(partial_path):
        return
    
    # 规范化路径分隔符
    partial_path = partial_path.replace("\\", "/")
    
    # 确定搜索路径（始终基于 workspace）
    search_base = os.path.join(workspace, partial_path)
    search_base = os.path.normpath(search_base)
    
    # 安全检查：确保路径在 workspace 内
    search_base_resolved = os.path.realpath(search_base)
    if not search_base_resolved.startswith(workspace_resolved):
        return
    
    # 如果是目录，列出目录内容
    if os.path.isdir(search_base):
        search_dir = search_base
        prefix_part = ""
        # 保持用户输入的路径格式
        if partial_path.endswith("/") or partial_path.endswith(os.sep):
            user_prefix = partial_path
        else:
            user_prefix = partial_path + "/"
    else:
        # 否则按前缀匹配
        search_dir = os.path.dirname(search_base)
        prefix_part = os.path.basename(search_base).lower()
        # 获取用户输入的目录部分
        if "/" in partial_path:
            user_prefix = partial_path.rsplit("/", 1)[0] + "/"
        elif os.sep in partial_path:
            user_prefix = partial_path.rsplit(os.sep, 1)[0] + "/"
        else:
            user_prefix = ""
    
    # 再次检查 search_dir 是否在 workspace 内
    search_dir_resolved = os.path.realpath(search_dir)
    if not search_dir_resolved.startswith(workspace_resolved):
        return
    
    if not os.path.isdir(search_dir):
        return
    
    try:
        entries = os.listdir(search_dir)
        count = 0
        for entry in sorted(entries):
            if count >= 30:  # 限制数量
                break
            
            # 跳过隐藏文件（除非用户明确输入 .）
            if entry.startswith(".") and not prefix_part.startswith("."):
                continue
            
            # 前缀匹配
            if prefix_part and not entry.lower().startswith(prefix_part):
                continue
            
            full_path = os.path.join(search_dir, entry)
            is_dir = os.path.isdir(full_path)
            
            # 扩展名过滤（仅对文件）
            if extensions and not is_dir:
                if not any(entry.lower().endswith(ext.lower()) for ext in extensions):
                    continue
            
            # 构建显示名称和补全文本
            if is_dir:
                display_name = entry + "/"
                meta = "dir"
            else:
                display_name = entry
                meta = "file"
            
            # 计算 start_position
            if prefix_part:
                start_pos = -len(prefix_part)
            else:
                start_pos = 0
            
            yield Completion(
                entry + ("/" if is_dir else ""),
                start_position=start_pos,
                display=display_name,
                display_meta=meta
            )
            count += 1
    except (OSError, PermissionError):
        pass


def get_system_commands() -> Set[str]:
    """
    从系统 PATH 环境变量获取可执行命令列表
    支持 Windows/Linux/Mac
    """
    commands = set()
    
    # Windows 可执行文件扩展名
    if sys.platform == "win32":
        pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").lower().split(";")
    else:
        pathext = [""]
    
    # 遍历 PATH 中的目录
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    
    for path_dir in path_dirs:
        if not path_dir or not os.path.isdir(path_dir):
            continue
        
        try:
            for entry in os.scandir(path_dir):
                if not entry.is_file():
                    continue
                
                name = entry.name
                
                if sys.platform == "win32":
                    # Windows: 检查是否有可执行扩展名
                    name_lower = name.lower()
                    for ext in pathext:
                        if name_lower.endswith(ext):
                            # 去掉扩展名
                            cmd_name = name[:len(name) - len(ext)] if ext else name
                            commands.add(cmd_name.lower())
                            break
                else:
                    # Linux/Mac: 检查是否有执行权限
                    if os.access(entry.path, os.X_OK):
                        commands.add(name)
        except (PermissionError, OSError):
            # 跳过无法访问的目录
            continue
    
    return commands


# 缓存系统命令，避免每次补全都扫描
_system_commands_cache: Optional[Set[str]] = None


def get_cached_system_commands() -> Set[str]:
    """获取缓存的系统命令列表"""
    global _system_commands_cache
    if _system_commands_cache is None:
        _system_commands_cache = get_system_commands()
    return _system_commands_cache


def refresh_system_commands():
    """刷新系统命令缓存"""
    global _system_commands_cache
    _system_commands_cache = get_system_commands()


def get_captain_dir() -> Path:
    """获取 .captain 目录路径"""
    workspace = get_workspace_path()
    if not workspace:
        workspace = "."
    captain_dir = Path(workspace).resolve() / ".captain"
    captain_dir.mkdir(parents=True, exist_ok=True)
    return captain_dir


def get_history_file() -> Path:
    """获取历史记录文件路径"""
    return get_captain_dir() / "history.txt"


class CaptainCompleter(Completer):
    """
    Captain 命令补全器
    支持:
    - 内置命令: exit, quit, shell, /list
    - prompt 模板命令: /init, /audit 等
    - shell 命令补全
    """
    
    def __init__(self, get_templates_func: Optional[Callable] = None):
        self.get_templates_func = get_templates_func or list_prompt_templates
        self._builtin_commands = ["exit", "quit", "q", "shell ", "vector ", "/list"]
    
    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = document.get_word_before_cursor()
        
        # 全局文件路径补全：检查当前正在输入的部分是否是路径
        # 获取最后一个空格后的内容作为可能的路径
        if " " in text:
            last_part = text.rsplit(" ", 1)[-1]
        else:
            last_part = text
        
        # 如果最后输入的部分看起来像路径，进行文件补全
        if is_path_like(last_part):
            yield from get_file_completions(last_part)
            return
        
        # 空输入或只有开头字符，显示所有可用命令
        if not text or text == word:
            # 内置命令
            for cmd in self._builtin_commands:
                if cmd.startswith(text.lower()):
                    yield Completion(
                        cmd,
                        start_position=-len(text),
                        display_meta="built-in"
                    )
            
            # prompt 模板命令
            if text.startswith("/") or not text:
                templates = self.get_templates_func()
                for name, info in templates.items():
                    cmd = f"/{name}"
                    if cmd.startswith(text) or not text:
                        args_hint = " ".join(f'{a}=""' for a in info.get("args", []))
                        display = f"/{name} {args_hint}".strip()
                        yield Completion(
                            display,
                            start_position=-len(text),
                            display=f"/{name}",
                            display_meta=f"args: {', '.join(info.get('args', [])) or 'none'}"
                        )
        
        # / 开头，补全 prompt 模板
        elif text.startswith("/"):
            templates = self.get_templates_func()
            prefix = text[1:]  # 去掉 /
            
            for name, info in templates.items():
                if name.startswith(prefix):
                    args_hint = " ".join(f'{a}=""' for a in info.get("args", []))
                    display = f"/{name} {args_hint}".strip()
                    yield Completion(
                        display,
                        start_position=-len(text),
                        display=f"/{name}",
                        display_meta=f"args: {', '.join(info.get('args', [])) or 'none'}"
                    )
            
            # /list 命令
            if "list".startswith(prefix):
                yield Completion(
                    "/list",
                    start_position=-len(text),
                    display_meta="list all templates"
                )
        
        # shell 命令补全 - 使用系统 PATH 中的命令
        elif text.startswith("shell "):
            shell_part = text[6:]  # 去掉 "shell "
            if shell_part:
                # 只在有输入时才补全，避免显示太多命令
                system_cmds = get_cached_system_commands()
                shell_part_lower = shell_part.lower()
                
                # 优先显示前缀匹配的命令
                matches = []
                for cmd in system_cmds:
                    if cmd.lower().startswith(shell_part_lower):
                        matches.append(cmd)
                
                # 限制显示数量，按字母排序
                for cmd in sorted(matches)[:50]:
                    yield Completion(
                        cmd,
                        start_position=-len(shell_part),
                        display_meta="system"
                    )
        
        # vector 命令补全
        elif text.startswith("vector "):
            vector_part = text[7:]  # 去掉 "vector "
            parts = vector_part.split()
            
            if len(parts) == 0 or (len(parts) == 1 and not vector_part.endswith(" ")):
                # 补全 action: list, store, rag
                action_part = parts[0] if parts else ""
                for action, meta in [("list", "list collections"), ("store", "store markdown"), ("rag", "RAG query")]:
                    if action.startswith(action_part.lower()):
                        yield Completion(
                            action,
                            start_position=-len(action_part),
                            display_meta=meta
                        )
            
            # vector list - 无需更多参数
            elif parts[0].lower() == "list":
                pass  # list 命令完成
            
            # vector rag 补全
            elif parts[0].lower() == "rag":
                if len(parts) == 1 and vector_part.endswith(" "):
                    yield Completion(
                        "",
                        start_position=0,
                        display="{collection}",
                        display_meta="collection name (required)"
                    )
                elif len(parts) == 2 and vector_part.endswith(" "):
                    yield Completion(
                        "",
                        start_position=0,
                        display="{query}",
                        display_meta="your question (required)"
                    )
                elif len(parts) == 3 and vector_part.endswith(" "):
                    yield Completion(
                        "5",
                        start_position=0,
                        display="[top_k]",
                        display_meta="optional, default: 5"
                    )
            
            # vector store 补全
            elif parts[0].lower() == "store":
                if len(parts) == 1 or (len(parts) == 2 and not vector_part.endswith(" ")):
                    target_part = parts[1] if len(parts) > 1 else ""
                    if "markdown".startswith(target_part.lower()):
                        yield Completion(
                            "markdown",
                            start_position=-len(target_part),
                            display_meta="target"
                        )
                elif len(parts) >= 2 and parts[1].lower() == "markdown":
                    # 文件路径补全
                    if len(parts) == 2 and vector_part.endswith(" "):
                        # 刚输入空格，显示当前目录下的 .md 文件
                        yield from get_file_completions("./", extensions=[".md"])
                    elif len(parts) == 3 and not vector_part.endswith(" "):
                        # 正在输入路径，补全文件
                        partial_path = parts[2]
                        yield from get_file_completions(partial_path, extensions=[".md"])
                    elif len(parts) == 3 and vector_part.endswith(" "):
                        yield Completion(
                            "",
                            start_position=0,
                            display="<collection_name>",
                            display_meta="optional, default: filename"
                        )
                    elif len(parts) == 4 and vector_part.endswith(" "):
                        yield Completion(
                            "600",
                            start_position=0,
                            display="<chunk_size>",
                            display_meta="optional, default: 600"
                        )
                    elif len(parts) == 5 and vector_part.endswith(" "):
                        yield Completion(
                            "100",
                            start_position=0,
                            display="<chunk_overlap>",
                            display_meta="optional, default: 100"
                        )


def create_prompt_style() -> Style:
    """创建 prompt 样式"""
    return Style.from_dict({
        "prompt": "bold ansiblue",
        "prompt.arg": "ansicyan",
        # 补全菜单样式
        "completion-menu": "bg:ansiblack ansiwhite",
        "completion-menu.completion": "",
        "completion-menu.completion.current": "bg:ansiblue ansiwhite",
        "completion-menu.meta": "bg:ansiblack ansigray italic",
        "completion-menu.meta.current": "bg:ansiblue ansiwhite",
        # 自动建议样式
        "auto-suggest": "ansigray italic",
    })


def create_key_bindings() -> KeyBindings:
    """创建自定义快捷键绑定"""
    kb = KeyBindings()
    
    @kb.add("c-l")
    def clear_screen(event):
        """Ctrl+L 清屏"""
        event.app.renderer.clear()
    
    @kb.add("c-u")
    def clear_line(event):
        """Ctrl+U 清除当前行"""
        event.current_buffer.delete_before_cursor(len(event.current_buffer.text))
    
    @kb.add("enter")
    def handle_enter(event):
        """
        Enter 键处理：
        - 补全菜单打开且有选中项时：确认补全（目录则继续补全，文件则确认不发送）
        - 补全菜单打开但无选中项时：正常提交
        - 补全菜单关闭时：正常提交
        """
        buffer = event.current_buffer
        
        # 检查补全菜单是否打开且有选中项
        if buffer.complete_state:
            completions = buffer.complete_state.completions
            index = buffer.complete_state.complete_index
            
            # 有选中的补全项
            if completions and index is not None and 0 <= index < len(completions):
                selected = completions[index]
                completion_text = selected.text
                
                # 应用补全
                buffer.apply_completion(selected)
                
                # 如果是目录（以 / 结尾），触发新的补全
                if completion_text.endswith("/"):
                    buffer.start_completion(select_first=False)
                # 如果是文件，补全已应用，菜单会自动关闭，不提交
                return
        
        # 补全菜单未打开或无选中项，正常提交
        buffer.validate_and_handle()
    
    return kb


def create_prompt_session(
    history_file: Optional[Path] = None,
    enable_history: bool = True,
    enable_auto_suggest: bool = True,
    enable_completion: bool = True
) -> PromptSession:
    """
    创建配置好的 PromptSession
    
    Args:
        history_file: 历史记录文件路径，默认为 .captain/history.txt
        enable_history: 是否启用历史记录
        enable_auto_suggest: 是否启用自动建议
        enable_completion: 是否启用命令补全
    
    Returns:
        配置好的 PromptSession
    """
    kwargs = {
        "style": create_prompt_style(),
        "key_bindings": create_key_bindings(),
    }
    
    # 历史记录
    if enable_history:
        if history_file is None:
            history_file = get_history_file()
        kwargs["history"] = FileHistory(str(history_file))
    
    # 自动建议（基于历史记录）
    if enable_auto_suggest and enable_history:
        kwargs["auto_suggest"] = AutoSuggestFromHistory()
    
    # 命令补全
    if enable_completion:
        kwargs["completer"] = CaptainCompleter()
        kwargs["complete_while_typing"] = True
    
    return PromptSession(**kwargs)


def get_prompt_message() -> FormattedText:
    """获取格式化的 prompt 消息"""
    return FormattedText([
        ("", "\n"),
        ("class:prompt", "> "),
    ])


class CaptainShell:
    """
    Captain Shell 封装类
    提供完整的命令行交互功能
    """
    
    def __init__(
        self,
        enable_history: bool = True,
        enable_auto_suggest: bool = True,
        enable_completion: bool = True
    ):
        self.session = create_prompt_session(
            enable_history=enable_history,
            enable_auto_suggest=enable_auto_suggest,
            enable_completion=enable_completion
        )
        self.prompt_message = get_prompt_message()
        self.style = create_prompt_style()
    
    async def prompt_async(self) -> str:
        """异步获取用户输入"""
        return await self.session.prompt_async(
            self.prompt_message,
            style=self.style
        )
    
    def prompt(self) -> str:
        """同步获取用户输入"""
        return self.session.prompt(
            self.prompt_message,
            style=self.style
        )
    
    def get_history(self) -> List[str]:
        """获取历史记录列表"""
        history_file = get_history_file()
        if history_file.exists():
            with open(history_file, "r", encoding="utf-8") as f:
                # FileHistory 格式: 每行一个命令，+ 开头
                lines = f.readlines()
                return [line[1:].strip() for line in lines if line.startswith("+")]
        return []
    
    def clear_history(self):
        """清除历史记录"""
        history_file = get_history_file()
        if history_file.exists():
            history_file.unlink()
    
    def add_to_history(self, command: str):
        """手动添加命令到历史记录"""
        if hasattr(self.session, "history") and self.session.history:
            self.session.history.append_string(command)

