"""watsonx Orchestrate client: IBM Cloud IAM auth + streaming chat/completions."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator, Optional

import httpx

from sse import WxoEvent, iter_sse_data, parse_payload

log = logging.getLogger("wxo")

IAM_URL = "https://iam.cloud.ibm.com/identity/token"


class WxoError(RuntimeError):
    pass


class WxoClient:
    """Streams one agent reply per call, reusing a wxO thread across turns.

    The IAM bearer token is cached and refreshed five minutes before it
    expires; concurrent callers share one refresh.
    """

    def __init__(self, instance_url: str, agent_id: str, api_key: str) -> None:
        self.instance_url = instance_url.rstrip("/")
        self.agent_id = agent_id
        self._api_key = api_key
        self._token: Optional[str] = None
        self._token_expires = 0.0
        self._token_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=90.0, write=10.0, pool=10.0),
            http2=False,
        )

    def completions_url(self) -> str:
        return f"{self.instance_url}/v2/orchestrate/{self.agent_id}/chat/completions"

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _bearer(self) -> str:
        async with self._token_lock:
            if self._token and time.time() < self._token_expires - 300:
                return self._token
            resp = await self._http.post(
                IAM_URL,
                data={
                    "grant_type": "urn:ibm:params:oauth:grant-type:apikey",
                    "apikey": self._api_key,
                },
                headers={"Accept": "application/json"},
            )
            if resp.status_code != 200:
                raise WxoError(f"IAM token exchange failed ({resp.status_code}). Check WXO_API_KEY.")
            body = resp.json()
            self._token = body["access_token"]
            self._token_expires = float(body.get("expiration", time.time() + 3600))
            log.info("IAM token refreshed, valid for %ds", int(self._token_expires - time.time()))
            return self._token

    async def stream(self, text: str, thread_id: Optional[str]) -> AsyncIterator[WxoEvent]:
        """Send one user message and yield events as the agent replies.

        Cancelling the consumer closes the HTTP stream, which stops the run
        on the wxO side as far as the client is concerned.
        """
        token = await self._bearer()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-IBM-THREAD-ID": thread_id or "new",
        }
        body = {"messages": [{"role": "user", "content": text}], "stream": True}

        url = self.completions_url()
        async with self._http.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread())[:300].decode("utf-8", "replace")
                raise WxoError(f"wxO returned {resp.status_code}: {detail}")

            # Some deployments return the thread id as a header before any
            # event; take it immediately so an early barge-in can't lose it.
            header_thread = resp.headers.get("x-ibm-thread-id")
            if header_thread and header_thread != "new":
                yield WxoEvent("thread", header_thread)

            async for data in _aiter_sse(resp.aiter_lines()):
                for event in parse_payload(data):
                    yield event
                    if event.kind == "done":
                        return


async def _aiter_sse(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Async version of sse.iter_sse_data."""
    buf: list[str] = []
    async for raw in lines:
        if raw == "" or raw in ("\r", "\n"):
            if buf:
                for data in iter_sse_data(buf + [""]):
                    yield data
                buf = []
            continue
        buf.append(raw)
    if buf:
        for data in iter_sse_data(buf):
            yield data
