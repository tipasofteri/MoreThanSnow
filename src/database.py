from pymongo import MongoClient
from pymongo.database import Database
from typing import Dict, Any

# Используем словарь вместо MongoDB
fake_db = {
    'games': {},
    'users': {}
}

class FakeCollection:
    def __init__(self, name: str):
        self.name = name
    
    def find_one(self, query: Dict[str, Any]) -> Dict[str, Any]:
        if self.name not in fake_db:
            return None
        if not query:
            return fake_db[self.name]
        for doc in fake_db[self.name].values():
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None
    
    def insert_one(self, document: Dict[str, Any]) -> None:
        if self.name not in fake_db:
            fake_db[self.name] = {}
        _id = document.get('_id', len(fake_db[self.name]) + 1)
        fake_db[self.name][_id] = document
        return {'inserted_id': _id}
    
    def update_one(self, query: Dict[str, Any], update: Dict[str, Any]) -> None:
        doc = self.find_one(query)
        if doc and '$set' in update:
            doc.update(update['$set'])
            return {'modified_count': 1}
        return {'modified_count': 0}

class FakeDB:
    def __getattr__(self, name: str) -> FakeCollection:
        return FakeCollection(name)

# Используем фейковую базу данных
database = FakeDB()