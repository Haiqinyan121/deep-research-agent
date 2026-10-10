"""本地知识库索引脚本 —— 扫描文档目录，切分、向量化，持久化到 Chroma。

用法（在 `langgraph/src` 下执行）:

    python knowledge_indexer.py                        # 索引配置里的 KNOWLEDGE_BASE_DIR
    python knowledge_indexer.py --docs ../data/docs    # 指定文档目录
    python knowledge_indexer.py --reset                # 先清空旧索引再重建

支持 `.txt` / `.md` / `.pdf`。

**重复执行是幂等的**：每个切片用「相对路径::序号」做固定 id，
重新索引会**覆盖**同名切片，而不是无限追加。
（如果源文件变短了，多出来的旧切片要靠 `--reset` 清理。）
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from config import Configuration
from rag_tool import build_embeddings

SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}

# 中文文档优先按段落、句子切，最后才退化到按字符切
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ". ", " ", ""]


def _read_pdf(path: Path) -> str:
    """用 pypdf 抽 PDF 文本（避免引入 langchain-community 这个大依赖）。"""

    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _read_file(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return _read_pdf(path)
    # errors="ignore" —— 个别乱码字符不该让整个索引失败
    return path.read_text(encoding="utf-8", errors="ignore")


def _iter_files(docs_dir: Path) -> list[Path]:
    return sorted(
        p for p in docs_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _clear_index(config: Configuration, persist_dir: Path) -> None:
    """清空已有索引：先删目录，删不动再让 Chroma 删 collection。

    为什么要两步：Windows 上只要还有进程（比如 `ENABLE_RAG=True` 的 `server.py`）
    连着这个向量库，`data_level0.bin` 就被占着，`rmtree` 会抛
    `PermissionError: [WinError 32]`。这时改用 Chroma 自己的 `delete_collection`
    —— 它删的是自己的数据，不碰文件系统，库被别人连着也能删干净。

    两步都失败时给一条能照着做的中文提示，而不是甩一个裸的 WinError 堆栈。
    """

    # 先试最直接的：删目录。没有别的进程占着库时一步到位，
    # 而且**不会在进程里留下任何 Chroma 句柄** —— 顺序很重要，
    # 反过来先开 PersistentClient 的话，它自己就会把句柄占上，把 rmtree 弄失败。
    try:
        shutil.rmtree(persist_dir)
        print(f"[清理] 已清空旧索引：{persist_dir.resolve()}")
        return
    except PermissionError:
        pass  # 句柄被占着（server.py 正连着这个库），换 Chroma 自己的接口

    # 退回 delete_collection：让 Chroma 删它自己的数据，不碰文件系统，
    # 所以同进程内已有连接也不影响。
    try:
        import chromadb

        chromadb.PersistentClient(path=str(persist_dir)).delete_collection(config.rag_collection)
        print(f"[清理] 已删除 collection：{config.rag_collection}")
        return
    except Exception as exc:
        raise SystemExit(
            f"[错误] 无法清空向量库 {persist_dir}：文件正被其他进程占用。\n"
            f"  请先停掉正在使用它的进程（例如 server.py），再重试。\n"
            f"  原始错误：{exc}"
        )


def build_index(config: Configuration, docs_dir: str | Path, reset: bool = False) -> int:
    """建索引，返回写入的切片总数。"""

    docs_path = Path(docs_dir).expanduser()
    if not docs_path.is_absolute():
        docs_path = (Path.cwd() / docs_path).resolve()
    if not docs_path.exists():
        raise SystemExit(f"[错误] 文档目录不存在：{docs_path}")

    persist_dir = config.resolved_vector_store_dir()

    if reset and persist_dir.exists():
        _clear_index(config, persist_dir)

    files = _iter_files(docs_path)
    if not files:
        suffixes = "/".join(sorted(SUPPORTED_SUFFIXES))
        raise SystemExit(f"[错误] {docs_path.resolve()} 下没有找到 {suffixes} 文件")

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.rag_chunk_size,
        chunk_overlap=config.rag_chunk_overlap,
        separators=SEPARATORS,
        length_function=len,
    )

    chunks: list[Document] = []
    ids: list[str] = []

    print(f"[扫描] 发现 {len(files)} 个文件：")
    for path in files:
        rel = path.relative_to(docs_path).as_posix()
        try:
            text = _read_file(path).strip()
        except Exception as exc:
            print(f"  [跳过] {rel} 读取失败，已跳过：{exc}")
            continue

        if not text:
            print(f"  [跳过] {rel} 内容为空，已跳过")
            continue

        pieces = splitter.split_text(text)
        for index, piece in enumerate(pieces):
            chunks.append(Document(page_content=piece, metadata={"source": rel, "chunk": index}))
            # 固定 id —— 这是"重复执行幂等"的关键
            ids.append(f"{rel}::{index}")
        print(f"  {rel}  →  {len(pieces)} 个切片")

    if not chunks:
        raise SystemExit("[错误] 所有文件都是空的，没有可索引的内容")

    print(f"\n[向量化] 共 {len(chunks)} 个切片，开始向量化（首次运行会下载 embedding 模型）…")

    Chroma.from_documents(
        documents=chunks,
        ids=ids,
        embedding=build_embeddings(config),
        collection_name=config.rag_collection,
        persist_directory=str(persist_dir),
    )

    print(f"[完成] 索引完成：{persist_dir.resolve()}")
    return len(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="为本地知识库建立向量索引")
    parser.add_argument(
        "--docs",
        default=None,
        help="文档目录，默认取配置项 KNOWLEDGE_BASE_DIR",
    )
    parser.add_argument("--reset", action="store_true", help="先清空已有索引再重建")
    args = parser.parse_args()

    config = Configuration.from_env()

    # 命令行传的相对路径按当前目录算；配置里的默认路径锚定到 langgraph/
    docs_dir = Path(args.docs).expanduser() if args.docs else config.resolved_knowledge_base_dir()
    if not docs_dir.is_absolute():
        docs_dir = (Path.cwd() / docs_dir).resolve()

    print(f"[文档] 文档目录：{docs_dir}")
    print(f"[索引] 索引目录：{config.resolved_vector_store_dir()}")
    print(f"[模型] Embedding：{config.embedding_provider} / {config.embedding_model}\n")

    build_index(config, docs_dir, reset=args.reset)


if __name__ == "__main__":
    sys.exit(main())
