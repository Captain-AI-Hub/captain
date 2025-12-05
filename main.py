from utils.utils import (
    set_toml_path, get_model_config, 
    set_database_path, get_database_path, 
    get_local_file_store_path, get_workspace_path,
    get_major_agent_config, get_sub_agents_config,
)

from utils.save_content import save_content
from utils.command_parser import parse_command, CommandType, ResultStyle
from utils.stream_handler import StreamHandler

import argparse
from chat.chat import ChatStream, cleanup_resources
import asyncio
import sys
import time
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.status import Status
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style
from utils.shell_prompt import CaptainShell, get_cached_system_commands
from pathlib import Path

# import ssl
# import urllib3

# # Disable SSL verification warnings
# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# # Create an unverified SSL context and set it as default
# ssl._create_default_https_context = ssl._create_unverified_context

# # Also patch requests.Session to use verify=False by default
# import requests
# from functools import wraps

# _original_session_request = requests.Session.request

# @wraps(_original_session_request)
# def _patched_session_request(self, method, url, **kwargs):  # type: ignore[misc]
#     kwargs.setdefault('verify', False)
#     return _original_session_request(self, method, url, **kwargs)

# requests.Session.request = _patched_session_request  # type: ignore[method-assign]

async def main():
    """主程序入口"""
    
    parser = argparse.ArgumentParser(description="Captain Cmd Tools")
    parser.add_argument(
        "--config", 
        type=str, 
        default="config.toml", 
        required=False, 
        help="Path to config file"
    )
    parser.add_argument(
        "--workspace", 
        type=str, 
        default=".", 
        required=False, 
        help="Path to workspace directory"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output.md",
        required=False,
        help="Path to save output"
    )
    args = parser.parse_args()

    # 创建 Rich Console
    console = Console()

    # 初始化加载
    with Status("[bold cyan]Initializing Captain...", console=console, spinner="dots") as status:
        # 预加载系统命令缓存
        status.update("[bold cyan]Loading system commands...")
        get_cached_system_commands()
        
        # 初始化配置
        status.update("[bold cyan]Loading configuration...")
        set_toml_path(args.config)
        config = get_model_config()
        
        if config == "Error: toml_path is None":
            console.print(f"[bold red]❌ Failed to load model config: {config}[/bold red]")
            sys.exit(1)
        
        # 获取 major agent 配置
        major_agent_config = get_major_agent_config()
        if major_agent_config is None:
            console.print("[bold red]❌ Failed to load major agent config[/bold red]")
            sys.exit(1)
        
        # 初始化数据库路径
        status.update("[bold cyan]Setting up workspace...")
        set_database_path(args.workspace)
        
        # 创建 Captain Shell
        status.update("[bold cyan]Preparing shell...")
        
    # 创建 Captain Shell (带历史记录和补全)
    shell = CaptainShell()

    # 显示欢迎信息
    console.print("\n[bold cyan]🚀 Welcome to Captain Cmd Tools[/bold cyan]")
    
    # 创建配置信息表格
    config_table = Table(show_header=False, box=box.SIMPLE)
    config_table.add_column("Key", style="cyan")
    config_table.add_column("Value", style="green")
    
    config_table.add_row("Major Model", major_agent_config['model_name'])
    
    config_table.add_row("Sub Agents", "")
    sub_agents_config = get_sub_agents_config()
    for sub_agent_name, sub_agent_cfg in sub_agents_config.items():
        config_table.add_row(f" -> {sub_agent_name}", sub_agent_cfg.get("model_name", ""))

    config_table.add_row("Workspace", str(Path(get_workspace_path()).resolve()))
    config_table.add_row("CheckpointDB", get_database_path())
    config_table.add_row("StoreDB", get_local_file_store_path())
    
    console.print(config_table)
    console.print("\n[dim]Type 'exit' or 'quit' to exit[/dim]\n")
        
    try:
        while True:
            try:
                # 获取用户输入
                query_msg = await shell.prompt_async()
                
                # 统一命令解析
                cmd_result = parse_command(query_msg)
                
                # 退出命令
                if cmd_result.cmd_type == CommandType.EXIT:
                    console.print(f"[bold green]{cmd_result.title}[/bold green]")
                    break
                
                # 空输入
                if cmd_result.cmd_type == CommandType.EMPTY:
                    continue
                
                # 需要显示结果的内置命令
                if cmd_result.cmd_type in (CommandType.SHELL, CommandType.VECTOR, CommandType.PROMPT_LIST):
                    console.print()
                    style_map = {
                        ResultStyle.SUCCESS: ("bold green", "green"),
                        ResultStyle.ERROR: ("bold red", "red"),
                        ResultStyle.WARNING: ("bold yellow", "yellow"),
                        ResultStyle.INFO: ("bold cyan", "cyan"),
                    }
                    title_style, border_style = style_map.get(cmd_result.style, ("bold", "white"))
                    console.print(Panel(
                        cmd_result.output,
                        title=f"[{title_style}]{cmd_result.title}[/{title_style}]",
                        border_style=border_style,
                        box=box.SIMPLE
                    ))
                    continue
                
                # Prompt 模板命令（需要传递给 agent）
                if cmd_result.cmd_type == CommandType.PROMPT:
                    if not cmd_result.success:
                        console.print()
                        style_map = {
                            ResultStyle.WARNING: ("bold yellow", "yellow"),
                            ResultStyle.ERROR: ("bold red", "red"),
                        }
                        title_style, border_style = style_map.get(cmd_result.style, ("bold yellow", "yellow"))
                        console.print(Panel(
                            cmd_result.output,
                            title=f"[{title_style}]{cmd_result.title}[/{title_style}]",
                            border_style=border_style,
                            box=box.SIMPLE
                        ))
                        continue
                    
                    # 成功解析的 prompt，显示后传递给 agent
                    query_msg = cmd_result.passthrough_msg
                    console.print(Panel(
                        cmd_result.output,
                        title=f"[bold magenta]{cmd_result.title}[/bold magenta]",
                        border_style="magenta",
                        box=box.SIMPLE
                    ))
                
                # RAG 命令（检索后传递给 agent）
                elif cmd_result.cmd_type == CommandType.VECTOR_RAG:
                    console.print()
                    if not cmd_result.success:
                        console.print(Panel(
                            cmd_result.output,
                            title=f"[bold red]{cmd_result.title}[/bold red]",
                            border_style="red",
                            box=box.SIMPLE
                        ))
                        continue
                    
                    # 显示检索到的上下文，然后传递增强提示词给 agent
                    query_msg = cmd_result.passthrough_msg
                    console.print(Panel(
                        cmd_result.output,
                        title=f"[bold cyan]{cmd_result.title}[/bold cyan]",
                        border_style="cyan",
                        box=box.SIMPLE
                    ))
                
                # PASSTHROUGH: 直接传递给 agent
                elif cmd_result.cmd_type == CommandType.PASSTHROUGH:
                    query_msg = cmd_result.passthrough_msg
                
                # 确保 query_msg 有效
                if not query_msg:
                    continue

                console.print()
                
                # 使用 StreamHandler 处理流式响应
                stream_handler = StreamHandler(console, args.output, save_content)
                
                # 流式处理响应
                async for response in ChatStream( # type: ignore
                    model_name=major_agent_config["model_name"],
                    base_url=major_agent_config["base_url"],
                    api_key=major_agent_config["api_key"],
                    system_prompt=major_agent_config.get("system_prompt", ""),
                    human_message=query_msg,
                ):
                    stream_handler.handle_response(response)
                
                # 流结束时清理
                stream_handler.finalize()
                
            except KeyboardInterrupt:
                if 'stream_handler' in locals():
                    stream_handler.finalize()
                
                console.print("\n\n[bold yellow]⚠️  Interrupted by user (Press Ctrl+C again to exit)[/bold yellow]")
                # 询问是否真的要退出
                try:
                    confirm = await shell.session.prompt_async(
                        FormattedText([('class:prompt', 'Do you want to exit? (y/n): ')]),
                        style=Style.from_dict({"prompt": "yellow"})
                    )
                    if confirm.strip().lower() in ["y", "yes"]:
                        console.print("[bold green]👋 Goodbye![/bold green]")
                        break
                except (KeyboardInterrupt, EOFError):
                    # 第二次 Ctrl+C 直接退出
                    console.print("\n[bold green]👋 Goodbye![/bold green]")
                    break
            except EOFError:
                # 处理 EOF（比如在某些终端中按 Ctrl+D）
                console.print("\n[bold green]👋 Goodbye![/bold green]")
                break
            except Exception as e:
                console.print(Panel(
                    f"{e}",
                    title="[bold red]❌ Error processing request[/bold red]",
                    border_style="red",
                    box=box.ROUNDED
                ))
                import traceback
                console.print(traceback.format_exc())
                continue
    
    except KeyboardInterrupt:
        console.print("\n\n[bold green]👋 Goodbye![/bold green]")
    except Exception as e:
        console.print(Panel(
            f"{e}",
            title="[bold red]❌ Fatal error[/bold red]",
            border_style="red",
            box=box.ROUNDED
        ))
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)
    finally:
        # 清理资源
        await cleanup_resources()

if __name__ == "__main__":
    console = Console()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("\n[bold green]👋 Goodbye![/bold green]")
    except Exception as e:
        console.print(Panel(
            f"{e}",
            title="[bold red]❌ Fatal error[/bold red]",
            border_style="red",
            box=box.ROUNDED
        ))
        import traceback
        console.print(traceback.format_exc())
    finally:
        time.sleep(0.1)