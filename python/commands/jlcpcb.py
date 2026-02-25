"""
JLCPCB API client for fetching parts data

Handles authentication and downloading the JLCPCB parts library
for integration with KiCAD component selection.
"""

import os
import logging
import requests
import time
import shutil
import subprocess
import errno
import sqlite3
import hmac
import hashlib
import secrets
import string
import base64
import json
import os
from typing import Optional, Dict, List, Callable, Any
from pathlib import Path

logger = logging.getLogger("kicad_interface")


class JLCPCBClient:
    """
    Client for JLCPCB API

    Handles HMAC-SHA256 signature-based authentication and fetching
    the complete parts library from JLCPCB's external API.
    """

    BASE_URL = "https://jlcpcb.com/external"
    YAQWSX_BASE_URL = "https://yaqwsx.github.io/jlcparts/data"
    YAQWSX_MAX_PARTS = 60
    YAQWSX_DEFAULT_DOWNLOAD_MB = 950.0
    YAQWSX_DEFAULT_DB_MB = 1700.0
    YAQWSX_ESTIMATED_TOTAL_PARTS = 7000000
    YAQWSX_ESTIMATED_IN_STOCK_PARTS = 650000
    YAQWSX_ESTIMATED_BASIC_PARTS = 350

    @staticmethod
    def _estimate_minutes(total_bytes: int, mbps: float) -> float:
        if total_bytes <= 0 or mbps <= 0:
            return 0.0
        bits = float(total_bytes) * 8.0
        seconds = bits / (mbps * 1_000_000.0)
        return round(seconds / 60.0, 1)

    @staticmethod
    def _normalize_etag(value: Optional[str]) -> str:
        if not value:
            return ""
        normalized = str(value).strip()
        if normalized.startswith("W/"):
            normalized = normalized[2:]
        return normalized.strip('"')

    def __init__(
        self,
        app_id: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
    ):
        """
        Initialize JLCPCB API client

        Args:
            app_id: JLCPCB App ID (or reads from JLCPCB_APP_ID env var)
            access_key: JLCPCB Access Key (or reads from JLCPCB_API_KEY env var)
            secret_key: JLCPCB Secret Key (or reads from JLCPCB_API_SECRET env var)
        """
        self.app_id = app_id or os.getenv("JLCPCB_APP_ID")
        self.access_key = access_key or os.getenv("JLCPCB_API_KEY")
        self.secret_key = secret_key or os.getenv("JLCPCB_API_SECRET")

        if not self.app_id or not self.access_key or not self.secret_key:
            logger.warning(
                "JLCPCB API credentials not found. Set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET environment variables."
            )

    def estimate_yaqwsx_download(self) -> Dict[str, Any]:
        file_sizes: Dict[str, int] = {}
        total_bytes = 0
        archive_parts = self._discover_yaqwsx_archive_parts()

        for filename in archive_parts:
            url = f"{self.YAQWSX_BASE_URL}/{filename}"
            response = requests.head(url, timeout=30, allow_redirects=True)
            response.raise_for_status()
            size = int(response.headers.get("Content-Length", 0) or 0)
            file_sizes[filename] = size
            total_bytes += size

        total_mb = round(total_bytes / (1024 * 1024), 1)
        estimated_db_mb = round(total_mb * 1.8, 1)
        min_minutes = self._estimate_minutes(total_bytes, 100.0)
        max_minutes = self._estimate_minutes(total_bytes, 20.0)
        created_at = None
        try:
            index_response = requests.get(
                f"{self.YAQWSX_BASE_URL}/index.json", timeout=60
            )
            index_response.raise_for_status()
            created_at = index_response.json().get("created")
        except Exception:
            created_at = None

        return {
            "source": "yaqwsx",
            "createdFrom": "https://github.com/yaqwsx/jlcparts",
            "createdAt": created_at,
            "downloadFiles": file_sizes,
            "archiveParts": archive_parts,
            "downloadSizeBytes": total_bytes,
            "downloadSizeMB": total_mb,
            "estimatedDatabaseSizeMB": estimated_db_mb,
            "estimatedDownloadTimeMinutes": {
                "min": min_minutes,
                "max": max_minutes,
                "note": "Estimated for ~100 Mbps to ~20 Mbps network speed.",
            },
            "estimatedPartCount": {
                "min": 6500000,
                "max": 7500000,
                "note": "Recent public snapshots are typically around 7 million parts; exact count depends on upstream build.",
            },
            "estimatedInStockParts": self.YAQWSX_ESTIMATED_IN_STOCK_PARTS,
            "estimatedBasicParts": self.YAQWSX_ESTIMATED_BASIC_PARTS,
            "estimatedExtendedParts": self.YAQWSX_ESTIMATED_TOTAL_PARTS
            - self.YAQWSX_ESTIMATED_BASIC_PARTS,
        }

    @staticmethod
    def _load_manifest(manifest_path: str) -> Dict[str, Any]:
        if not os.path.exists(manifest_path):
            return {}
        try:
            with open(manifest_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
        return {}

    @staticmethod
    def _save_manifest(manifest_path: str, data: Dict[str, Any]) -> None:
        tmp_path = f"{manifest_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp_path, manifest_path)

    def _get_remote_archive_metadata(
        self, archive_parts: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        remote: Dict[str, Dict[str, Any]] = {}
        for filename in archive_parts:
            url = f"{self.YAQWSX_BASE_URL}/{filename}"
            response = requests.head(url, timeout=30, allow_redirects=True)
            response.raise_for_status()

            content_length = int(response.headers.get("Content-Length", 0) or 0)
            etag = response.headers.get("ETag")
            last_modified = response.headers.get("Last-Modified")

            remote[filename] = {
                "size": content_length,
                "etag": etag,
                "lastModified": last_modified,
                "url": url,
            }
        return remote

    @staticmethod
    def _get_cache_total_parts(cache_db_path: str) -> Optional[int]:
        if not os.path.exists(cache_db_path):
            return None
        conn = sqlite3.connect(cache_db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            has_view = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_components'"
            ).fetchone()
            if has_view:
                row = cursor.execute(
                    "SELECT COUNT(*) AS c FROM v_components"
                ).fetchone()
            else:
                row = cursor.execute("SELECT COUNT(*) AS c FROM components").fetchone()
            if row and row["c"] is not None:
                return int(row["c"])
            return None
        finally:
            conn.close()

    def _plan_incremental_download(
        self,
        target_dir: str,
        archive_parts: List[str],
        remote_meta: Dict[str, Dict[str, Any]],
        previous_files: Dict[str, Any],
    ) -> Dict[str, Any]:
        parts_to_download: List[str] = []
        reused_parts: List[str] = []
        total_download_bytes = 0

        for filename in archive_parts:
            output_path = os.path.join(target_dir, filename)
            remote_file = remote_meta.get(filename, {})
            remote_size = int(remote_file.get("size", 0) or 0)
            previous = (
                previous_files.get(filename, {})
                if isinstance(previous_files, dict)
                else {}
            )

            local_exists = os.path.exists(output_path)
            local_size = os.path.getsize(output_path) if local_exists else -1
            same_size = local_exists and local_size == remote_size

            prev_etag = self._normalize_etag(previous.get("etag"))
            remote_etag = self._normalize_etag(remote_file.get("etag"))
            same_etag = (
                bool(prev_etag) and bool(remote_etag) and prev_etag == remote_etag
            )
            prev_last_modified = str(previous.get("lastModified") or "").strip()
            remote_last_modified = str(remote_file.get("lastModified") or "").strip()
            same_last_modified = (
                bool(prev_last_modified)
                and bool(remote_last_modified)
                and prev_last_modified == remote_last_modified
            )

            should_redownload = not local_exists
            if local_exists:
                if same_etag or same_last_modified:
                    should_redownload = False
                elif not same_size and (remote_etag or remote_last_modified):
                    should_redownload = True
                elif not same_size:
                    should_redownload = True
                elif remote_etag and prev_etag:
                    should_redownload = not same_etag
                elif remote_last_modified and prev_last_modified:
                    should_redownload = not same_last_modified
                else:
                    should_redownload = False

            if should_redownload:
                parts_to_download.append(filename)
                total_download_bytes += remote_size
            else:
                reused_parts.append(filename)

        return {
            "partsToDownload": parts_to_download,
            "reusedParts": reused_parts,
            "totalDownloadBytes": total_download_bytes,
        }

    def estimate_yaqwsx_update(
        self, target_dir: str, include_remote_check: bool = True
    ) -> Dict[str, Any]:
        os.makedirs(target_dir, exist_ok=True)

        manifest_path = os.path.join(target_dir, "cache_manifest.json")
        existing_manifest = self._load_manifest(manifest_path)
        previous_files = (
            existing_manifest.get("files", {})
            if isinstance(existing_manifest, dict)
            else {}
        )

        if not include_remote_check:
            known_total_bytes = 0
            if isinstance(previous_files, dict):
                for entry in previous_files.values():
                    if isinstance(entry, dict):
                        known_total_bytes += int(entry.get("size", 0) or 0)

            if known_total_bytes > 0:
                total_mb = round(known_total_bytes / (1024 * 1024), 1)
                total_bytes = known_total_bytes
                archive_parts = list(previous_files.keys())
            else:
                total_mb = self.YAQWSX_DEFAULT_DOWNLOAD_MB
                total_bytes = int(total_mb * 1024 * 1024)
                archive_parts = []

            estimated_db_mb = round(total_mb * 1.8, 1)
            estimate = {
                "source": "yaqwsx",
                "createdFrom": "https://github.com/yaqwsx/jlcparts",
                "createdAt": existing_manifest.get("createdAt")
                if isinstance(existing_manifest, dict)
                else None,
                "downloadFiles": {},
                "archiveParts": archive_parts,
                "downloadSizeBytes": total_bytes,
                "downloadSizeMB": total_mb,
                "estimatedDatabaseSizeMB": estimated_db_mb,
                "estimatedDownloadTimeMinutes": {
                    "min": self._estimate_minutes(total_bytes, 100.0),
                    "max": self._estimate_minutes(total_bytes, 20.0),
                    "note": "Estimated for full archive size.",
                },
                "estimatedPartCount": {
                    "min": 6500000,
                    "max": 7500000,
                    "note": "Recent public snapshots are typically around 7 million parts; exact count depends on upstream build.",
                },
                "estimatedInStockParts": self.YAQWSX_ESTIMATED_IN_STOCK_PARTS,
                "estimatedBasicParts": self.YAQWSX_ESTIMATED_BASIC_PARTS,
                "estimatedExtendedParts": self.YAQWSX_ESTIMATED_TOTAL_PARTS
                - self.YAQWSX_ESTIMATED_BASIC_PARTS,
                "cacheDirectory": target_dir,
                "cacheManifestPath": manifest_path,
                "estimatedUpdateDownloadBytes": total_bytes,
                "estimatedUpdateDownloadMB": total_mb,
                "changedArchiveParts": None,
                "reusedArchiveParts": len(archive_parts),
                "isInitialArchiveDownload": len(archive_parts) == 0,
                "estimatedUpdateTimeMinutes": {
                    "min": self._estimate_minutes(total_bytes, 100.0),
                    "max": self._estimate_minutes(total_bytes, 20.0),
                    "note": "Quick estimate; exact changed files are computed when download starts.",
                },
            }
            return estimate

        remote_created_at = None
        try:
            index_response = requests.get(
                f"{self.YAQWSX_BASE_URL}/index.json", timeout=30
            )
            index_response.raise_for_status()
            remote_created_at = index_response.json().get("created")
        except Exception:
            remote_created_at = None

        existing_created_at = (
            existing_manifest.get("createdAt")
            if isinstance(existing_manifest, dict)
            else None
        )
        if (
            remote_created_at
            and existing_created_at
            and str(remote_created_at) == str(existing_created_at)
            and isinstance(previous_files, dict)
            and len(previous_files) > 0
        ):
            archive_parts = list(previous_files.keys())
            if all(
                os.path.exists(os.path.join(target_dir, part)) for part in archive_parts
            ):
                known_total_bytes = sum(
                    int(v.get("size", 0) or 0)
                    for v in previous_files.values()
                    if isinstance(v, dict)
                )
                total_mb = round(known_total_bytes / (1024 * 1024), 1)
                estimate = {
                    "source": "yaqwsx",
                    "createdFrom": "https://github.com/yaqwsx/jlcparts",
                    "createdAt": remote_created_at,
                    "downloadFiles": {},
                    "archiveParts": archive_parts,
                    "downloadSizeBytes": known_total_bytes,
                    "downloadSizeMB": total_mb,
                    "estimatedDatabaseSizeMB": round(total_mb * 1.8, 1),
                    "estimatedDownloadTimeMinutes": {
                        "min": self._estimate_minutes(known_total_bytes, 100.0),
                        "max": self._estimate_minutes(known_total_bytes, 20.0),
                        "note": "Estimated for full archive size.",
                    },
                    "estimatedPartCount": {
                        "min": 6500000,
                        "max": 7500000,
                        "note": "Recent public snapshots are typically around 7 million parts; exact count depends on upstream build.",
                    },
                    "estimatedInStockParts": self.YAQWSX_ESTIMATED_IN_STOCK_PARTS,
                    "estimatedBasicParts": self.YAQWSX_ESTIMATED_BASIC_PARTS,
                    "estimatedExtendedParts": self.YAQWSX_ESTIMATED_TOTAL_PARTS
                    - self.YAQWSX_ESTIMATED_BASIC_PARTS,
                    "cacheDirectory": target_dir,
                    "cacheManifestPath": manifest_path,
                    "estimatedUpdateDownloadBytes": 0,
                    "estimatedUpdateDownloadMB": 0.0,
                    "changedArchiveParts": 0,
                    "reusedArchiveParts": len(archive_parts),
                    "isInitialArchiveDownload": False,
                    "estimatedUpdateTimeMinutes": {
                        "min": 0.0,
                        "max": 0.0,
                        "note": "No archive updates detected from index timestamp.",
                    },
                }
                return estimate

        base_estimate = self.estimate_yaqwsx_download()
        archive_parts = list(base_estimate.get("archiveParts", []))

        remote_meta = self._get_remote_archive_metadata(archive_parts)
        plan = self._plan_incremental_download(
            target_dir=target_dir,
            archive_parts=archive_parts,
            remote_meta=remote_meta,
            previous_files=previous_files,
        )

        update_bytes = int(plan["totalDownloadBytes"])
        update_mb = round(update_bytes / (1024 * 1024), 1)
        base_estimate["cacheDirectory"] = target_dir
        base_estimate["cacheManifestPath"] = manifest_path
        base_estimate["estimatedUpdateDownloadBytes"] = update_bytes
        base_estimate["estimatedUpdateDownloadMB"] = update_mb
        base_estimate["changedArchiveParts"] = len(plan["partsToDownload"])
        base_estimate["reusedArchiveParts"] = len(plan["reusedParts"])
        base_estimate["isInitialArchiveDownload"] = len(plan["reusedParts"]) == 0
        base_estimate["estimatedUpdateTimeMinutes"] = {
            "min": self._estimate_minutes(update_bytes, 100.0),
            "max": self._estimate_minutes(update_bytes, 20.0),
            "note": "Estimated for changed/new archive parts only.",
        }
        return base_estimate

    def download_yaqwsx_cache(
        self,
        target_dir: str,
        extract_dir: Optional[str] = None,
        callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> Dict[str, Any]:
        os.makedirs(target_dir, exist_ok=True)

        estimate = self.estimate_yaqwsx_update(target_dir, include_remote_check=True)
        archive_parts = estimate.get("archiveParts", [])
        total_bytes = int(estimate["downloadSizeBytes"])

        if (
            int(estimate.get("changedArchiveParts", 0) or 0) == 0
            and float(estimate.get("estimatedUpdateDownloadMB", 0.0) or 0.0) == 0.0
        ):
            return {
                "cacheDbPath": "",
                "downloadedBytes": 0,
                "totalDownloadBytes": 0,
                "remoteTotalBytes": total_bytes,
                "changedParts": 0,
                "reusedParts": int(
                    estimate.get("reusedArchiveParts", len(archive_parts))
                ),
                "updatedParts": [],
                "estimated": estimate,
                "cacheDir": target_dir,
                "manifestPath": os.path.join(target_dir, "cache_manifest.json"),
                "noUpdate": True,
            }

        manifest_path = os.path.join(target_dir, "cache_manifest.json")
        existing_manifest = self._load_manifest(manifest_path)
        remote_meta = self._get_remote_archive_metadata(archive_parts)

        previous_files = (
            existing_manifest.get("files", {})
            if isinstance(existing_manifest, dict)
            else {}
        )
        plan = self._plan_incremental_download(
            target_dir=target_dir,
            archive_parts=archive_parts,
            remote_meta=remote_meta,
            previous_files=previous_files,
        )
        parts_to_download = list(plan["partsToDownload"])
        reused_parts = list(plan["reusedParts"])
        total_download_bytes = int(plan["totalDownloadBytes"])

        estimated_db_bytes = int(
            float(estimate.get("estimatedDatabaseSizeMB", 0)) * 1024 * 1024
        )
        download_required_bytes = int(total_download_bytes)

        download_free_bytes = shutil.disk_usage(target_dir).free
        if download_free_bytes < download_required_bytes:
            required_mb = round(download_required_bytes / (1024 * 1024), 1)
            free_mb = round(download_free_bytes / (1024 * 1024), 1)
            raise Exception(
                f"Insufficient disk space for public snapshot archive updates. Required ~{required_mb} MB, available {free_mb} MB."
            )

        extraction_target_dir = extract_dir or target_dir
        os.makedirs(extraction_target_dir, exist_ok=True)

        extraction_free_bytes = shutil.disk_usage(extraction_target_dir).free
        if extraction_free_bytes < estimated_db_bytes:
            required_mb = round(estimated_db_bytes / (1024 * 1024), 1)
            free_mb = round(extraction_free_bytes / (1024 * 1024), 1)
            raise Exception(
                f"Insufficient disk space for public snapshot extraction/import. Required ~{required_mb} MB, available {free_mb} MB."
            )

        downloaded_bytes = 0

        if callback:
            callback(
                0,
                max(total_download_bytes, 1),
                f"Reusing {len(reused_parts)} unchanged archive parts; downloading {len(parts_to_download)} changed/new parts",
            )

        for index, filename in enumerate(parts_to_download, start=1):
            file_meta = remote_meta.get(filename, {})
            url = str(file_meta.get("url") or f"{self.YAQWSX_BASE_URL}/{filename}")
            output_path = os.path.join(target_dir, filename)

            with requests.get(url, stream=True, timeout=120) as response:
                response.raise_for_status()
                with open(output_path, "wb") as out:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        try:
                            out.write(chunk)
                        except OSError as e:
                            if e.errno == errno.ENOSPC:
                                raise Exception(
                                    "Insufficient disk space while downloading public snapshot archive."
                                ) from e
                            raise

                        downloaded_bytes += len(chunk)

                        if callback and downloaded_bytes % (10 * 1024 * 1024) < len(
                            chunk
                        ):
                            callback(
                                downloaded_bytes,
                                max(total_download_bytes, 1),
                                f"Downloaded {filename} ({index}/{len(parts_to_download)})",
                            )

            if callback:
                callback(
                    downloaded_bytes,
                    max(total_download_bytes, 1),
                    f"Finished {filename} ({index}/{len(parts_to_download)})",
                )

        final_manifest = {
            "updatedAt": int(time.time()),
            "source": "public",
            "createdAt": estimate.get("createdAt"),
            "files": {
                name: {
                    "size": int(remote_meta.get(name, {}).get("size", 0) or 0),
                    "etag": remote_meta.get(name, {}).get("etag"),
                    "lastModified": remote_meta.get(name, {}).get("lastModified"),
                }
                for name in archive_parts
            },
        }
        self._save_manifest(manifest_path, final_manifest)

        archive_path = os.path.join(target_dir, "cache.zip")
        if not os.path.exists(archive_path):
            raise Exception("yaqwsx cache.zip was not downloaded")

        missing_parts = [
            part
            for part in archive_parts
            if not os.path.exists(os.path.join(target_dir, part))
        ]
        if missing_parts:
            raise Exception(
                f"Missing archive part files required for extraction: {', '.join(missing_parts[:5])}"
            )

        seven_zip = shutil.which("7z")
        if not seven_zip:
            raise Exception("7z is required to extract yaqwsx cache archive")

        cpu_count = max(1, int(os.cpu_count() or 1))
        extract_threads = max(
            1,
            int(os.getenv("JLCPCB_EXTRACT_THREADS", str(cpu_count))),
        )

        extract = subprocess.run(
            [seven_zip, "x", "-y", f"-mmt={extract_threads}", archive_path],
            cwd=extraction_target_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if extract.returncode != 0:
            output_lower = (extract.stdout or "").lower()
            if "no space left" in output_lower or "disk full" in output_lower:
                raise Exception(
                    "Insufficient disk space while extracting public snapshot archive."
                )
            raise Exception(
                f"Failed to extract yaqwsx cache archive: {extract.stdout[-800:]}"
            )

        cache_db_path = os.path.join(extraction_target_dir, "cache.sqlite3")
        if not os.path.exists(cache_db_path):
            raise Exception("Extracted yaqwsx archive did not produce cache.sqlite3")

        expected_total_parts = self._get_cache_total_parts(cache_db_path)

        return {
            "cacheDbPath": cache_db_path,
            "downloadedBytes": downloaded_bytes,
            "totalDownloadBytes": total_download_bytes,
            "remoteTotalBytes": total_bytes,
            "changedParts": len(parts_to_download),
            "reusedParts": len(reused_parts),
            "updatedParts": parts_to_download,
            "estimated": estimate,
            "cacheDir": target_dir,
            "manifestPath": manifest_path,
            "expectedTotalParts": expected_total_parts,
        }

    def _discover_yaqwsx_archive_parts(self) -> List[str]:
        parts: List[str] = []
        misses = 0

        for idx in range(1, self.YAQWSX_MAX_PARTS + 1):
            name = f"cache.z{idx:02d}"
            url = f"{self.YAQWSX_BASE_URL}/{name}"
            try:
                response = requests.head(url, timeout=30, allow_redirects=True)
                if response.status_code == 200:
                    parts.append(name)
                    misses = 0
                else:
                    misses += 1
            except Exception:
                misses += 1

            if misses >= 3 and idx > 8:
                break

        parts.append("cache.zip")
        return parts

    @staticmethod
    def _generate_nonce() -> str:
        """Generate a 32-character random nonce"""
        chars = string.ascii_letters + string.digits
        return "".join(secrets.choice(chars) for _ in range(32))

    def _build_signature_string(
        self, method: str, path: str, timestamp: int, nonce: str, body: str
    ) -> str:
        """
        Build the signature string according to JLCPCB spec

        Format:
        <HTTP Method>\n
        <Request Path>\n
        <Timestamp>\n
        <Nonce>\n
        <Request Body>\n

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path with query params
            timestamp: Unix timestamp in seconds
            nonce: 32-character random string
            body: Request body (empty string for GET)

        Returns:
            Signature string
        """
        return f"{method}\n{path}\n{timestamp}\n{nonce}\n{body}\n"

    def _sign(self, signature_string: str) -> str:
        """
        Sign the signature string with HMAC-SHA256

        Args:
            signature_string: The string to sign

        Returns:
            Base64-encoded signature
        """
        signature_bytes = hmac.new(
            str(self.secret_key).encode("utf-8"),
            signature_string.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.b64encode(signature_bytes).decode("utf-8")

    def _get_auth_header(self, method: str, path: str, body: str = "") -> str:
        """
        Generate the Authorization header for JLCPCB API requests

        Args:
            method: HTTP method (GET, POST, etc.)
            path: Request path with query params
            body: Request body JSON string (empty for GET)

        Returns:
            Authorization header value
        """
        if not self.app_id or not self.access_key or not self.secret_key:
            raise Exception(
                "JLCPCB API credentials not configured. Please set JLCPCB_APP_ID, JLCPCB_API_KEY, and JLCPCB_API_SECRET environment variables."
            )

        nonce = self._generate_nonce()
        timestamp = int(time.time())

        signature_string = self._build_signature_string(
            method, path, timestamp, nonce, body
        )
        signature = self._sign(signature_string)

        logger.debug(f"Signature string:\n{repr(signature_string)}")
        logger.debug(f"Signature: {signature}")
        logger.debug(
            f'Auth header: JOP appid="{self.app_id}",accesskey="{self.access_key}",nonce="{nonce}",timestamp="{timestamp}",signature="{signature}"'
        )

        return f'JOP appid="{self.app_id}",accesskey="{self.access_key}",nonce="{nonce}",timestamp="{timestamp}",signature="{signature}"'

    def fetch_parts_page(self, last_key: Optional[str] = None) -> Dict:
        """
        Fetch one page of parts from JLCPCB API

        Args:
            last_key: Pagination key from previous response (None for first page)

        Returns:
            Response dict with parts data and pagination info
        """
        path = "/component/getComponentInfos"

        payload = {}
        if last_key:
            payload["lastKey"] = last_key

        # Convert payload to JSON string for signing
        # For POST requests, we always send JSON, even if empty dict
        body_str = json.dumps(payload, separators=(",", ":"))

        # Generate authorization header
        auth_header = self._get_auth_header("POST", path, body_str)

        headers = {"Authorization": auth_header, "Content-Type": "application/json"}

        try:
            response = requests.post(
                f"{self.BASE_URL}{path}", headers=headers, json=payload, timeout=60
            )

            logger.debug(f"Response status: {response.status_code}")
            logger.debug(f"Response headers: {response.headers}")
            logger.debug(f"Response text: {response.text}")

            response.raise_for_status()
            data = response.json()

            if data.get("code") != 200:
                raise Exception(
                    f"API request failed (code {data.get('code')}): {data.get('msg', 'Unknown error')} - Full response: {data}"
                )

            return data["data"]

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch parts page: {e}")
            raise Exception(f"JLCPCB API request failed: {e}")

    def download_full_database(
        self, callback: Optional[Callable[[int, int, str], None]] = None
    ) -> List[Dict]:
        """
        Download entire parts library from JLCPCB

        Args:
            callback: Optional progress callback function(current_page, total_parts, status_msg)

        Returns:
            List of all parts
        """
        all_parts = []
        last_key = None
        page = 0

        logger.info("Starting full JLCPCB parts database download...")

        while True:
            page += 1

            try:
                data = self.fetch_parts_page(last_key)

                parts = data.get("componentInfos", [])
                all_parts.extend(parts)

                last_key = data.get("lastKey")

                if callback:
                    callback(
                        page, len(all_parts), f"Downloaded {len(all_parts)} parts..."
                    )
                else:
                    logger.info(
                        f"Page {page}: Downloaded {len(all_parts)} parts so far..."
                    )

                # Check if there are more pages
                if not last_key or len(parts) == 0:
                    break

                # Rate limiting - be nice to the API
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Error downloading parts at page {page}: {e}")
                if len(all_parts) > 0:
                    logger.warning(
                        f"Partial download available: {len(all_parts)} parts"
                    )
                    return all_parts
                else:
                    raise

        logger.info(f"Download complete: {len(all_parts)} parts retrieved")
        return all_parts

    def get_part_by_lcsc(self, lcsc_number: str) -> Optional[Dict]:
        """
        Get detailed information for a specific LCSC part number

        Note: This uses the same endpoint as fetching parts, as JLCPCB doesn't
        have a dedicated single-part endpoint. In practice, you should use
        the local database after initial download.

        Args:
            lcsc_number: LCSC part number (e.g., "C25804")

        Returns:
            Part info dict or None if not found
        """
        # For now, this would require searching through pages
        # In practice, you'd use the local database
        logger.warning("get_part_by_lcsc should use local database, not API")
        return None


def test_jlcpcb_connection(
    app_id: Optional[str] = None,
    access_key: Optional[str] = None,
    secret_key: Optional[str] = None,
) -> bool:
    """
    Test JLCPCB API connection

    Args:
        app_id: Optional App ID (uses env var if not provided)
        access_key: Optional Access Key (uses env var if not provided)
        secret_key: Optional Secret Key (uses env var if not provided)

    Returns:
        True if connection successful, False otherwise
    """
    try:
        client = JLCPCBClient(app_id, access_key, secret_key)
        # Test by fetching first page
        data = client.fetch_parts_page()
        logger.info("JLCPCB API connection test successful")
        return True
    except Exception as e:
        logger.error(f"JLCPCB API connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Test the JLCPCB client
    logging.basicConfig(level=logging.INFO)

    print("Testing JLCPCB API connection...")
    if test_jlcpcb_connection():
        print("✓ Connection successful!")

        client = JLCPCBClient()
        print("\nFetching first page of parts...")
        data = client.fetch_parts_page()
        parts = data.get("componentInfos", [])
        print(f"✓ Retrieved {len(parts)} parts in first page")

        if parts:
            print(f"\nExample part:")
            part = parts[0]
            print(f"  LCSC: {part.get('componentCode')}")
            print(f"  MFR Part: {part.get('componentModelEn')}")
            print(
                f"  Category: {part.get('firstSortName')} / {part.get('secondSortName')}"
            )
            print(f"  Package: {part.get('componentSpecificationEn')}")
            print(f"  Stock: {part.get('stockCount')}")
    else:
        print("✗ Connection failed. Check your API credentials.")
