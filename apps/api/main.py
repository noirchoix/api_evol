from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from core.config import settings
from routers.api import router

app=FastAPI(title=settings.app_name,version='0.5.0',description='Repository-aware semantic API contract evolution analysis, blast-radius detection, human-approved migration planning, and deterministic validation gates.')
app.add_middleware(CORSMiddleware,allow_origins=list(settings.cors_origins),allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
app.include_router(router,prefix=settings.api_prefix)

@app.get('/')
def root() -> dict[str,str]: return {'app':settings.app_name,'docs':'/docs','health':f'{settings.api_prefix}/health'}
