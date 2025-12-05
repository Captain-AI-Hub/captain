from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from agent.agent import build_sub_agent
from tools.shell_exec import shell_exec
from tools.web_search import internet_search
import json
from typing import Optional, Any, AsyncGenerator, cast
from langchain_core.messages import HumanMessage
from pathlib import Path
from utils.utils import (
    cprint, Colors,
    get_database_path, get_local_file_store_path,
    get_major_config, get_sub_agents_config,
    get_workspace_path
)
from tools.utils import ErrorHandlingMiddleware
from tools.vlm_tools import read_image
from langchain.agents.middleware import (
    TodoListMiddleware,
)

from deepagents.middleware import (
    FilesystemMiddleware,
    SubAgentMiddleware,
    CompiledSubAgent
)

from deepagents.backends import (
    FilesystemBackend
)

from langchain_google_genai.chat_models import ChatGoogleGenerativeAI

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
import aiosqlite

from tools.mod_vector import store_markdown, search_vectors, list_collections

_store = None
_checkpoint = None
_major_agent = None

async def init_resources():
    """初始化数据库连接"""
    global _store, _checkpoint
    
    try:
        # 创建异步连接
        store_conn = await aiosqlite.connect(get_local_file_store_path())
        checkpoint_conn = await aiosqlite.connect(get_database_path())
        
        # 创建存储对象
        _store = AsyncSqliteStore(conn=store_conn)
        _checkpoint = AsyncSqliteSaver(conn=checkpoint_conn)
        
        # 初始化数据库模式
        await _store.setup()
        await _checkpoint.setup()
        return True
    except Exception as e:
        cprint(f"[init_resources] Failed to initialize resources: {e}", Colors.FAIL)
        return False

async def build_agent(
    model_name: str,
    base_url: str,
    api_key: str,
    system_prompt: str,
) -> Optional[Any]:
    """构建 deep agent"""
    
    global _store, _checkpoint, _major_agent, _llm_tool_selector_model, _summarization_model
    
    # 获取 sub agents 配置 (新的 TOML 格式)
    sub_agents_config = get_sub_agents_config()
       
    sub_agent = []
    for sub_agent_name, sub_agent_config in sub_agents_config.items():
        try:
            sub_model_name = sub_agent_config["model_name"]
            sub_base_url = sub_agent_config["base_url"]
            sub_api_key = sub_agent_config["api_key"]
            sub_system_prompt = sub_agent_config.get("system_prompt", "")
            mcp_tools = sub_agent_config.get("mcp_tools", [])
            inside_tools = sub_agent_config.get("inside_tools", [])
            # 支持从子代理配置中读取超时设置，默认 10 分钟
            sub_timeout = sub_agent_config.get("timeout", 600)
            sub_max_retries = sub_agent_config.get("max_retries", 3)
        except Exception as e:
            cprint(
                f"[build_agent] Sub agent '{sub_agent_name}' config error: {e}", 
                Colors.FAIL
            )
            continue

        agent = await build_sub_agent(
            model_name=sub_model_name,
            base_url=sub_base_url,
            api_key=sub_api_key,
            system_prompt=sub_system_prompt,
            mcp_tools=mcp_tools,
            inside_tools=inside_tools,
            timeout=sub_timeout,
            max_retries=sub_max_retries,
        )
        if agent is not None:
            sub_agent.append(
                CompiledSubAgent(
                    name=sub_agent_name,
                    description=sub_agent_config.get("description", ""),
                    runnable=agent
                )
            )
        else:
            cprint(
                f"[build_agent] Sub agent '{sub_agent_name}' build failed", 
                Colors.FAIL
            )

    try:
        # 初始化模型
        # 设置较长的超时时间以支持子代理长时间执行
        # 默认 10 分钟超时，可在配置中覆盖
        from utils.utils import get_major_agent_config as get_config
        agent_config = get_config() or {}
        timeout = agent_config.get("timeout", 600)  # 默认 10 分钟
        max_retries = agent_config.get("max_retries", 3)  # 默认重试 3 次
        
        model = None
        if model_name.startswith("gemini"):
            model = ChatGoogleGenerativeAI(
                model=model_name,
                base_url=base_url,
                api_key=api_key,
                transport= "rest" if base_url!="https://generativelanguage.googleapis.com" else None,
                timeout=timeout,
            )
        else:
            model = init_chat_model(
                model=model_name,
                base_url=base_url,
                api_key=api_key,
                timeout=timeout,
                max_retries=max_retries,
            )

        # 确保资源已初始化
        if _store is None or _checkpoint is None:
            if not await init_resources():
                raise RuntimeError("Failed to initialize database resources")
        
        # 创建代理
        agent = create_agent(
            model=model,
            tools=[shell_exec, internet_search, read_image, search_vectors, list_collections],
            store=_store,
            checkpointer=_checkpoint,
            system_prompt=system_prompt,
            middleware=[
                TodoListMiddleware(),
                FilesystemMiddleware(
                    backend=FilesystemBackend(
                        root_dir=Path(get_workspace_path()).resolve(), 
                        virtual_mode=True
                    )
                ),
                SubAgentMiddleware(
                    default_model=model,
                    default_tools=[],
                    subagents=sub_agent,
                ),
                ErrorHandlingMiddleware(),
            ]
        )

        _major_agent = agent
        return agent
        
    except Exception as e:
        cprint(f"[build_agent] Error creating agent: {e}", Colors.FAIL)
        import traceback
        cprint(traceback.format_exc(), Colors.FAIL)
        return None

