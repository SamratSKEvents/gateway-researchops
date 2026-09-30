"""ResearchOps backend: mounts each module's router. No business logic here."""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .modules.research.api import router as research_api
from .modules.ai_runtime.api import router as ai_api
from .modules.store.api import router as store_api
from .modules.memory.api import router as memory_api

FRONT = Path(__file__).resolve().parent.parent / "frontend"
app = FastAPI(title="ResearchOps")
for r in (research_api, ai_api, store_api, memory_api):
    app.include_router(r)
app.mount("/research", StaticFiles(directory=FRONT / "research"), name="research")


@app.on_event("startup")
async def _warm_nli():   # load the GPU entailment model in the background so the first run doesn't wait for it
    import asyncio
    from .modules import nli
    asyncio.get_running_loop().run_in_executor(None, nli.available)


@app.get("/api/nli/status")
def nli_status():
    from .modules import nli
    return nli.status() if nli._state else {"model": nli.MODEL, "ready": False, "error": None, "device": "cuda", "loading": True}


@app.get("/")
def research_console():
    return FileResponse(FRONT / "research" / "index.html")
