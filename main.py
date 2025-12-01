from utils.utils import (
    set_toml_path, get_model_config, 
    set_database_path, get_database_path, 
    get_local_file_store_path, get_workspace_path,
    get_major_agent_config, get_sub_agents_config,
    get_prompt, list_prompt_templates
)

from utils.save_content import save_content

import argparse
from chat.chat import ChatStream, cleanup_resources
import asyncio
import sys
import json
import time
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.table import Table
from rich.text import Text
from rich import box
from rich.status import Status
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style
from utils.shell_prompt import CaptainShell, get_cached_system_commands
from collections import OrderedDict
from pathlib import Path
from utils.sys_shell import parse_shell_command, execute_shell_command

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

    # 全局 Live 显示控制
    current_live = None
    
    def update_live(renderable, transient=False):
        """统一更新 Live 显示"""
        nonlocal current_live
        
        if current_live is None:
            current_live = Live(
                renderable,
                console=console,
                refresh_per_second=12,
                transient=transient
            )
            current_live.start()
        else:
            current_live.update(renderable)

    def stop_current_live():
        """停止当前 Live"""
        nonlocal current_live
        if current_live is not None:
            current_live.stop()
            current_live = None
        
    try:
        while True:
            try:
                # 获取用户输入
                query_msg = await shell.prompt_async()
                query_msg = query_msg.strip()
                
                # 检查退出命令
                if query_msg.lower() in ["exit", "quit", "q"]:
                    console.print("[bold green]👋 Goodbye![/bold green]")
                    break
                
                # 忽略空输入
                if not query_msg:
                    continue
                
                # 检查是否是 shell 命令
                is_shell, shell_command = parse_shell_command(query_msg)
                if is_shell:
                    if shell_command:
                        console.print()
                        result = execute_shell_command(shell_command)
                        if result["success"]:
                            console.print(Panel(
                                result["output"],
                                title=f"[bold cyan]🖥️  Shell: {result['command']}[/bold cyan]",
                                border_style="cyan",
                                box=box.SIMPLE
                            ))
                        else:
                            console.print(Panel(
                                result["output"],
                                title=f"[bold red]❌ Shell: {result['command']}[/bold red]",
                                border_style="red",
                                box=box.SIMPLE
                            ))
                    else:
                        console.print("[bold yellow]⚠️  Please provide a command after 'shell'[/bold yellow]")
                    continue
                
                # 检查是否是 prompt 模板命令
                if query_msg.startswith("/"):
                    prompt_cmd = query_msg[1:].strip()  # 去掉 "/" 前缀
                    
                    # /list 列出所有模板
                    if prompt_cmd == "list":
                        console.print()
                        templates = list_prompt_templates()
                        if templates:
                            table = Table(title="Prompt Templates", box=box.SIMPLE)
                            table.add_column("Name", style="cyan")
                            table.add_column("Args", style="yellow")
                            table.add_column("Preview", style="dim")
                            for name, info in templates.items():
                                args_str = ", ".join(info["args"]) if info["args"] else "-"
                                table.add_row(name, args_str, info["prompt_preview"])
                            console.print(table)
                        else:
                            console.print("[bold yellow]⚠️  No prompt templates found[/bold yellow]")
                        continue
                    
                    # 解析 prompt 模板
                    result = get_prompt(prompt_cmd)
                    if result is None:
                        console.print(f"[bold yellow]⚠️  Unknown template: {prompt_cmd.split()[0]}[/bold yellow]")
                        console.print("[dim]Use /list to see available templates[/dim]")
                        continue
                    elif result.startswith("Error:"):
                        console.print(f"[bold red]❌ {result}[/bold red]")
                        continue
                    
                    # 将解析后的 prompt 作为查询消息
                    query_msg = result
                    console.print(Panel(
                        query_msg,
                        title=f"[bold magenta]📝 Prompt: {prompt_cmd.split()[0]}[/bold magenta]",
                        border_style="magenta",
                        box=box.SIMPLE
                    ))

                console.print()
                
                # 状态管理
                tool_states = OrderedDict()
                pending_results = {}  # {tool_id: result} - 结果先于 tool_call 到达时缓存
                thinking_buffer = []
                answer_buffer = []
                current_state = None
                tools_live = None  # 专门用于工具显示的 Live
                
                def render_pending_tools():
                    """只渲染 pending 状态的工具"""
                    panels = []
                    for tool_id, state in tool_states.items():
                        if state["status"] == "pending":
                            panel = Panel(
                                Text.assemble(
                                    ("🔧 ", "bold cyan"),
                                    (f"{state['name']}\n", "bold"),
                                    ("Args: ", "dim"),
                                    (state['args_str'], "cyan"),
                                    ("\n\n", ""),
                                    ("⏳ ", "yellow"),
                                    ("Processing...", "yellow italic")
                                ),
                                title=f"[bold cyan]🔧 Tool Call: {state['name']}[/bold cyan]",
                                border_style="cyan",
                                box=box.ROUNDED
                            )
                            panels.append(panel)
                    return Group(*panels) if panels else None
                
                def update_tools_live():
                    """更新工具 Live 显示（只显示 pending 的工具）"""
                    nonlocal tools_live
                    pending_content = render_pending_tools()
                    
                    if pending_content is None:
                        # 没有 pending 工具了，停止 Live
                        if tools_live:
                            tools_live.stop()
                            tools_live = None
                        return
                    
                    if tools_live is None:
                        tools_live = Live(
                            pending_content,
                            console=console,
                            refresh_per_second=12,
                            transient=True  # Processing 状态会消失
                        )
                        tools_live.start()
                    else:
                        tools_live.update(pending_content)
                
                def print_tool_complete(state):
                    """打印单个工具的完成结果（永久显示）"""
                    result_str = state.get("result", "")
                    if len(result_str) > 1000:
                        result_str = result_str[:1000] + "\n... (truncated)"
                    console.print(
                        Panel(
                            Text.assemble(
                                ("🔧 ", "bold cyan"),
                                (f"{state['name']}\n", "bold"),
                                ("Args: ", "dim"),
                                (state['args_str'], "cyan"),
                                ("\n\nResult:\n", "dim"),
                                (result_str, "green")
                            ),
                            title=f"[bold green]✅ {state['name']} - Complete[/bold green]",
                            border_style="green",
                            box=box.ROUNDED
                        )
                    )
                    # 保存工具调用
                    save_content(args.output, "tool_call", {
                        "name": state["name"],
                        "args_str": state["args_str"]
                    })
                
                def stop_tools_live():
                    """停止工具 Live"""
                    nonlocal tools_live
                    if tools_live:
                        tools_live.stop()
                        tools_live = None

                # 流式处理响应
                async for response in ChatStream( # type: ignore
                    model_name=major_agent_config["model_name"],
                    base_url=major_agent_config["base_url"],
                    api_key=major_agent_config["api_key"],
                    system_prompt=major_agent_config.get("system_prompt", ""),
                    human_message=query_msg,
                ):
                    # 跳过 None 响应
                    if response is None:
                        continue
                                                   
                    response_type = response.get("type")
                    content = response.get("content", "")
                    
                    if response_type == "model_thinking":
                        # 从工具状态切换过来时，停止工具 Live
                        if current_state in ("tool_call", "tool_result"):
                            stop_tools_live()
                        
                        # 只有从其他状态切换过来时才停止 Live 并保存之前的内容
                        if current_state != "model_thinking" and current_live:
                            # 保存之前的 answer 内容（如果有）
                            if answer_buffer:
                                save_content(args.output, "answer", "".join(answer_buffer))
                            answer_buffer = []
                            stop_current_live()
                        current_state = "model_thinking"

                        thinking_buffer.append(content)
                        thinking_text = "".join(thinking_buffer)
                        
                        update_live(
                            Panel(
                                thinking_text,
                                title="[bold yellow]🤔 Model Thinking[/bold yellow]",
                                border_style="yellow",
                                box=box.ROUNDED
                            ),
                            transient=False
                        )
                    elif response_type == "model_answer":
                        # 从工具状态切换过来时，停止工具 Live
                        if current_state in ("tool_call", "tool_result"):
                            stop_tools_live()
                        
                        # 只有从其他状态切换过来时才停止 Live 并保存之前的内容
                        if current_state != "model_answer" and current_live:
                            # 保存之前的 thinking 内容（如果有）
                            if thinking_buffer:
                                save_content(args.output, "think", "".join(thinking_buffer))
                            thinking_buffer = []
                            stop_current_live()
                        current_state = "model_answer"
                        
                        answer_buffer.append(content)
                        answer_text = "".join(answer_buffer)
                        
                        try:
                            md_content = Markdown(answer_text)
                        except Exception:
                            md_content = answer_text
                        
                        update_live(
                            Panel(
                                md_content,
                                title="[bold green]💬 Model Answer[/bold green]",
                                border_style="green",
                                box=box.ROUNDED
                            ),
                            transient=False
                        )
                    elif response_type == "tool_call":
                        # 从非工具状态切换过来时，保存之前的内容
                        if current_state not in ("tool_call", "tool_result"):
                            if current_live:
                                if thinking_buffer:
                                    save_content(args.output, "think", "".join(thinking_buffer))
                                if answer_buffer:
                                    save_content(args.output, "answer", "".join(answer_buffer))
                                thinking_buffer = []
                                answer_buffer = []
                                stop_current_live()
                        current_state = "tool_call"
                        
                        try:
                            tool_data = json.loads(content)
                            tool_id = tool_data.get('id', '')
                            tool_name = tool_data.get('name', '')
                            tool_args = tool_data.get('args', {})
                            
                            try:
                                args_str = json.dumps(tool_args, ensure_ascii=False, indent=2)
                            except:
                                args_str = str(tool_args)
                            
                            # 添加到工具状态
                            tool_states[tool_id] = {
                                "name": tool_name,
                                "args_str": args_str,
                                "status": "pending",
                                "result": None
                            }
                            
                            # 检查是否有缓存的结果（结果先于 tool_call 到达）
                            if tool_id in pending_results:
                                tool_states[tool_id]["status"] = "complete"
                                tool_states[tool_id]["result"] = str(pending_results[tool_id])
                                del pending_results[tool_id]
                                # 停止 Live，打印完成结果
                                stop_tools_live()
                                print_tool_complete(tool_states[tool_id])
                            else:
                                # 更新 Live 显示 Processing
                                update_tools_live()

                        except json.JSONDecodeError:
                            console.print(Panel(f"Error parsing tool call: {content}", style="red"))
                        
                    elif response_type == "tool_result":
                        current_state = "tool_result"
                        try:
                            result_data = json.loads(content)
                            tool_id = result_data.get('id', '')
                            tool_result = result_data.get('content', content)
                            
                            if tool_id in tool_states:
                                # 更新工具状态为完成
                                tool_states[tool_id]["status"] = "complete"
                                tool_states[tool_id]["result"] = str(tool_result)
                                
                                # 停止 Live，打印完成结果，然后更新 Live 显示剩余 pending 工具
                                stop_tools_live()
                                print_tool_complete(tool_states[tool_id])
                                # 如果还有其他 pending 工具，重新显示
                                update_tools_live()
                            else:
                                # 结果先于 tool_call 到达，缓存起来
                                pending_results[tool_id] = tool_result
                                
                        except json.JSONDecodeError:
                            console.print(Panel(f"Error parsing tool result: {content}", style="red"))

                    elif response_type == "sub_agent":
                        # 从其他状态切换过来时，停止之前的 Live
                        if current_state not in ("tool_call", "tool_result"):
                            if current_live:
                                if thinking_buffer:
                                    save_content(args.output, "think", "".join(thinking_buffer))
                                if answer_buffer:
                                    save_content(args.output, "answer", "".join(answer_buffer))
                                thinking_buffer = []
                                answer_buffer = []
                                stop_current_live()
                        
                        stop_tools_live()

                        try:
                            md_content = Markdown(content)
                        except Exception:
                            md_content = content
                        
                        console.print(Panel(
                            md_content,
                            title="[bold magenta]🤖 Sub Agent Output[/bold magenta]",
                            border_style="magenta",
                            box=box.ROUNDED
                        ))
                        # 保存子代理输出
                        save_content(args.output, "sub_agent", content)

                    elif response_type == "error":
                        # 停止工具 Live
                        stop_tools_live()
                        stop_current_live()
                        console.print(Panel(
                            content,
                            title="[bold red]❌ Error from ChatStream [/bold red]",
                            border_style="red",
                            box=box.ROUNDED
                        ))
                
                # 流结束时处理
                stop_tools_live()
                
                stop_current_live()
                
                # 流结束时保存最后的内容
                if thinking_buffer:
                    save_content(args.output, "think", "".join(thinking_buffer))
                if answer_buffer:
                    save_content(args.output, "answer", "".join(answer_buffer))
                
                # 清理状态
                pending_results.clear()
                thinking_buffer.clear()
                answer_buffer.clear()
                current_state = None
                
            except KeyboardInterrupt:
                stop_current_live()
                
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