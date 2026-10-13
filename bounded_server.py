#!/usr/bin/env python3
"""
Bounded worker-pool HTTP server and mixin for Forge Console, Insights, and Ideas.

Replaces unbounded ThreadingHTTPServer with a bounded ThreadPoolExecutor worker pool.
Under saturation, incoming connections are accepted, immediately answered with
HTTP 503 Service Unavailable + Retry-After: 2, and closed without unbounded queueing.
Worker threads are daemon threads to ensure clean, non-blocking shutdown.
Python 3.14 stdlib only.
"""

from __future__ import annotations

import socketserver
import sys
import threading
import time
import weakref
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.thread import _worker
from http.server import HTTPServer


class DaemonThreadPoolExecutor(ThreadPoolExecutor):
    """
    ThreadPoolExecutor subclass that creates daemon worker threads.
    Does not register threads in _threads_queues so atexit / interpreter exit
    never blocks on idle or keep-alive worker threads.
    """

    def _adjust_thread_count(self) -> None:
        if self._idle_semaphore.acquire(timeout=0):
            return

        def weakref_cb(_, q=self._work_queue):
            q.put(None)

        num_threads = len(self._threads)
        if num_threads < self._max_workers:
            thread_name = f"{self._thread_name_prefix or self}_{num_threads}"
            t = threading.Thread(
                name=thread_name,
                target=_worker,
                args=(
                    weakref.ref(self, weakref_cb),
                    self._create_worker_context(),
                    self._work_queue,
                ),
                daemon=True,
            )
            t.start()
            self._threads.add(t)


class BoundedThreadPoolMixIn(socketserver.ThreadingMixIn):
    """
    socketserver mix-in that processes requests using a bounded ThreadPoolExecutor.
    If the worker pool is saturated (all max_workers busy), it immediately responds
    with HTTP 503 Service Unavailable + Retry-After: 2 and closes the socket.
    Workers are daemon threads so shutdown is clean and non-blocking.
    """

    daemon_threads = True
    max_workers: int = 64

    def __init__(
        self,
        *args,
        max_workers: int | None = None,
        thread_name_prefix: str = "",
        **kwargs,
    ) -> None:
        if max_workers is not None:
            self.max_workers = max_workers
        super().__init__(*args, **kwargs)
        self._worker_semaphore = threading.BoundedSemaphore(self.max_workers)
        prefix = thread_name_prefix or f"pool_{getattr(self, 'server_port', 'srv')}"
        self.executor = DaemonThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=prefix,
        )
        self._last_sat_log = 0.0

    @property
    def active_workers(self) -> int:
        """Returns the number of workers currently processing requests."""
        return max(0, self.max_workers - self._worker_semaphore._value)

    def process_request(self, request, client_address) -> None:
        """Submit request handling to the bounded worker pool or reject with 503 if saturated."""
        if not self._worker_semaphore.acquire(blocking=False):
            self._handle_saturated(request, client_address)
            return

        def _worker_task():
            try:
                self.process_request_thread(request, client_address)
            finally:
                self._worker_semaphore.release()

        try:
            self.executor.submit(_worker_task)
        except Exception:
            self._worker_semaphore.release()
            self._handle_saturated(request, client_address)

    def _handle_saturated(self, request, client_address) -> None:
        """Respond with 503 Service Unavailable and Retry-After: 2 header, then close socket."""
        now = time.time()
        if now - self._last_sat_log > 1.0:
            self._last_sat_log = now
            port_label = getattr(self, "server_port", "server")
            sys.stderr.write(
                f"[{port_label}] Worker pool saturated (max_workers={self.max_workers}), "
                f"returning 503 + Retry-After: 2 to {client_address}\n"
            )

        try:
            request.settimeout(5.0)
            body = b'{"error": "Server busy, worker pool saturated", "status": 503}\n'
            response = (
                b"HTTP/1.1 503 Service Unavailable\r\n"
                b"Content-Type: application/json; charset=utf-8\r\n"
                b"Retry-After: 2\r\n"
                b"Connection: close\r\n"
                b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n"
                b"\r\n" + body
            )
            request.sendall(response)
        except Exception:
            pass
        finally:
            self.shutdown_request(request)

    def server_close(self) -> None:
        super().server_close()
        if hasattr(self, "executor"):
            self.executor.shutdown(wait=False, cancel_futures=True)


class BoundedThreadingServer(BoundedThreadPoolMixIn, HTTPServer):
    """HTTP Server with bounded worker pool, reuse address, and daemon threads."""

    allow_reuse_address = True
    daemon_threads = True
