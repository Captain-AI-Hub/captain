import tomllib
import os
import re
from pathlib import Path
from typing import Optional, Tuple

_toml_path = ""
_captain_db_path = ""
_local_file_store_path = ""
_workspace_path = ""

_major_config = {
    "configurable": {
        "thread_id": "major_thread"
    }
}

def get_major_config():
    """
    获取major配置
    Returns:
        major_config: major配置
    """
    return _major_config

def set_toml_path(path: str):
    """
    设置toml路径
    Args:
        path: toml路径
    """
    global _toml_path
    _toml_path = path

def get_mcp_servers():
    """
    获取mcpServers配置
    Returns:
        mcp_servers: mcpServers配置
    """
    if not _toml_path:
        return "Error: toml_path is None"
    with open(_toml_path, "rb") as f:
        config = tomllib.load(f)
    return config["mcp_servers"]["content"]

def get_model_config():
    """
    获取完整的 TOML 配置
    Returns:
        config: 完整配置字典
    """
    if not _toml_path:
        return "Error: toml_path is None"
    with open(_toml_path, "rb") as f:
        config = tomllib.load(f)
    return config

def get_major_agent_config():
    """
    获取 major agent 配置
    Returns:
        major_agent_config: major agent 配置字典
    """
    config = get_model_config()
    if config == "Error: toml_path is None":
        return None
    return config.get("model_config", {}).get("major_agent")

def get_sub_agents_config():
    """
    获取所有 sub agent 配置
    Returns:
        sub_agents: {agent_name: agent_config} 字典
    """
    config = get_model_config()
    if config == "Error: toml_path is None":
        return {}
    
    model_config = config.get("model_config", {})
    return {k: v for k, v in model_config.items() if k != "major_agent"}

def get_tavily_api_key():
    """
    获取 Tavily API Key
    Returns:
        tavily_api_key: Tavily API Key
    """
    config = get_model_config()
    if config == "Error: toml_path is None":
        return None
    tavily_config = config.get("tavily_config", {})
    return tavily_config.get("tavily_api_key", "")

def get_prompt_templates():
    """
    获取所有 prompt templates
    Returns:
        prompt_templates: {template_name: template_config} 字典
    """
    config = get_model_config()
    if config == "Error: toml_path is None":
        return {}
    return config.get("prompt_templates", {})

def parse_prompt_command(command: str) -> Tuple[Optional[str], dict]:
    """
    解析 prompt 命令
    示例:
        "init" -> ("init", {})
        "audit file=\"test.c\"" -> ("audit", {"file": "test.c"})
        "example arg1=\"val1\" arg2=\"val2\"" -> ("example", {"arg1": "val1", "arg2": "val2"})
    
    Args:
        command: 用户输入的命令字符串
    Returns:
        (template_name, args_dict): 模板名称和参数字典
    """
    if not command or not command.strip():
        return None, {}
    
    parts = command.strip().split(maxsplit=1)
    template_name = parts[0]
    args_dict = {}
    
    if len(parts) > 1:
        args_str = parts[1]
        # 匹配 key="value" 或 key='value' 格式
        pattern = r'(\w+)\s*=\s*["\']([^"\']*)["\']'
        matches = re.findall(pattern, args_str)
        for key, value in matches:
            args_dict[key] = value
    
    return template_name, args_dict

def get_prompt(command: str) -> Optional[str]:
    """
    根据命令获取并处理 prompt
    示例:
        get_prompt("init") -> "Review the current directory..."
        get_prompt("audit file=\"test.c\"") -> "Carefully audit test.c to identify..."
    
    Args:
        command: 用户输入的命令字符串
    Returns:
        处理后的 prompt 字符串，如果模板不存在则返回 None
    """
    template_name, args_dict = parse_prompt_command(command)
    if template_name is None:
        return None
    
    templates = get_prompt_templates()
    template = templates.get(template_name)
    
    if template is None:
        return None
    
    prompt = template.get("prompt", "")
    required_args = template.get("args", [])
    
    # 检查是否提供了所有必需参数
    missing_args = [arg for arg in required_args if arg not in args_dict]
    if missing_args:
        return f"Error: Missing required arguments: {', '.join(missing_args)}"
    
    # 替换 prompt 中的占位符
    for key, value in args_dict.items():
        prompt = prompt.replace(f"{{{key}}}", value)
    
    return prompt.strip()

def list_prompt_templates() -> dict:
    """
    列出所有可用的 prompt templates 及其参数
    Returns:
        {template_name: {"args": [...], "prompt_preview": "..."}} 字典
    """
    templates = get_prompt_templates()
    result = {}
    for name, config in templates.items():
        args = config.get("args", [])
        prompt = config.get("prompt", "")
        # 截取前 50 个字符作为预览
        preview = prompt.strip()[:50] + "..." if len(prompt.strip()) > 50 else prompt.strip()
        result[name] = {
            "args": args,
            "prompt_preview": preview
        }
    return result

def set_database_path(path: str):
    """
    设置工作空间路径
    Args:
        path: 工作空间路径
    """
    global _workspace_path
    _workspace_path = path
    
    base_path = Path(_workspace_path).resolve()
    db_path = os.path.join(base_path, ".captain", "checkpoint.db")
    if not os.path.exists(db_path):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        with open(db_path, "w") as f:
            f.write("")
    global _captain_db_path
    _captain_db_path = db_path

    store_path = os.path.join(base_path, ".captain", "store.db")
    if not os.path.exists(store_path):
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        with open(store_path, "w") as f:
            f.write("")
    global _local_file_store_path
    _local_file_store_path = store_path

def get_database_path():
    """
    获取工作空间路径
    Returns:
        database_path: 数据库路径
    """
    return _captain_db_path

def get_local_file_store_path():
    """
    获取本地文件存储路径
    Returns:
        local_file_store_path: 本地文件存储路径
    """
    return _local_file_store_path

def get_workspace_path():
    """
    获取工作空间路径
    Returns:
        workspace_path: 工作空间路径
    """
    return _workspace_path

class Colors:
    """ANSI颜色代码"""
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def cprint(text: str, color: str = Colors.ENDC):
    """
    带颜色的打印函数
    Args:
        text: 要打印的文本
        color: 颜色代码 (从Colors类获取)
    """
    print(f"{color}{text}{Colors.ENDC}")