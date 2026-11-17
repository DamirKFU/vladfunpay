import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

from app.db.mongo import EXPORT_COLLECTIONS
from app.usecases.data import BaseDatabaseDumper


def _default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    return str(value)


@dataclass(frozen=True)
class MongoDatabaseDumper(BaseDatabaseDumper):
    db: AsyncDatabase

    async def dump(self, archive: zipfile.ZipFile) -> list[str]:
        for name in EXPORT_COLLECTIONS:
            with archive.open(f'{name}.jsonl', 'w') as f:
                async for doc in self.db[name].find():
                    line = json.dumps(
                        doc, ensure_ascii=False, default=_default
                    )
                    f.write(line.encode() + b'\n')
        return list(EXPORT_COLLECTIONS)