async def process_agent(agent: Any, message: str):
    """处理代理流式输出"""
    try:
        messages = [HumanMessage(content=message)]
        config = get_major_config()
        async for raw_data in agent.astream(
            {"messages": messages},
            stream_mode=["updates", "messages"],
            subgraphs=True,  # 启用子图流式输出以获取 sub_agent 的详细信息
            config=config
        ):
            try:
                # subgraphs=True 时返回格式: (namespace, stream_mode, chunk)
                # namespace: tuple，空 tuple () 表示主代理，非空表示子图路径
                # stream_mode: str，如 "messages" 或 "updates"
                # chunk: 对应 stream_mode 的数据
                if not isinstance(raw_data, tuple) or len(raw_data) != 3:
                    continue
                
                namespace, stream_mode, chunk = raw_data
                
                # 判断是否来自子代理 (namespace 非空表示来自子图)
                is_subagent = len(namespace) > 0 if namespace else False
                subagent_name = str(namespace[0]).split(":")[0] if is_subagent and namespace else None
                
                # ============ messages 模式：流式 token ============
                if stream_mode == "messages":
                    token, metadata = chunk
                    
                    if metadata is None or token is None:
                        continue
                    
                    node_name = metadata.get("langgraph_node", "")
                    
                    # 检查 token 是否有 content_blocks
                    if not hasattr(token, 'content_blocks') or not token.content_blocks:
                        continue
                    
                    for block in token.content_blocks:
                        # 模型的文本输出
                        if block.get("type") == "text" and node_name == "model":
                            if is_subagent:
                                # 子代理的模型回答
                                yield {
                                    "type": "sub_agent_answer",
                                    "content": block.get('text', ''),
                                    "subagent": subagent_name,
                                }
                            else:
                                yield {
                                    "type": "model_answer",
                                    "content": block.get('text', ''),
                                }
                        # 模型的思考过程
                        elif block.get("type") == "reasoning":
                            if is_subagent:
                                # 子代理的思考过程
                                yield {
                                    "type": "sub_agent_thinking",
                                    "content": block.get('reasoning', ''),
                                    "subagent": subagent_name,
                                }
                            else:
                                yield {
                                    "type": "model_thinking",
                                    "content": block.get('reasoning', ''),
                                }
                
                # ============ updates 模式：状态更新 ============
                elif stream_mode == "updates":
                    if chunk is None:
                        continue
                    
                    # chunk 是 dict: {node_name: {state_updates}}
                    for node_name, node_data in chunk.items():
                        if node_data is None:
                            continue
                        
                        # 获取 messages 列表
                        messages_list = node_data.get("messages", [])
                        
                        for msg in messages_list:
                            # ---- 处理工具调用 ----
                            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                                for tc in msg.tool_calls:
                                    tool_name = tc.get('name') or tc['name']
                                    
                                    if is_subagent:
                                        # 子代理的工具调用
                                        yield {
                                            "type": "sub_agent_tool_call",
                                            "name": tool_name,
                                            "args": tc.get('args', {}),
                                            "id": tc.get('id'),
                                            "subagent": subagent_name,
                                        }
                                    elif tool_name == "task":
                                        # 主代理调用 task 工具 -> 启动子代理
                                        # 产出特殊事件，不当作普通工具处理
                                        task_args = tc.get('args', {})
                                        yield {
                                            "type": "sub_agent_start",
                                            "subagent": task_args.get('agent', 'general'),
                                            "task": task_args.get('task', ''),
                                            "id": tc.get('id')
                                        }
                                    else:
                                        # 普通工具调用
                                        yield {
                                            "type": "tool_call",
                                            "name": tool_name,
                                            "args": tc.get('args', {}),
                                            "id": tc.get('id')
                                        }
                            
                            # ---- 处理工具结果 ----
                            if msg.__class__.__name__ == "ToolMessage":
                                tool_name = getattr(msg, 'name', '')
                                
                                if is_subagent:
                                    # 子代理的工具结果
                                    yield {
                                        "type": "sub_agent_tool_result",
                                        "content": msg.content,
                                        "id": msg.tool_call_id,
                                        "subagent": subagent_name,
                                    }
                                elif tool_name == "task":
                                    # task 工具完成 = 子代理完成
                                    # 产出子代理完成事件（包含最终结果摘要）
                                    yield {
                                        "type": "sub_agent_end",
                                        "content": msg.content,
                                        "id": msg.tool_call_id,
                                    }
                                else:
                                    # 普通工具结果
                                    yield {
                                        "type": "tool_result",
                                        "content": msg.content,
                                        "id": msg.tool_call_id,
                                    }
                                    
                                    # ---- 处理 read_image 工具返回的图片内容 ----
                                    if tool_name == "read_image":
                                        try:
                                            # 工具返回的是带有 __vlm_image__ 标记的 JSON
                                            content = msg.content
                                            image_content = None
                                            
                                            # 解析 JSON 格式的工具返回值
                                            if isinstance(content, str):
                                                try:
                                                    parsed = json.loads(content)
                                                    # 检查是否有 __vlm_image__ 标记
                                                    if isinstance(parsed, dict) and parsed.get('__vlm_image__'):
                                                        image_content = parsed.get('content')
                                                except json.JSONDecodeError:
                                                    pass
                                            elif isinstance(content, dict) and content.get('__vlm_image__'):
                                                image_content = content.get('content')
                                            
                                            # 如果成功解析到图片内容，注入 HumanMessage
                                            if image_content:
                                                image_message = HumanMessage(content=image_content)
                                                await agent.aupdate_state(
                                                    config=config,
                                                    values={"messages": [image_message]}
                                                )

                                        except Exception as e:
                                            yield {
                                                "type": "error",
                                                "content": f"Failed to inject image message: {e}"
                                            }
 
            except Exception as e:
                import traceback
                yield {
                    "type": "error",
                    "content": f'[process_agent] Inner exception: {e}\n[process_agent] Traceback:\n{traceback.format_exc()}',
                }
    
    except Exception as e:
        import traceback
        yield {
            "type": "error",
            "content": f'[process_agent] Error: {e}\n[process_agent] Traceback: {traceback.format_exc()}',
        }

