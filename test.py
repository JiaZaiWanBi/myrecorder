from myrecorder.app import load_config
from myrecorder.pipeline import build_pipeline, resolve_workflow_steps
from myrecorder.providers import create_provider

import aiohttp
import asyncio


async def main() -> None:
    cfg = load_config("config.yaml", "streams.yaml")
    if not cfg.streams:
        return

    target = cfg.streams[0]
    async with aiohttp.ClientSession() as session:
        provider = create_provider(
            target.provider,
            session=session,
            timeout_seconds=cfg.request_timeout_seconds,
            retries=cfg.request_retries,
        )
        pipeline = build_pipeline(cfg, target, provider_task=provider)
        print(resolve_workflow_steps(cfg, target))
        print([task.name for task in pipeline.tasks])


asyncio.run(main())
