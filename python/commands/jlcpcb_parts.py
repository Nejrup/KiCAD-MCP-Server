"""
JLCPCB Parts Database Manager

Manages local SQLite database of JLCPCB parts for fast searching
and component selection.
"""

import os
import sqlite3
import json
import logging
import platform
import subprocess
import ctypes
from pathlib import Path
from typing import List, Dict, Optional, cast, Any
from datetime import datetime

logger = logging.getLogger("kicad_interface")


class JLCPCBPartsManager:
    """
    Manages local database of JLCPCB parts

    Provides fast parametric search, filtering, and package-to-footprint mapping.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize parts database manager

        Args:
            db_path: Path to SQLite database file (default: data/jlcpcb_parts.db)
        """
        if db_path is None:
            # Default to data directory in project root
            project_root = Path(__file__).parent.parent.parent
            data_dir = project_root / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "jlcpcb_parts.db")

        self.db_path = db_path
        self.conn: sqlite3.Connection = cast(sqlite3.Connection, None)
        self._init_database()

    def _init_database(self):
        """Initialize SQLite database with schema"""
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row  # Return rows as dicts

        cursor = self.conn.cursor()

        # Create components table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS components (
                lcsc TEXT PRIMARY KEY,
                category TEXT,
                subcategory TEXT,
                mfr_part TEXT,
                package TEXT,
                solder_joints INTEGER,
                manufacturer TEXT,
                library_type TEXT,
                description TEXT,
                datasheet TEXT,
                stock INTEGER,
                price_json TEXT,
                last_updated INTEGER
            )
        """)

        self._create_component_indexes(cursor)

        # Full-text search index for descriptions
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS components_fts USING fts5(
                lcsc,
                description,
                mfr_part,
                manufacturer,
                content=components
            )
        """)

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        self.conn.commit()
        logger.info(f"Initialized JLCPCB parts database at {self.db_path}")

    @staticmethod
    def _detect_total_memory_bytes() -> int:
        try:
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            phys_pages = int(os.sysconf("SC_PHYS_PAGES"))
            total = page_size * phys_pages
            if total > 0:
                return total
        except Exception:
            pass

        system = platform.system()
        try:
            if system == "Darwin":
                output = subprocess.check_output(
                    ["sysctl", "-n", "hw.memsize"], text=True
                )
                total = int(output.strip())
                if total > 0:
                    return total
            elif system == "Linux":
                with open("/proc/meminfo", "r", encoding="utf-8") as fh:
                    for line in fh:
                        if line.startswith("MemTotal:"):
                            parts = line.split()
                            if len(parts) >= 2:
                                return int(parts[1]) * 1024
            elif system == "Windows":

                class _MemoryStatusEx(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
                    ]

                memory_status = _MemoryStatusEx()
                memory_status.dwLength = ctypes.sizeof(_MemoryStatusEx)
                windll = getattr(ctypes, "windll", None)
                if windll and windll.kernel32.GlobalMemoryStatusEx(
                    ctypes.byref(memory_status)
                ):
                    total = int(memory_status.ullTotalPhys)
                    if total > 0:
                        return total
        except Exception:
            pass

        try:
            import psutil  # type: ignore

            return int(psutil.virtual_memory().total)
        except Exception:
            return 8 * 1024 * 1024 * 1024

    @staticmethod
    def _detect_cpu_count() -> int:
        return max(1, int(os.cpu_count() or 1))

    def _auto_import_tuning(self, incremental_since: Optional[int]) -> Dict[str, int]:
        cpu_count = self._detect_cpu_count()
        total_memory = self._detect_total_memory_bytes()
        total_gb = total_memory / (1024 * 1024 * 1024)

        if total_gb >= 32:
            full_batch = 250000
            inc_batch = 100000
            cache_kb = -262144
            mmap_bytes = 1024 * 1024 * 1024
            thread_cap = 16
        elif total_gb >= 16:
            full_batch = 150000
            inc_batch = 75000
            cache_kb = -131072
            mmap_bytes = 512 * 1024 * 1024
            thread_cap = 12
        elif total_gb >= 8:
            full_batch = 100000
            inc_batch = 50000
            cache_kb = -65536
            mmap_bytes = 256 * 1024 * 1024
            thread_cap = 8
        else:
            full_batch = 50000
            inc_batch = 25000
            cache_kb = -32768
            mmap_bytes = 128 * 1024 * 1024
            thread_cap = 4

        auto_batch = inc_batch if incremental_since is not None else full_batch
        auto_threads = max(1, min(cpu_count, thread_cap))

        batch_size = max(
            1000,
            int(os.getenv("JLCPCB_IMPORT_BATCH_SIZE", str(auto_batch))),
        )
        cpu_threads = max(
            1,
            int(os.getenv("JLCPCB_IMPORT_THREADS", str(auto_threads))),
        )
        cache_size_kb = int(os.getenv("JLCPCB_IMPORT_CACHE_KB", str(cache_kb)))
        mmap_size_bytes = int(os.getenv("JLCPCB_IMPORT_MMAP_BYTES", str(mmap_bytes)))

        return {
            "batchSize": batch_size,
            "threads": cpu_threads,
            "cacheSizeKb": cache_size_kb,
            "mmapSizeBytes": mmap_size_bytes,
        }

    def _create_component_indexes(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_category ON components(category, subcategory)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_package ON components(package)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_manufacturer ON components(manufacturer)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_library_type ON components(library_type)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_mfr_part ON components(mfr_part)"
        )

    def _drop_component_indexes(self, cursor: sqlite3.Cursor) -> None:
        cursor.execute("DROP INDEX IF EXISTS idx_category")
        cursor.execute("DROP INDEX IF EXISTS idx_package")
        cursor.execute("DROP INDEX IF EXISTS idx_manufacturer")
        cursor.execute("DROP INDEX IF EXISTS idx_library_type")
        cursor.execute("DROP INDEX IF EXISTS idx_mfr_part")

    def get_metadata(self, key: str) -> Optional[str]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM metadata WHERE key = ?", (key,))
        row = cursor.fetchone()
        return str(row["value"]) if row and row["value"] is not None else None

    def set_metadata(self, key: str, value: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            (key, value),
        )
        self.conn.commit()

    def import_parts(self, parts: List[Dict], progress_callback=None):
        """
        Import parts into database from JLCPCB API response

        Args:
            parts: List of part dicts from JLCPCB API
            progress_callback: Optional callback(current, total, message)
        """
        cursor = self.conn.cursor()
        imported = 0
        skipped = 0

        for i, part in enumerate(parts):
            try:
                # Extract price breaks
                price_json = json.dumps(part.get("prices", []))

                # Determine library type
                library_type = self._determine_library_type(part)

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        part.get("componentCode"),  # lcsc
                        part.get("firstSortName"),  # category
                        part.get("secondSortName"),  # subcategory
                        part.get("componentModelEn"),  # mfr_part
                        part.get("componentSpecificationEn"),  # package
                        part.get("soldPoint"),  # solder_joints
                        part.get("componentBrandEn"),  # manufacturer
                        library_type,  # library_type
                        part.get("describe"),  # description
                        part.get("dataManualUrl"),  # datasheet
                        part.get("stockCount", 0),  # stock
                        price_json,  # price_json
                        int(datetime.now().timestamp()),  # last_updated
                    ),
                )

                imported += 1

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(
                        i + 1, len(parts), f"Imported {imported} parts..."
                    )

            except Exception as e:
                logger.error(f"Error importing part {part.get('componentCode')}: {e}")
                skipped += 1

        # Update FTS index
        cursor.execute("""
            INSERT INTO components_fts(components_fts, rowid, lcsc, description, mfr_part, manufacturer)
            SELECT 'rebuild', rowid, lcsc, description, mfr_part, manufacturer FROM components
        """)

        self.conn.commit()
        logger.info(f"Import complete: {imported} parts imported, {skipped} skipped")

    def _determine_library_type(self, part: Dict) -> str:
        """Determine if part is Basic, Extended, or Preferred"""
        # JLCPCB API should provide this, but if not, we infer from assembly type
        assembly_type = part.get("assemblyType", "")

        if "Basic" in assembly_type or part.get("libraryType") == "base":
            return "Basic"
        elif "Extended" in assembly_type:
            return "Extended"
        elif "Prefer" in assembly_type:
            return "Preferred"
        else:
            return "Extended"  # Default to Extended

    def import_jlcsearch_parts(self, parts: List[Dict], progress_callback=None):
        """
        Import parts into database from JLCSearch API response

        Args:
            parts: List of part dicts from JLCSearch API
            progress_callback: Optional callback(current, total, message)
        """
        cursor = self.conn.cursor()
        imported = 0
        skipped = 0

        for i, part in enumerate(parts):
            try:
                # JLCSearch format is different from official API
                # LCSC is an integer, we need to add 'C' prefix
                lcsc = part.get("lcsc")
                if isinstance(lcsc, int):
                    lcsc = f"C{lcsc}"

                # Build price JSON from jlcsearch single price
                price = part.get("price") or part.get("price1")
                price_json = json.dumps([{"qty": 1, "price": price}] if price else [])

                # Determine library type from is_basic flag
                library_type = "Basic" if part.get("is_basic") else "Extended"
                if part.get("is_preferred"):
                    library_type = "Preferred"

                # Extract description from various fields
                description_parts = []
                if "resistance" in part:
                    description_parts.append(f"{part['resistance']}Ω")
                if "capacitance" in part:
                    description_parts.append(f"{part['capacitance']}F")
                if "tolerance_fraction" in part:
                    tol = part["tolerance_fraction"] * 100
                    description_parts.append(f"±{tol}%")
                if "power_watts" in part:
                    description_parts.append(f"{part['power_watts']}mW")
                if "voltage" in part:
                    description_parts.append(f"{part['voltage']}V")

                description = part.get("description", " ".join(description_parts))

                cursor.execute(
                    """
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        lcsc,  # lcsc with C prefix
                        part.get("category", ""),  # category
                        part.get("subcategory", ""),  # subcategory
                        part.get("mfr", ""),  # mfr_part
                        part.get("package", ""),  # package
                        0,  # solder_joints (not in jlcsearch)
                        part.get("manufacturer", ""),  # manufacturer
                        library_type,  # library_type
                        description,  # description
                        "",  # datasheet (not in jlcsearch)
                        part.get("stock", 0),  # stock
                        price_json,  # price_json
                        int(datetime.now().timestamp()),  # last_updated
                    ),
                )

                imported += 1

                if progress_callback and (i + 1) % 1000 == 0:
                    progress_callback(
                        i + 1, len(parts), f"Imported {imported} parts..."
                    )

            except Exception as e:
                logger.error(f"Error importing part {part.get('lcsc')}: {e}")
                skipped += 1

        # Update FTS index
        cursor.execute("""
            INSERT INTO components_fts(components_fts)
            VALUES('rebuild')
        """)

        self.conn.commit()
        logger.info(f"Import complete: {imported} parts imported, {skipped} skipped")

    def import_yaqwsx_cache(
        self,
        cache_db_path: str,
        in_stock_only: bool = True,
        incremental_since: Optional[int] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        source = sqlite3.connect(cache_db_path)
        source.row_factory = sqlite3.Row
        source_cursor = source.cursor()
        cursor = self.conn.cursor()

        def _get_relation_columns(relation_name: str) -> set[str]:
            rows = source_cursor.execute(
                f"PRAGMA table_info({relation_name})"
            ).fetchall()
            return {str(r["name"]) for r in rows}

        def _first_existing(columns: set[str], candidates: List[str]) -> Optional[str]:
            for candidate in candidates:
                if candidate in columns:
                    return candidate
            return None

        try:
            has_view = source_cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_components'"
            ).fetchone()
            source_max_last_update: Optional[int] = None

            conditions: List[str] = []
            if in_stock_only:
                conditions.append("stock > 0")

            if has_view:
                v_cols = _get_relation_columns("v_components")
                mfr_col = _first_existing(
                    v_cols, ["mfr", "mfr_part", "component_model"]
                )
                joints_col = _first_existing(v_cols, ["joints", "solder_joints"])
                last_col = _first_existing(v_cols, ["last_update", "last_updated"])
                basic_col = _first_existing(v_cols, ["basic", "is_basic"])
                preferred_col = _first_existing(v_cols, ["preferred", "is_preferred"])
                library_type_col = _first_existing(v_cols, ["library_type"])
                price_col = _first_existing(v_cols, ["price", "price_json"])

                mfr_expr = mfr_col if mfr_col else "''"
                joints_expr = joints_col if joints_col else "0"
                last_expr = last_col if last_col else "NULL"
                price_expr = price_col if price_col else "NULL"

                if basic_col:
                    basic_expr = basic_col
                elif library_type_col:
                    basic_expr = (
                        f"CASE WHEN {library_type_col} = 'Basic' THEN 1 ELSE 0 END"
                    )
                else:
                    basic_expr = "0"

                if preferred_col:
                    preferred_expr = preferred_col
                elif library_type_col:
                    preferred_expr = (
                        f"CASE WHEN {library_type_col} = 'Preferred' THEN 1 ELSE 0 END"
                    )
                else:
                    preferred_expr = "0"

                if incremental_since is not None and last_col:
                    conditions.append(f"{last_col} > {int(incremental_since)}")
                where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

                if last_col:
                    source_max_row = source_cursor.execute(
                        f"SELECT MAX({last_col}) AS max_last FROM v_components"
                    ).fetchone()
                    if source_max_row and source_max_row["max_last"] is not None:
                        source_max_last_update = int(source_max_row["max_last"])

                count_sql = f"SELECT COUNT(*) AS c FROM v_components {where_clause}"
                select_sql = (
                    "SELECT lcsc, category, subcategory, "
                    f"{mfr_expr} AS mfr, "
                    "package, "
                    f"{joints_expr} AS joints, "
                    "manufacturer, "
                    f"{basic_expr} AS basic, "
                    f"{preferred_expr} AS preferred, "
                    "description, datasheet, stock, "
                    f"{price_expr} AS price, "
                    f"{last_expr} AS last_update "
                    f"FROM v_components {where_clause}"
                )
            else:
                comp_cols = _get_relation_columns("components")
                cat_cols = _get_relation_columns("categories")
                m_cols = _get_relation_columns("manufacturers")

                mfr_col = _first_existing(comp_cols, ["mfr", "mfr_part"])
                joints_col = _first_existing(comp_cols, ["joints", "solder_joints"])
                last_col = _first_existing(comp_cols, ["last_update", "last_updated"])
                basic_col = _first_existing(comp_cols, ["basic", "is_basic"])
                preferred_col = _first_existing(
                    comp_cols, ["preferred", "is_preferred"]
                )
                library_type_col = _first_existing(comp_cols, ["library_type"])
                price_col = _first_existing(comp_cols, ["price", "price_json"])
                cat_name_col = _first_existing(cat_cols, ["category", "name"])
                subcat_name_col = _first_existing(
                    cat_cols, ["subcategory", "sub_category"]
                )
                manu_name_col = _first_existing(m_cols, ["name", "manufacturer"])

                mfr_expr = f"c.{mfr_col}" if mfr_col else "''"
                joints_expr = f"c.{joints_col}" if joints_col else "0"
                last_expr = f"c.{last_col}" if last_col else "NULL"
                price_expr = f"c.{price_col}" if price_col else "NULL"
                category_expr = f"cat.{cat_name_col}" if cat_name_col else "''"
                subcategory_expr = f"cat.{subcat_name_col}" if subcat_name_col else "''"
                manufacturer_expr = f"m.{manu_name_col}" if manu_name_col else "''"

                if basic_col:
                    basic_expr = f"c.{basic_col}"
                elif library_type_col:
                    basic_expr = (
                        f"CASE WHEN c.{library_type_col} = 'Basic' THEN 1 ELSE 0 END"
                    )
                else:
                    basic_expr = "0"

                if preferred_col:
                    preferred_expr = f"c.{preferred_col}"
                elif library_type_col:
                    preferred_expr = f"CASE WHEN c.{library_type_col} = 'Preferred' THEN 1 ELSE 0 END"
                else:
                    preferred_expr = "0"

                component_conditions: List[str] = []
                if in_stock_only:
                    component_conditions.append("c.stock > 0")
                if incremental_since is not None and last_col:
                    component_conditions.append(
                        f"c.{last_col} > {int(incremental_since)}"
                    )
                component_where_clause = (
                    f"WHERE {' AND '.join(component_conditions)}"
                    if component_conditions
                    else ""
                )

                if last_col:
                    source_max_row = source_cursor.execute(
                        f"SELECT MAX({last_col}) AS max_last FROM components"
                    ).fetchone()
                    if source_max_row and source_max_row["max_last"] is not None:
                        source_max_last_update = int(source_max_row["max_last"])

                count_sql = (
                    "SELECT COUNT(*) AS c "
                    "FROM components c "
                    "LEFT JOIN categories cat ON c.category_id = cat.id "
                    "LEFT JOIN manufacturers m ON c.manufacturer_id = m.id "
                    + component_where_clause
                )
                select_sql = (
                    "SELECT c.lcsc AS lcsc, "
                    f"{category_expr} AS category, "
                    f"{subcategory_expr} AS subcategory, "
                    f"{mfr_expr} AS mfr, "
                    "c.package AS package, "
                    f"{joints_expr} AS joints, "
                    f"{manufacturer_expr} AS manufacturer, "
                    f"{basic_expr} AS basic, "
                    f"{preferred_expr} AS preferred, "
                    "c.description AS description, "
                    "c.datasheet AS datasheet, "
                    "c.stock AS stock, "
                    f"{price_expr} AS price, "
                    f"{last_expr} AS last_update "
                    "FROM components c "
                    "LEFT JOIN categories cat ON c.category_id = cat.id "
                    "LEFT JOIN manufacturers m ON c.manufacturer_id = m.id "
                    + component_where_clause
                )

            total = int(source_cursor.execute(count_sql).fetchone()["c"])

            if incremental_since is not None and total == 0:
                return {
                    "imported": 0,
                    "total": 0,
                    "max_last_update": source_max_last_update or incremental_since,
                }

            imported = 0
            batch = []
            now_ts = int(datetime.now().timestamp())
            tuning = self._auto_import_tuning(incremental_since)
            batch_size = int(tuning["batchSize"])
            cpu_threads = int(tuning["threads"])
            cache_size_kb = int(tuning["cacheSizeKb"])
            mmap_size_bytes = int(tuning["mmapSizeBytes"])

            cursor.execute("PRAGMA temp_store = MEMORY")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute(f"PRAGMA cache_size = {cache_size_kb}")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute(f"PRAGMA threads = {cpu_threads}")
            cursor.execute(f"PRAGMA mmap_size = {mmap_size_bytes}")
            cursor.execute("BEGIN IMMEDIATE")

            if incremental_since is None:
                self._drop_component_indexes(cursor)
                cursor.execute("DELETE FROM components")

            if incremental_since is not None:
                cursor.execute(
                    "CREATE TEMP TABLE IF NOT EXISTS updated_lcsc(lcsc TEXT PRIMARY KEY)"
                )

            for row in source_cursor.execute(select_sql):
                lcsc_num = row["lcsc"]
                lcsc = (
                    f"C{int(lcsc_num)}"
                    if isinstance(lcsc_num, int)
                    or (isinstance(lcsc_num, str) and lcsc_num.isdigit())
                    else str(lcsc_num)
                )

                basic = int(row["basic"] or 0)
                preferred = int(row["preferred"] or 0)
                library_type = (
                    "Preferred" if preferred else ("Basic" if basic else "Extended")
                )

                price_raw = row["price"]
                if isinstance(price_raw, str):
                    price_json = price_raw
                else:
                    price_json = json.dumps(price_raw or [])

                batch.append(
                    (
                        lcsc,
                        row["category"] or "",
                        row["subcategory"] or "",
                        row["mfr"] or "",
                        row["package"] or "",
                        int(row["joints"] or 0),
                        row["manufacturer"] or "",
                        library_type,
                        row["description"] or "",
                        row["datasheet"] or "",
                        int(row["stock"] or 0),
                        price_json,
                        int(row["last_update"] or now_ts),
                    )
                )

                if len(batch) >= batch_size:
                    cursor.executemany(
                        """
                        INSERT OR REPLACE INTO components (
                            lcsc, category, subcategory, mfr_part, package,
                            solder_joints, manufacturer, library_type, description,
                            datasheet, stock, price_json, last_updated
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        batch,
                    )

                    if incremental_since is not None:
                        cursor.executemany(
                            "INSERT OR IGNORE INTO updated_lcsc(lcsc) VALUES (?)",
                            [(item[0],) for item in batch],
                        )

                    imported += len(batch)
                    batch = []

                    if progress_callback:
                        progress_callback(
                            imported, total, f"Imported {imported}/{total} parts"
                        )

            if batch:
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO components (
                        lcsc, category, subcategory, mfr_part, package,
                        solder_joints, manufacturer, library_type, description,
                        datasheet, stock, price_json, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                if incremental_since is not None:
                    cursor.executemany(
                        "INSERT OR IGNORE INTO updated_lcsc(lcsc) VALUES (?)",
                        [(item[0],) for item in batch],
                    )
                imported += len(batch)

            if incremental_since is None:
                cursor.execute(
                    "INSERT INTO components_fts(components_fts) VALUES('rebuild')"
                )
                self._create_component_indexes(cursor)
            else:
                cursor.execute(
                    "DELETE FROM components_fts WHERE lcsc IN (SELECT lcsc FROM updated_lcsc)"
                )
                cursor.execute(
                    """
                    INSERT INTO components_fts(rowid, lcsc, description, mfr_part, manufacturer)
                    SELECT c.rowid, c.lcsc, c.description, c.mfr_part, c.manufacturer
                    FROM components c
                    JOIN updated_lcsc u ON u.lcsc = c.lcsc
                    """
                )
                cursor.execute("DROP TABLE IF EXISTS updated_lcsc")

            self.conn.commit()

            return {
                "imported": imported,
                "total": total,
                "max_last_update": source_max_last_update,
            }
        except Exception:
            try:
                self._create_component_indexes(cursor)
                self.conn.rollback()
            except Exception:
                pass
            raise
        finally:
            source.close()

    def search_parts(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        package: Optional[str] = None,
        library_type: Optional[str] = None,
        manufacturer: Optional[str] = None,
        in_stock: bool = True,
        limit: int = 20,
    ) -> List[Dict]:
        """
        Search for parts with filters

        Args:
            query: Free-text search (searches description, mfr part, LCSC)
            category: Filter by category name
            package: Filter by package type
            library_type: Filter by "Basic", "Extended", or "Preferred"
            manufacturer: Filter by manufacturer name
            in_stock: Only return parts with stock > 0
            limit: Maximum number of results

        Returns:
            List of matching parts
        """
        cursor = self.conn.cursor()

        # Build query
        sql_parts = ["SELECT * FROM components WHERE 1=1"]
        params = []

        if query:
            # Use FTS for text search
            sql_parts.append("""
                AND lcsc IN (
                    SELECT lcsc FROM components_fts
                    WHERE components_fts MATCH ?
                )
            """)
            params.append(query)

        if category:
            sql_parts.append("AND category LIKE ?")
            params.append(f"%{category}%")

        if package:
            sql_parts.append("AND package LIKE ?")
            params.append(f"%{package}%")

        if library_type:
            sql_parts.append("AND library_type = ?")
            params.append(library_type)

        if manufacturer:
            sql_parts.append("AND manufacturer LIKE ?")
            params.append(f"%{manufacturer}%")

        if in_stock:
            sql_parts.append("AND stock > 0")

        sql_parts.append("LIMIT ?")
        params.append(limit)

        sql = " ".join(sql_parts)

        try:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_part_info(self, lcsc_number: str) -> Optional[Dict]:
        """
        Get detailed information for specific LCSC part

        Args:
            lcsc_number: LCSC part number (e.g., "C25804")

        Returns:
            Part info dict or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM components WHERE lcsc = ?", (lcsc_number,))
        row = cursor.fetchone()

        if row:
            part = dict(row)
            # Parse price JSON
            if part.get("price_json"):
                try:
                    part["price_breaks"] = json.loads(part["price_json"])
                except:
                    part["price_breaks"] = []
            return part
        return None

    def get_database_stats(self) -> Dict:
        """Get statistics about the database"""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM components")
        total = cursor.fetchone()["total"]

        cursor.execute(
            "SELECT COUNT(*) as basic FROM components WHERE library_type = 'Basic'"
        )
        basic = cursor.fetchone()["basic"]

        cursor.execute(
            "SELECT COUNT(*) as extended FROM components WHERE library_type = 'Extended'"
        )
        extended = cursor.fetchone()["extended"]

        cursor.execute("SELECT COUNT(*) as in_stock FROM components WHERE stock > 0")
        in_stock = cursor.fetchone()["in_stock"]

        return {
            "total_parts": total,
            "basic_parts": basic,
            "extended_parts": extended,
            "in_stock": in_stock,
            "db_path": self.db_path,
        }

    def has_parts(self) -> bool:
        cursor = self.conn.cursor()
        cursor.execute("SELECT 1 FROM components LIMIT 1")
        return cursor.fetchone() is not None

    def map_package_to_footprint(self, package: str) -> List[str]:
        """
        Map JLCPCB package name to KiCAD footprint(s)

        Args:
            package: JLCPCB package name (e.g., "0603", "SOT-23")

        Returns:
            List of possible KiCAD footprint library refs
        """
        # Load mapping from JSON file or use defaults
        mappings = {
            "0402": [
                "Resistor_SMD:R_0402_1005Metric",
                "Capacitor_SMD:C_0402_1005Metric",
                "LED_SMD:LED_0402_1005Metric",
            ],
            "0603": [
                "Resistor_SMD:R_0603_1608Metric",
                "Capacitor_SMD:C_0603_1608Metric",
                "LED_SMD:LED_0603_1608Metric",
            ],
            "0805": [
                "Resistor_SMD:R_0805_2012Metric",
                "Capacitor_SMD:C_0805_2012Metric",
            ],
            "1206": [
                "Resistor_SMD:R_1206_3216Metric",
                "Capacitor_SMD:C_1206_3216Metric",
            ],
            "SOT-23": ["Package_TO_SOT_SMD:SOT-23", "Package_TO_SOT_SMD:SOT-23-3"],
            "SOT-23-5": ["Package_TO_SOT_SMD:SOT-23-5"],
            "SOT-23-6": ["Package_TO_SOT_SMD:SOT-23-6"],
            "SOIC-8": ["Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"],
            "SOIC-16": ["Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"],
            "QFN-20": ["Package_DFN_QFN:QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm"],
            "QFN-32": ["Package_DFN_QFN:QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm"],
        }

        # Normalize package name
        package_normalized = package.strip().upper()

        for key, footprints in mappings.items():
            if key.upper() in package_normalized:
                return footprints

        return []

    def suggest_alternatives(self, lcsc_number: str, limit: int = 5) -> List[Dict]:
        """
        Find alternative parts similar to the given LCSC number

        Prioritizes: cheaper price, higher stock, Basic library type

        Args:
            lcsc_number: Reference LCSC part number
            limit: Maximum alternatives to return

        Returns:
            List of alternative parts
        """
        part = self.get_part_info(lcsc_number)
        if not part:
            return []

        # Search for parts in same category with same package
        alternatives = self.search_parts(
            category=part["subcategory"],
            package=part["package"],
            in_stock=True,
            limit=limit * 3,
        )

        # Filter out the original part
        alternatives = [p for p in alternatives if p["lcsc"] != lcsc_number]

        # Sort by: Basic first, then by price, then by stock
        def sort_key(p):
            is_basic = 1 if p.get("library_type") == "Basic" else 0
            try:
                prices = json.loads(p.get("price_json", "[]"))
                price = float(prices[0].get("price", 999)) if prices else 999
            except:
                price = 999
            stock = p.get("stock", 0)

            return (-is_basic, price, -stock)

        alternatives.sort(key=sort_key)

        return alternatives[:limit]

    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()


if __name__ == "__main__":
    # Test the parts manager
    logging.basicConfig(level=logging.INFO)

    manager = JLCPCBPartsManager()

    # Get stats
    stats = manager.get_database_stats()
    print(f"\nDatabase Statistics:")
    print(f"  Total parts: {stats['total_parts']}")
    print(f"  Basic parts: {stats['basic_parts']}")
    print(f"  Extended parts: {stats['extended_parts']}")
    print(f"  In stock: {stats['in_stock']}")
    print(f"  Database: {stats['db_path']}")

    if stats["total_parts"] > 0:
        print("\nSearching for '10k resistor'...")
        results = manager.search_parts(query="10k resistor", limit=5)
        for part in results:
            print(
                f"  {part['lcsc']}: {part['mfr_part']} - {part['description']} ({part['library_type']})"
            )
