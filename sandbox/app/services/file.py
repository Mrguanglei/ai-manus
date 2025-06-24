"""
File Operation Service Implementation - Async Version
"""
import os
import re
import glob
import asyncio
import shutil
from io import BytesIO
from typing import Optional, BinaryIO
from app.models.file import (
    FileReadResult, FileWriteResult, FileReplaceResult,
    FileSearchResult, FileFindResult, FileExistsResult
)
from app.core.exceptions import AppException, ResourceNotFoundException, BadRequestException
from app.schemas.file import FileUploadResult, FileDownloadResult


class FileService:
    """File Operation Service"""

    async def read_file(self, file: str, start_line: Optional[int] = None,
                        end_line: Optional[int] = None, sudo: bool = False) -> FileReadResult:
        """
        Asynchronously read file content
        
        Args:
            file: Absolute file path
            start_line: Starting line (0-based)
            end_line: Ending line (not included)
            sudo: Whether to use sudo privileges
        """
        # Check if file exists
        if not os.path.exists(file) and not sudo:
            raise ResourceNotFoundException(f"File does not exist: {file}")

        try:
            content = ""

            # Read with sudo
            if sudo:
                command = f"sudo cat '{file}'"
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    raise BadRequestException(f"Failed to read file: {stderr.decode()}")

                content = stdout.decode('utf-8')
            else:
                # Asynchronously read file
                def read_file_async():
                    try:
                        with open(file, 'r', encoding='utf-8') as f:
                            return f.read()
                    except Exception as e:
                        raise AppException(message=f"Failed to read file: {str(e)}")

                # Execute IO operation in thread pool
                content = await asyncio.to_thread(read_file_async)

            # Process line range
            if start_line is not None or end_line is not None:
                lines = content.splitlines()
                start = start_line if start_line is not None else 0
                end = end_line if end_line is not None else len(lines)
                content = '\n'.join(lines[start:end])

            return FileReadResult(
                content=content,
                file=file
            )
        except Exception as e:
            if isinstance(e, BadRequestException) or isinstance(e, ResourceNotFoundException):
                raise e
            raise AppException(message=f"Failed to read file: {str(e)}")

    async def write_file(self, file: str, content: str, append: bool = False,
                         leading_newline: bool = False, trailing_newline: bool = False,
                         sudo: bool = False) -> FileWriteResult:
        """
        Asynchronously write file content
        
        Args:
            file: Absolute file path
            content: Content to write
            append: Whether to append mode
            leading_newline: Whether to add a leading newline
            trailing_newline: Whether to add a trailing newline
            sudo: Whether to use sudo privileges
        """
        try:
            # Prepare content
            if leading_newline:
                content = '\n' + content
            if trailing_newline:
                content = content + '\n'

            bytes_written = 0

            # Write with sudo
            if sudo:
                mode = '>>' if append else '>'
                # Create temporary file
                temp_file = f"/tmp/file_write_{os.getpid()}.tmp"

                # Asynchronously write to temporary file
                def write_temp_file():
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        f.write(content)
                    return len(content.encode('utf-8'))

                bytes_written = await asyncio.to_thread(write_temp_file)

                # Use sudo to write temporary file content to target file
                command = f"sudo bash -c \"cat {temp_file} {mode} '{file}'\""
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    raise BadRequestException(f"Failed to write file: {stderr.decode()}")

                # Clean up temporary file
                os.unlink(temp_file)
            else:
                # Ensure directory exists
                os.makedirs(os.path.dirname(file), exist_ok=True)

                # Asynchronously write file
                def write_file_async():
                    mode = 'a' if append else 'w'
                    with open(file, mode, encoding='utf-8') as f:
                        return f.write(content)

                bytes_written = await asyncio.to_thread(write_file_async)

            return FileWriteResult(
                file=file,
                bytes_written=bytes_written
            )
        except Exception as e:
            if isinstance(e, BadRequestException):
                raise e
            raise AppException(message=f"Failed to write file: {str(e)}")

    async def str_replace(self, file: str, old_str: str, new_str: str,
                          sudo: bool = False) -> FileReplaceResult:
        """
        Asynchronously replace string in file
        
        Args:
            file: Absolute file path
            old_str: Original string to be replaced
            new_str: New replacement string
            sudo: Whether to use sudo privileges
        """
        # First read file content
        file_result = await self.read_file(file, sudo=sudo)
        content = file_result.content

        # Calculate replacement count
        replaced_count = content.count(old_str)
        if replaced_count == 0:
            return FileReplaceResult(
                file=file,
                replaced_count=0
            )

        # Perform replacement
        new_content = content.replace(old_str, new_str)

        # Write back to file
        await self.write_file(file, new_content, sudo=sudo)

        return FileReplaceResult(
            file=file,
            replaced_count=replaced_count
        )

    async def find_in_content(self, file: str, regex: str,
                              sudo: bool = False) -> FileSearchResult:
        """
        Asynchronously search in file content
        
        Args:
            file: Absolute file path
            regex: Regular expression pattern
            sudo: Whether to use sudo privileges
        """
        # Read file
        file_result = await self.read_file(file, sudo=sudo)
        content = file_result.content

        # Process line by line
        lines = content.splitlines()
        matches = []
        line_numbers = []

        # Compile regular expression
        try:
            pattern = re.compile(regex)
        except Exception as e:
            raise BadRequestException(f"Invalid regular expression: {str(e)}")

        # Find matches (use async processing for possibly large files)
        def process_lines():
            nonlocal matches, line_numbers
            for i, line in enumerate(lines):
                if pattern.search(line):
                    matches.append(line)
                    line_numbers.append(i)

        await asyncio.to_thread(process_lines)

        return FileSearchResult(
            file=file,
            matches=matches,
            line_numbers=line_numbers
        )

    async def find_by_name(self, path: str, glob_pattern: str) -> FileFindResult:
        """
        Asynchronously find files by name pattern
        
        Args:
            path: Directory path to search
            glob_pattern: File name pattern (glob syntax)
        """
        # Check if path exists
        if not os.path.exists(path):
            raise ResourceNotFoundException(f"Directory does not exist: {path}")

        # Asynchronously find files
        def glob_async():
            search_pattern = os.path.join(path, glob_pattern)
            return glob.glob(search_pattern, recursive=True)

        files = await asyncio.to_thread(glob_async)

        return FileFindResult(
            path=path,
            files=files
        )

    async def check_exists(self, path: str) -> FileExistsResult:
        """
        Asynchronously check if file or directory exists
        
        Args:
            path: File or directory path to check
        """
        # Asynchronously check existence
        def exists_async():
            return os.path.exists(path)

        exists = await asyncio.to_thread(exists_async)

        return FileExistsResult(
            path=path,
            exists=exists
        )

    async def upload_file(
            self,
            file_data: BinaryIO,
            filename: str,
            target_path: str,
            content_type: Optional[str] = None
    ):
        # 确保目标目录存在
        os.makedirs(target_path, exist_ok=True)

        # 构建完整的文件路径
        file_path = os.path.join(target_path, filename)

        # 写入文件
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file_data, f)

        size = os.path.getsize(file_path)
        return FileUploadResult(
            filename=filename,
            path=file_path,
            size=size,
            content_type=content_type
        )



# Service instance
file_service = FileService()
