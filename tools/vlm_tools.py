"""
VLM (Vision Language Model) Tools
提供图片读取工具，使视觉模型能够理解图片内容
"""

from typing import Annotated, Dict, Any
from langchain.tools import tool
from pydantic import Field
import base64
from pathlib import Path
import mimetypes
from utils.utils import get_workspace_path

def _get_media_type(path: str) -> str:
    """从路径获取媒体类型"""
    mime_type = mimetypes.guess_type(path)[0]
    return mime_type or 'image/jpeg'


def _validate_image_extension(path: str) -> bool:
    """验证文件扩展名是否为支持的图片格式"""
    supported_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    ext = Path(path).suffix.lower()
    return ext in supported_extensions


def _resolve_path(path: str) -> Path:
    """
    解析文件路径，结合 workspace 进行沙箱限制。
    - 相对路径：相对于 workspace 解析
    - 绝对路径：必须在 workspace 内
    """
    workspace = Path(get_workspace_path()).resolve()
    
    # 处理以 / 开头的路径（视为相对于 workspace）
    if path.startswith('/') or path.startswith('\\'):
        path = path.lstrip('/\\')
    
    file_path = Path(path)
    
    if file_path.is_absolute():
        resolved = file_path.resolve()
    else:
        resolved = (workspace / file_path).resolve()
    
    # 沙箱检查：确保路径在 workspace 内
    try:
        resolved.relative_to(workspace)
    except ValueError:
        raise PermissionError(f"Access denied: path is outside workspace: {path}")
    
    return resolved


@tool(description="Read an image from local file path (relative to workspace) or URL. Returns image content that will be injected into conversation for visual model understanding.")
def read_image(
    path_or_url: Annotated[str, Field(description="Local file path (relative to workspace) or HTTP/HTTPS URL of the image to read")],
    prompt: Annotated[str, Field(description="The prompt/question to ask about the image")] = "Please analyze the content of this image"
) -> Dict[str, Any]:
    """
    读取图片并返回可序列化的图片内容格式。
    支持本地文件路径（相对于 workspace）和 HTTP/HTTPS URL。
    
    返回带有特殊标记的 dict，会被 process_agent 解析并注入为 HumanMessage。
    - URL: 直接传递 URL，模型自行获取图片
    - 本地文件: 转换为 base64 编码（路径限制在 workspace 内）
    """
    try:
        if path_or_url.startswith(('http://', 'https://')):
            # URL 方式：直接传递 URL，不需要下载
            return {
                "__vlm_image__": True,
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image",
                        "source_type": "url",
                        "url": path_or_url
                    }
                ]
            }
        else:
            # 本地文件方式：结合 workspace 解析路径
            file_path = _resolve_path(path_or_url)
            
            if not file_path.exists():
                raise FileNotFoundError(f"Image file not found: {path_or_url}")
            
            if not file_path.is_file():
                raise ValueError(f"Path is not a file: {path_or_url}")
            
            # 验证图片格式
            if not _validate_image_extension(str(file_path)):
                raise ValueError(f"Unsupported image format. Supported: jpeg, png, gif, webp, bmp")
            
            # 读取并转换为 base64
            image_data = file_path.read_bytes()
            media_type = _get_media_type(str(file_path))
            base64_data = base64.standard_b64encode(image_data).decode('utf-8')
            
            return {
                "__vlm_image__": True,
                "content": [
                    {
                        "type": "text",
                        "text": prompt
                    },
                    {
                        "type": "image",
                        "source_type": "base64",
                        "mime_type": media_type,
                        "data": base64_data
                    }
                ]
            }
        
    except FileNotFoundError as e:
        raise e
    except PermissionError:
        raise PermissionError(f"Permission denied reading file: {path_or_url}")
    except ValueError as e:
        raise e
    except Exception as e:
        raise RuntimeError(f"Failed to read image: {e}")
