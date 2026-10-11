"""编码 subagent 唯一的文件/命令入口。"""
from langchain_core.tools import tool
from ..security.sandbox import CodingSandbox, scoped_path
from ..security.policy import bind_role_tools


def create_coding_tools(workspace):
    sandbox = CodingSandbox(workspace)

    @tool
    def bash(command: str, timeout_seconds: int = 60) -> str:
        """在隔离 /workspace 执行 Bash；只读系统依赖，禁止访问宿主项目/凭据和网络。"""
        return sandbox.run(command, timeout_seconds)

    @tool
    def read(file_path: str) -> str:
        """读取编码工作区内 UTF-8 文件（最多 100 KB）。"""
        path = scoped_path(sandbox.root, file_path)
        if path.stat().st_size > 100000:
            raise ValueError("文件过大")
        return path.read_text(encoding="utf-8")

    @tool
    def write(file_path: str, content: str) -> str:
        """在编码工作区创建或覆盖 UTF-8 文件。"""
        if len(content.encode()) > 1000000:
            raise ValueError("文件过大")
        path = scoped_path(sandbox.root, file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(sandbox.root))

    @tool
    def edit(file_path: str, target_content: str, replacement_content: str) -> str:
        """精确替换编码工作区文件中的一处内容。"""
        path = scoped_path(sandbox.root, file_path)
        content = read.invoke({"file_path": file_path})
        if not target_content or content.count(target_content) != 1:
            raise ValueError("替换目标必须非空且唯一")
        return write.invoke({"file_path": str(path.relative_to(sandbox.root)),
                             "content": content.replace(target_content, replacement_content, 1)})

    return list(bind_role_tools("coding", [bash, read, write, edit]).values())