async def ChatStream(
    model_name: str,
    base_url: str,
    api_key: str,
    system_prompt: str = "you are a helpful assistant", 
    human_message: str = "", 
):
    """chat stream"""
    
    try:
        # 验证输入
        if not model_name or not base_url or not api_key or not human_message:
            yield {
                "type": "error", 
                "content": "Invalid request: missing required fields"
            }
            return    
        # 初始化资源
        global _store, _checkpoint, _major_agent
        if _store is None or _checkpoint is None:
            if not await init_resources():
                yield {
                    "type": "error", 
                    "content": "Failed to initialize database"
                }
                return
        
        agent = None

        if _major_agent is not None:
            agent = _major_agent
        else:
            agent = await build_agent(
                model_name, 
                base_url, 
                api_key, 
                system_prompt          
            )
        
        if not agent:
            yield {
                "type": "error", 
                "content": "Failed to build agent"
            }
            return
        
        # 处理代理流
        async for message in process_agent(agent, human_message):
            if message["type"] == "model_answer":
                yield {
                    "type": "model_answer",
                    "content": message["content"]
                }
            elif message["type"] == "model_thinking":
                yield {
                    "type": "model_thinking",
                    "content": message["content"]
                }
            elif message["type"] == "tool_call":
                yield {
                    "type": "tool_call",
                    "content": json.dumps({
                        "name": message["name"],
                        "args": message["args"],
                        "id": message["id"]
                    }, ensure_ascii=False)
                }
            elif message["type"] == "tool_result":
                yield {
                    "type": "tool_result",
                    "content": json.dumps({
                        "content": message["content"],
                        "id": message["id"]
                    }, ensure_ascii=False)
                }
            # ---- 子代理生命周期事件 ----
            elif message["type"] == "sub_agent_start":
                yield {
                    "type": "sub_agent_start",
                    "subagent": message.get("subagent"),
                    "task": message.get("task"),
                    "id": message.get("id")
                }
            elif message["type"] == "sub_agent_end":
                yield {
                    "type": "sub_agent_end",
                    "content": message["content"],
                    "id": message.get("id")
                }
            # ---- 子代理流式输出 ----
            elif message["type"] == "sub_agent_answer":
                yield {
                    "type": "sub_agent_answer",
                    "content": message["content"],
                    "subagent": message.get("subagent")
                }
            elif message["type"] == "sub_agent_thinking":
                yield {
                    "type": "sub_agent_thinking",
                    "content": message["content"],
                    "subagent": message.get("subagent")
                }
            elif message["type"] == "sub_agent_tool_call":
                yield {
                    "type": "sub_agent_tool_call",
                    "content": json.dumps({
                        "name": message["name"],
                        "args": message["args"],
                        "id": message["id"],
                        "subagent": message.get("subagent")
                    }, ensure_ascii=False)
                }
            elif message["type"] == "sub_agent_tool_result":
                yield {
                    "type": "sub_agent_tool_result",
                    "content": json.dumps({
                        "content": message["content"],
                        "id": message["id"],
                        "subagent": message.get("subagent")
                    }, ensure_ascii=False)
                }
            elif message["type"] == "error":
                yield {
                    "type": "error",
                    "content": message["content"]
                }
                
    except Exception as e:
        import traceback
        yield {
            "type": "error", 
            "content": f'[ChatStream] Error: {e}\n[ChatStream] Traceback:\n{traceback.format_exc()}',
        }

async def cleanup_resources():
    """清理数据库资源"""
    global _store, _checkpoint
    try:
        # 关闭 store
        if _store:
            try:
                if hasattr(_store, "_task") and _store._task:
                    _store._task.cancel()
                    try:
                        await _store._task
                    except:
                        pass
                if hasattr(_store, "conn") and _store.conn:
                    await _store.conn.close()
                    cprint("[cleanup] Store connection closed", Colors.OKGREEN)
            except Exception as e:
                cprint(f"[cleanup] Error closing store: {e}", Colors.WARNING)
        
        # 关闭 checkpoint
        if _checkpoint:
            try:
                if hasattr(_checkpoint, "conn") and _checkpoint.conn:
                    await _checkpoint.conn.close()
                    cprint("[cleanup] Checkpoint connection closed", Colors.OKGREEN)
            except Exception as e:
                cprint(f"[cleanup] Error closing checkpoint: {e}", Colors.WARNING)
        
        # 重置全局变量
        _store = None
        _checkpoint = None
            
    except Exception as e:
        cprint(f"[cleanup] Error during cleanup: {e}", Colors.WARNING)