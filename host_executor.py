# host_executor.py
# RUN ON YOUR HOST: uvicorn host_executor:app --host 127.0.0.1 --port 8091

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import asyncio
from typing import Optional
from fastapi.responses import StreamingResponse

app = FastAPI(title="Host Executor", version="1.0")

ALLOWED_COMMANDS = {
    "restart_quant_hub": (
        "sudo systemctl restart quant_hub.service",
        "Restart quant_hub systemd service",
        30,
        False,
    ),
    "status_quant_hub": (
        "systemctl status quant_hub.service --no-pager",
        "Show quant_hub service status",
        10,
        False,
    ),
    "restart_ollama": (
        "sudo systemctl restart ollama",
        "Restart Ollama systemd service",
        30,
        False,
    ),
    "restart_cloudflared": (
        "sudo systemctl restart cloudflared",
        "Restart Cloudflare Tunnel systemd service",
        30,
        False,
    ),
    "run_ingestion": (
        "/home/joey/Projects/henry_hub_atomic_agents/.venv/bin/python -m ingestion.orchestration.run_all",
        "Run all ingestion agents",
        300,
        False,
    ),
    "logs_quant_hub": (
        "journalctl -u quant_hub -f -n 100",
        "Follow quant_hub service logs (streaming)",
        0,
        True,
    ),
}

class CommandRequest(BaseModel):
    cmd: str = Field(..., description="Command key from allowlist")
    timeout: Optional[int] = Field(None, description="Override default timeout (seconds)")
    args: Optional[list[str]] = Field(None, description="Additional args")

class CommandResponse(BaseModel):
    success: bool
    cmd: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False

async def stream_command(cmd: str):
    process = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        async for line in process.stdout:
            yield line.decode("utf-8", errors="replace")
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()

@app.get("/logs/{cmd_key}")
async def stream_logs(cmd_key: str):
    if cmd_key not in ALLOWED_COMMANDS:
        raise HTTPException(404, f"Unknown command: {cmd_key}. Allowed: {list(ALLOWED_COMMANDS.keys())}")
    cmd_str, _, _, is_stream = ALLOWED_COMMANDS[cmd_key]
    if not is_stream:
        raise HTTPException(400, f"Command {cmd_key} is not a streaming command")
    return StreamingResponse(
        stream_command(cmd_str),
        media_type="text/plain",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.post("/run", response_model=CommandResponse)
async def run_command(req: CommandRequest):
    if req.cmd not in ALLOWED_COMMANDS:
        raise HTTPException(404, f"Command '{req.cmd}' not allowed. Allowed: {list(ALLOWED_COMMANDS.keys())}")
    base_cmd, description, default_timeout, is_stream = ALLOWED_COMMANDS[req.cmd]
    if is_stream:
        raise HTTPException(400, f"Use GET /logs/{req.cmd} for streaming commands")
    if req.args:
        import re
        safe_args = []
        for arg in req.args:
            if re.fullmatch(r"[\w\-\./:=]+", arg):
                safe_args.append(arg)
            else:
                raise HTTPException(400, f"Unsafe argument rejected: {arg}")
        full_cmd = f"{base_cmd} {' '.join(safe_args)}"
    else:
        full_cmd = base_cmd
    timeout = req.timeout or default_timeout
    try:
        process = await asyncio.create_subprocess_shell(
            full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            timed_out = False
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            stdout, stderr = await process.communicate()
            timed_out = True
        return CommandResponse(
            success=process.returncode == 0 and not timed_out,
            cmd=req.cmd,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            exit_code=process.returncode or -1,
            timed_out=timed_out,
        )
    except Exception as e:
        raise HTTPException(500, f"Execution error: {e}")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "host-executor"}

@app.get("/commands")
async def list_commands():
    return {key: {"description": desc, "timeout": timeout, "streaming": stream} for key, (_, desc, timeout, stream) in ALLOWED_COMMANDS.items()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8091, log_level="info")
