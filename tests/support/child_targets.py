"""Replacement crawl-child targets for the scraper's process tests (UT-107 to UT-109).

They are top-level functions, so the `spawn` child can import them. Each takes the same arguments
as `take_jobs.infrastructure.scraping.scraper.crawl_child`.
"""

import os
import time
from multiprocessing.connection import Connection
from typing import Any

from take_jobs.domain.models import CombinationOutcome, ScrapedJob, ScrapeReport


def sleep_then_report(connection: Connection, *_: Any) -> None:
    """Installs nothing, sleeps 60 s, then would send a valid report (UT-107)."""
    time.sleep(60)
    connection.send(ScrapeReport(outcomes=()))
    connection.close()


def crash_without_report(connection: Connection, *_: Any) -> None:
    """Exits with code 1 without sending anything (UT-108)."""
    os._exit(1)


def send_large_report(connection: Connection, *_: Any) -> None:
    """Sends a report of 15,000 jobs, well over 1 MiB pickled, then exits 0 (UT-109)."""
    connection.send(large_report())
    connection.close()


def large_report() -> ScrapeReport:
    jobs = tuple(
        ScrapedJob(
            source="vagas",
            external_id=str(index),
            title=f"Desenvolvedor Python {index}",
            url=f"https://www.vagas.com.br/vagas/v{index}/desenvolvedor-python",
            company="ACME",
            location="Sao Paulo / SP",
            description="descricao " * 20,
            published_label="09/10/2026",
        )
        for index in range(15_000)
    )
    return ScrapeReport(
        outcomes=(
            CombinationOutcome(source="vagas", term="python", jobs=jobs, pages=20, error=None),
        )
    )


def probe_socket_guard(connection: Connection, allow_hosts: list[str] | None) -> None:
    """Installs the test socket guard, then reports how `connect` and `connect_ex` behave."""
    import socket

    from pytest_socket import SocketConnectBlockedError

    from tests.support.socket_guard import install_test_socket_guard

    install_test_socket_guard(allow_hosts)
    result: dict[str, str] = {}
    for method in ("connect", "connect_ex"):
        for label, address in (("remote", "93.184.216.34"), ("loopback", "127.0.0.1")):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            try:
                outcome = getattr(sock, method)((address, 9))  # port 9: nothing listens
                result[f"{method}:{label}"] = f"returned {outcome}"
            except SocketConnectBlockedError:
                result[f"{method}:{label}"] = "blocked"
            except OSError:
                result[f"{method}:{label}"] = "refused"
            finally:
                sock.close()
    connection.send(result)
    connection.close()
