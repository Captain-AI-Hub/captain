"""流式输出处理器 - 管理 Agent 响应的 UI 渲染"""

import json
from collections import OrderedDict
from typing import Any, Callable
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.live import Live
from rich.text import Text
from rich import box


class StreamHandler:
    """处理 Agent 流式响应的 UI 渲染"""
    
    def __init__(self, console: Console, output_path: str, save_func: Callable):
        self.console = console
        self.output_path = output_path
        self.save_content = save_func
        
        # 状态管理
        self.tool_states: OrderedDict = OrderedDict()
        self.pending_results: dict = {}
        self.thinking_buffer: list = []
        self.answer_buffer: list = []
        self.current_state: str | None = None
        
        # Live 显示管理
        self.current_live: Live | None = None
        self.tools_live: Live | None = None
    
    def reset(self):
        """重置所有状态"""
        self.tool_states.clear()
        self.pending_results.clear()
        self.thinking_buffer.clear()
        self.answer_buffer.clear()
        self.current_state = None
        self._stop_current_live()
        self._stop_tools_live()
    
    # ==================== Live 管理 ====================
    
    def _update_live(self, renderable: Any, transient: bool = False):
        """更新主 Live 显示"""
        if self.current_live is None:
            self.current_live = Live(
                renderable,
                console=self.console,
                refresh_per_second=12,
                transient=transient
            )
            self.current_live.start()
        else:
            self.current_live.update(renderable)
    
    def _stop_current_live(self):
        """停止主 Live"""
        if self.current_live is not None:
            self.current_live.stop()
            self.current_live = None
    
    def _render_pending_tools(self) -> Group | None:
        """渲染 pending 状态的工具"""
        panels = []
        for tool_id, state in self.tool_states.items():
            if state["status"] == "pending":
                subagent = state.get("subagent")
                name_display = f"[{subagent}] {state['name']}" if subagent else state['name']
                panel = Panel(
                    Text.assemble(
                        ("🔧 ", "bold cyan"),
                        (f"{name_display}\n", "bold"),
                        ("Args: ", "dim"),
                        (state['args_str'], "cyan"),
                        ("\n\n", ""),
                        ("⏳ ", "yellow"),
                        ("Processing...", "yellow italic")
                    ),
                    title=f"[bold cyan]🔧 Tool Call: {name_display}[/bold cyan]",
                    border_style="cyan",
                    box=box.ROUNDED
                )
                panels.append(panel)
        return Group(*panels) if panels else None
    
    def _update_tools_live(self):
        """更新工具 Live 显示"""
        pending_content = self._render_pending_tools()
        
        if pending_content is None:
            self._stop_tools_live()
            return
        
        if self.tools_live is None:
            self.tools_live = Live(
                pending_content,
                console=self.console,
                refresh_per_second=12,
                transient=True
            )
            self.tools_live.start()
        else:
            self.tools_live.update(pending_content)
    
    def _stop_tools_live(self):
        """停止工具 Live"""
        if self.tools_live:
            self.tools_live.stop()
            self.tools_live = None
    
    # ==================== 状态切换辅助 ====================
    
    def _save_and_clear_buffers(self, think_type: str = "think", answer_type: str = "answer"):
        """保存并清空缓冲区"""
        if self.thinking_buffer:
            self.save_content(self.output_path, think_type, "".join(self.thinking_buffer))
            self.thinking_buffer.clear()
        if self.answer_buffer:
            self.save_content(self.output_path, answer_type, "".join(self.answer_buffer))
            self.answer_buffer.clear()
    
    def _transition_from_tool_state(self):
        """从工具状态切换时的处理"""
        if self.current_state in ("tool_call", "tool_result", "sub_agent_tool_call", "sub_agent_tool_result"):
            self._stop_tools_live()
    
    def _transition_from_content_state(self, target_state: str, think_type: str = "think", answer_type: str = "answer"):
        """从内容状态切换时的处理"""
        self._transition_from_tool_state()
        
        if self.current_state != target_state and self.current_live:
            self._save_and_clear_buffers(think_type, answer_type)
            self._stop_current_live()
    
    # ==================== 事件处理器 ====================
    
    def handle_model_thinking(self, content: str):
        """处理模型思考"""
        self._transition_from_content_state("model_thinking")
        self.current_state = "model_thinking"
        
        self.thinking_buffer.append(content)
        self._update_live(
            Panel(
                "".join(self.thinking_buffer),
                title="[bold yellow]🤔 Model Thinking[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED
            )
        )
    
    def handle_model_answer(self, content: str):
        """处理模型回答"""
        self._transition_from_content_state("model_answer")
        self.current_state = "model_answer"
        
        self.answer_buffer.append(content)
        answer_text = "".join(self.answer_buffer)
        
        try:
            md_content = Markdown(answer_text)
        except Exception:
            md_content = answer_text
        
        self._update_live(
            Panel(
                md_content,
                title="[bold green]💬 Model Answer[/bold green]",
                border_style="green",
                box=box.ROUNDED
            )
        )
    
    def handle_tool_call(self, content: str):
        """处理工具调用"""
        if self.current_state not in ("tool_call", "tool_result"):
            if self.current_live:
                self._save_and_clear_buffers()
                self._stop_current_live()
        self.current_state = "tool_call"
        
        try:
            tool_data = json.loads(content)
            tool_id = tool_data.get('id', '')
            tool_name = tool_data.get('name', '')
            tool_args = tool_data.get('args', {})
            
            try:
                args_str = json.dumps(tool_args, ensure_ascii=False, indent=2)
            except:
                args_str = str(tool_args)
            
            self.tool_states[tool_id] = {
                "name": tool_name,
                "args_str": args_str,
                "status": "pending",
                "result": None
            }
            
            if tool_id in self.pending_results:
                self.tool_states[tool_id]["status"] = "complete"
                self.tool_states[tool_id]["result"] = str(self.pending_results[tool_id])
                del self.pending_results[tool_id]
                self._stop_tools_live()
                self._print_tool_complete(self.tool_states[tool_id])
            else:
                self._update_tools_live()
        except json.JSONDecodeError:
            self.console.print(Panel(f"Error parsing tool call: {content}", style="red"))
    
    def handle_tool_result(self, content: str):
        """处理工具结果"""
        self.current_state = "tool_result"
        
        try:
            result_data = json.loads(content)
            tool_id = result_data.get('id', '')
            tool_result = result_data.get('content', content)
            
            if tool_id in self.tool_states:
                self.tool_states[tool_id]["status"] = "complete"
                self.tool_states[tool_id]["result"] = str(tool_result)
                self._stop_tools_live()
                self._print_tool_complete(self.tool_states[tool_id])
                self._update_tools_live()
            else:
                self.pending_results[tool_id] = tool_result
        except json.JSONDecodeError:
            self.console.print(Panel(f"Error parsing tool result: {content}", style="red"))
    
    def _print_tool_complete(self, state: dict):
        """打印工具完成结果"""
        result_str = state.get("result", "")
        if len(result_str) > 1000:
            result_str = result_str[:1000] + "\n... (truncated)"
        
        subagent = state.get("subagent")
        name_display = f"[{subagent}] {state['name']}" if subagent else state['name']
        title_prefix = f"{subagent}: " if subagent else ""
        
        self.console.print(
            Panel(
                Text.assemble(
                    ("🔧 ", "bold cyan"),
                    (f"{name_display}\n", "bold"),
                    ("Args: ", "dim"),
                    (state['args_str'], "cyan"),
                    ("\n\nResult:\n", "dim"),
                    (result_str, "green")
                ),
                title=f"[bold green]✅ {title_prefix}{state['name']} - Complete[/bold green]",
                border_style="green",
                box=box.ROUNDED
            )
        )
        self.save_content(self.output_path, "tool_call", {
            "name": state["name"],
            "args_str": state["args_str"]
        })
    
    # ==================== 子代理事件处理器 ====================
    
    def handle_sub_agent_start(self, response: dict):
        """处理子代理启动"""
        subagent_name = response.get("subagent", "general")
        task_desc = response.get("task", "")
        
        if self.current_state not in ("tool_call", "tool_result"):
            if self.current_live:
                self._save_and_clear_buffers()
                self._stop_current_live()
        
        self._stop_tools_live()
        self.current_state = "sub_agent"
        
        self.console.print(Panel(
            Text.assemble(
                ("🚀 Starting sub-agent: ", "bold"),
                (f"{subagent_name}\n", "bold cyan"),
                ("Task: ", "dim"),
                (task_desc[:200] + "..." if len(task_desc) > 200 else task_desc, "white"),
            ),
            title=f"[bold magenta]🤖 Sub Agent: {subagent_name}[/bold magenta]",
            border_style="magenta",
            box=box.ROUNDED
        ))
    
    def handle_sub_agent_end(self, content: str):
        """处理子代理完成"""
        if self.current_live:
            self._save_and_clear_buffers("sub_agent_think", "sub_agent_answer")
            self._stop_current_live()
        
        self._stop_tools_live()
        
        result_preview = content[:500] + "..." if len(content) > 500 else content
        try:
            md_content = Markdown(result_preview)
        except Exception:
            md_content = result_preview
        
        self.console.print(Panel(
            md_content,
            title="[bold green]✅ Sub Agent Complete[/bold green]",
            border_style="green",
            box=box.ROUNDED
        ))
        self.save_content(self.output_path, "sub_agent", content)
    
    def handle_sub_agent_thinking(self, content: str, subagent: str):
        """处理子代理思考"""
        self._transition_from_content_state("sub_agent_thinking", "sub_agent_think", "sub_agent_answer")
        self.current_state = "sub_agent_thinking"
        
        self.thinking_buffer.append(content)
        self._update_live(
            Panel(
                "".join(self.thinking_buffer),
                title=f"[bold yellow]🤔 {subagent} Thinking[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED
            )
        )
    
    def handle_sub_agent_answer(self, content: str, subagent: str):
        """处理子代理回答"""
        self._transition_from_content_state("sub_agent_answer", "sub_agent_think", "sub_agent_answer")
        self.current_state = "sub_agent_answer"
        
        self.answer_buffer.append(content)
        answer_text = "".join(self.answer_buffer)
        
        try:
            md_content = Markdown(answer_text)
        except Exception:
            md_content = answer_text
        
        self._update_live(
            Panel(
                md_content,
                title=f"[bold magenta]💬 {subagent} Answer[/bold magenta]",
                border_style="magenta",
                box=box.ROUNDED
            )
        )
    
    def handle_sub_agent_tool_call(self, content: str):
        """处理子代理工具调用"""
        if self.current_state not in ("tool_call", "tool_result", "sub_agent_tool_call", "sub_agent_tool_result"):
            if self.current_live:
                self._save_and_clear_buffers("sub_agent_think", "sub_agent_answer")
                self._stop_current_live()
        self.current_state = "sub_agent_tool_call"
        
        try:
            tool_data = json.loads(content)
            tool_id = tool_data.get('id', '')
            tool_name = tool_data.get('name', '')
            tool_args = tool_data.get('args', {})
            subagent_name = tool_data.get('subagent', 'SubAgent')
            
            try:
                args_str = json.dumps(tool_args, ensure_ascii=False, indent=2)
            except:
                args_str = str(tool_args)
            
            self.tool_states[tool_id] = {
                "name": tool_name,
                "args_str": args_str,
                "status": "pending",
                "result": None,
                "subagent": subagent_name
            }
            
            if tool_id in self.pending_results:
                self.tool_states[tool_id]["status"] = "complete"
                self.tool_states[tool_id]["result"] = str(self.pending_results[tool_id])
                del self.pending_results[tool_id]
                self._stop_tools_live()
                self._print_tool_complete(self.tool_states[tool_id])
            else:
                self._update_tools_live()
        except json.JSONDecodeError:
            self.console.print(Panel(f"Error parsing sub_agent tool call: {content}", style="red"))
    
    def handle_sub_agent_tool_result(self, content: str):
        """处理子代理工具结果"""
        self.current_state = "sub_agent_tool_result"
        
        try:
            result_data = json.loads(content)
            tool_id = result_data.get('id', '')
            tool_result = result_data.get('content', content)
            
            if tool_id in self.tool_states:
                self.tool_states[tool_id]["status"] = "complete"
                self.tool_states[tool_id]["result"] = str(tool_result)
                self._stop_tools_live()
                self._print_tool_complete(self.tool_states[tool_id])
                self._update_tools_live()
            else:
                self.pending_results[tool_id] = tool_result
        except json.JSONDecodeError:
            self.console.print(Panel(f"Error parsing sub_agent tool result: {content}", style="red"))
    
    def handle_error(self, content: str):
        """处理错误"""
        self._stop_tools_live()
        self._stop_current_live()
        self.console.print(Panel(
            content,
            title="[bold red]❌ Error from ChatStream[/bold red]",
            border_style="red",
            box=box.ROUNDED
        ))
    
    # ==================== 主处理入口 ====================
    
    def handle_response(self, response: dict | None):
        """处理单个响应"""
        if response is None:
            return
        
        response_type = response.get("type")
        if not response_type:
            return
            
        content = response.get("content", "")
        
        handlers = {
            "model_thinking": lambda: self.handle_model_thinking(content),
            "model_answer": lambda: self.handle_model_answer(content),
            "tool_call": lambda: self.handle_tool_call(content),
            "tool_result": lambda: self.handle_tool_result(content),
            "sub_agent_start": lambda: self.handle_sub_agent_start(response),
            "sub_agent_end": lambda: self.handle_sub_agent_end(content),
            "sub_agent_thinking": lambda: self.handle_sub_agent_thinking(
                content, str(response.get("subagent", "SubAgent"))
            ),
            "sub_agent_answer": lambda: self.handle_sub_agent_answer(
                content, str(response.get("subagent", "SubAgent"))
            ),
            "sub_agent_tool_call": lambda: self.handle_sub_agent_tool_call(content),
            "sub_agent_tool_result": lambda: self.handle_sub_agent_tool_result(content),
            "error": lambda: self.handle_error(content),
        }
        
        handler = handlers.get(response_type)
        if handler:
            handler()
    
    def finalize(self):
        """流结束时的清理"""
        self._stop_tools_live()
        self._stop_current_live()
        self._save_and_clear_buffers()

