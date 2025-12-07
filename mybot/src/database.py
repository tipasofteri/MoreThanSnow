import os
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import uuid
import threading
from copy import deepcopy

class Database:
    def __init__(self, db_path: str = 'data'):
        self.db_path = Path(db_path)
        self.db_path.mkdir(exist_ok=True)
        self._locks: Dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, collection_name: str) -> threading.Lock:
        with self._global_lock:
            if collection_name not in self._locks:
                self._locks[collection_name] = threading.Lock()
            return self._locks[collection_name]
    
    def _get_collection_path(self, collection_name: str) -> Path:
        return self.db_path / f"{collection_name}.json"
    
    def _read_collection(self, collection_name: str) -> Dict[str, Any]:
        path = self._get_collection_path(collection_name)
        if not path.exists():
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}
    
    def _write_collection(self, collection_name: str, data: Dict[str, Any]):
        path = self._get_collection_path(collection_name)
        temp_path = path.with_suffix('.tmp')
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)

    def _get_path(self, doc, path):
        keys = path.split('.')
        curr = doc
        for i, key in enumerate(keys):
            if isinstance(curr, dict):
                if key in curr:
                    curr = curr[key]
                else:
                    return None
            elif isinstance(curr, list):
                if key.isdigit():
                    idx = int(key)
                    if 0 <= idx < len(curr):
                        curr = curr[idx]
                    else:
                        return None
                else:
                    remaining_path = '.'.join(keys[i:])
                    results = []
                    for item in curr:
                        val = self._get_path(item, remaining_path)
                        if val is not None:
                            if isinstance(val, list): results.extend(val)
                            else: results.append(val)
                    return results if results else None
            else:
                return None
        return curr

    def _set_path(self, doc, path, value):
        keys = path.split('.')
        curr = doc
        for i, key in enumerate(keys[:-1]):
            if isinstance(curr, dict):
                if key not in curr:
                    curr[key] = {}
                curr = curr[key]
            elif isinstance(curr, list) and key.isdigit():
                idx = int(key)
                curr = curr[idx]
            else:
                return 
        
        last_key = keys[-1]
        if isinstance(curr, dict):
            curr[last_key] = value
        elif isinstance(curr, list) and last_key.isdigit():
            idx = int(last_key)
            if 0 <= idx < len(curr):
                curr[idx] = value

    def _unset_path(self, doc, path):
        keys = path.split('.')
        curr = doc
        for i, key in enumerate(keys[:-1]):
            if isinstance(curr, dict):
                if key not in curr:
                    return
                curr = curr[key]
            elif isinstance(curr, list) and key.isdigit():
                idx = int(key)
                if 0 <= idx < len(curr):
                    curr = curr[idx]
                else:
                    return
            else:
                return
        
        last_key = keys[-1]
        if isinstance(curr, dict) and last_key in curr:
            del curr[last_key]
        elif isinstance(curr, list) and last_key.isdigit():
            idx = int(last_key)
            if 0 <= idx < len(curr):
                curr.pop(idx)

    def _matches_query(self, doc: Dict[str, Any], query: Dict[str, Any]) -> bool:
        try:
            for key, value in query.items():
                if key == '$or':
                    if not any(self._matches_query(doc, cond) for cond in value): return False
                elif key == '$and':
                    if not all(self._matches_query(doc, cond) for cond in value): return False
                elif isinstance(value, dict) and any(k.startswith('$') for k in value):
                    doc_value = self._get_path(doc, key)
                    for op, op_value in value.items():
                        if op == '$lte':
                            if doc_value is None or doc_value > op_value: return False
                        elif op == '$lt':
                            if doc_value is None or doc_value >= op_value: return False
                        elif op == '$gte':
                            if doc_value is None or doc_value < op_value: return False
                        elif op == '$gt':
                            if doc_value is None or doc_value <= op_value: return False
                        elif op == '$eq':
                            if doc_value != op_value: return False
                        elif op == '$ne':
                            if doc_value == op_value: return False
                        elif op == '$in':
                            if doc_value not in op_value: return False
                        elif op == '$nin':
                            if doc_value in op_value: return False
                        elif op == '$exists':
                            exists = self._get_path(doc, key) is not None
                            if (op_value and not exists) or (not op_value and exists): return False
                        elif op == '$elemMatch':
                            if not isinstance(doc_value, list): return False
                            if not any(self._matches_query(item, op_value) for item in doc_value): return False
                        else:
                            return False
                else:
                    doc_value = self._get_path(doc, key)
                    if isinstance(doc_value, list) and not isinstance(value, list):
                        if value not in doc_value: return False
                    elif doc_value != value:
                        return False
            return True
        except (TypeError, KeyError, ValueError):
            return False

    def find_one(self, collection_name: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._get_lock(collection_name):
            collection = self._read_collection(collection_name)
            for doc_id, doc in collection.items():
                full_doc = {**doc, '_id': doc_id}
                if self._matches_query(full_doc, query):
                    return full_doc
            return None
    
    def find(self, collection_name: str, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        with self._get_lock(collection_name):
            collection = self._read_collection(collection_name)
            if not query:
                return [{**doc, '_id': doc_id} for doc_id, doc in collection.items()]
            results = []
            for doc_id, doc in collection.items():
                full_doc = {**doc, '_id': doc_id}
                if self._matches_query(full_doc, query):
                    results.append(full_doc)
            return results
    
    def insert_one(self, collection_name: str, document: Dict[str, Any]) -> str:
        with self._get_lock(collection_name):
            collection = self._read_collection(collection_name)
            doc_id = str(uuid.uuid4())
            collection[doc_id] = document
            self._write_collection(collection_name, collection)
            return doc_id
    
    def update_one(self, collection_name: str, query: Dict[str, Any], update: Dict[str, Any], upsert: bool = False) -> bool:
        with self._get_lock(collection_name):
            collection = self._read_collection(collection_name)
            updated = False
            
            for doc_id, doc in collection.items():
                full_doc = {**doc, '_id': doc_id}
                if self._matches_query(full_doc, query):
                    if '$set' in update:
                        for k, v in update['$set'].items(): self._set_path(doc, k, v)
                    if '$inc' in update:
                        for k, v in update['$inc'].items():
                            current_val = self._get_path(doc, k) or 0
                            self._set_path(doc, k, current_val + v)
                    if '$push' in update:
                        for k, v in update['$push'].items():
                            target_list = self._get_path(doc, k)
                            if target_list is None:
                                target_list = []
                                self._set_path(doc, k, target_list)
                            if isinstance(target_list, list): target_list.append(v)
                    if '$addToSet' in update:
                        for k, v in update['$addToSet'].items():
                            target_list = self._get_path(doc, k)
                            if target_list is None:
                                target_list = []
                                self._set_path(doc, k, target_list)
                            if isinstance(target_list, list):
                                if v not in target_list: target_list.append(v)
                    
                    # ИСПРАВЛЕННАЯ ЛОГИКА $pull
                    if '$pull' in update:
                        for k, v in update['$pull'].items():
                            target_list = self._get_path(doc, k)
                            if isinstance(target_list, list):
                                new_list = []
                                for item in target_list:
                                    should_remove = False
                                    # Проверка удаления по словарю (например {id: 123})
                                    if isinstance(v, dict):
                                        # Если критерий - словарь, проверяем соответствие полей
                                        match = True
                                        for sub_k, sub_v in v.items():
                                            if not isinstance(item, dict) or item.get(sub_k) != sub_v:
                                                match = False
                                                break
                                        if match: should_remove = True
                                    # Проверка удаления по значению
                                    elif item == v:
                                        should_remove = True
                                    
                                    if not should_remove:
                                        new_list.append(item)
                                self._set_path(doc, k, new_list)

                    if '$unset' in update:
                        for k in update['$unset']: self._unset_path(doc, k)

                    collection[doc_id] = doc
                    self._write_collection(collection_name, collection)
                    return True
            
            if not updated and upsert:
                new_doc = {k: v for k, v in query.items() if not k.startswith('$')}
                if '$set' in update:
                    for k, v in update['$set'].items(): self._set_path(new_doc, k, v)
                if '$inc' in update:
                    for k, v in update['$inc'].items(): self._set_path(new_doc, k, v)
                doc_id = str(uuid.uuid4())
                collection[doc_id] = new_doc
                self._write_collection(collection_name, collection)
                return True

            return False
            
    def delete_one(self, collection_name: str, query: Dict[str, Any]) -> bool:
        with self._get_lock(collection_name):
            collection = self._read_collection(collection_name)
            for doc_id, doc in list(collection.items()):
                full_doc = {**doc, '_id': doc_id}
                if self._matches_query(full_doc, query):
                    del collection[doc_id]
                    self._write_collection(collection_name, collection)
                    return True
            return False

    def delete_many(self, collection_name: str, query: Dict[str, Any]) -> int:
        with self._get_lock(collection_name):
            collection = self._read_collection(collection_name)
            to_delete = []
            for doc_id, doc in collection.items():
                full_doc = {**doc, '_id': doc_id}
                if self._matches_query(full_doc, query):
                    to_delete.append(doc_id)
            
            if to_delete:
                for doc_id in to_delete:
                    del collection[doc_id]
                self._write_collection(collection_name, collection)
            
            return len(to_delete)

    def find_one_and_update(self, collection_name: str, query: Dict[str, Any], update: Dict[str, Any], **kwargs):
        """Атомарная операция: найти документ по условию и обновить его"""
        with self._get_lock(collection_name):
            collection = self._read_collection(collection_name)
            
            # Сначала находим документ по условию
            found_doc = None
            found_id = None
            for doc_id, doc in collection.items():
                full_doc = {**doc, '_id': doc_id}
                if self._matches_query(full_doc, query):
                    found_doc = doc
                    found_id = doc_id
                    break
            
            # Если документ не найден, возвращаем None
            if not found_doc:
                return None
            
            # Обновляем найденный документ
            if '$set' in update:
                for k, v in update['$set'].items(): 
                    self._set_path(found_doc, k, v)
            if '$inc' in update:
                for k, v in update['$inc'].items():
                    current_val = self._get_path(found_doc, k) or 0
                    self._set_path(found_doc, k, current_val + v)
            if '$addToSet' in update:
                for k, v in update['$addToSet'].items():
                    current_list = self._get_path(found_doc, k) or []
                    if not isinstance(current_list, list):
                        current_list = []
                    if v not in current_list:
                        current_list.append(v)
                    self._set_path(found_doc, k, current_list)
            if '$push' in update:
                for k, v in update['$push'].items():
                    current_list = self._get_path(found_doc, k) or []
                    if not isinstance(current_list, list):
                        current_list = []
                    current_list.append(v)
                    self._set_path(found_doc, k, current_list)
            if '$pull' in update:
                for k, v in update['$pull'].items():
                    target_list = self._get_path(found_doc, k)
                    if isinstance(target_list, list):
                        new_list = []
                        for item in target_list:
                            should_remove = False
                            # Проверка удаления по словарю (например {id: 123})
                            if isinstance(v, dict):
                                # Если критерий - словарь, проверяем соответствие полей
                                match = True
                                for sub_k, sub_v in v.items():
                                    if not isinstance(item, dict) or item.get(sub_k) != sub_v:
                                        match = False
                                        break
                                if match: should_remove = True
                            # Проверка удаления по значению
                            elif item == v:
                                should_remove = True
                            
                            if not should_remove:
                                new_list.append(item)
                        self._set_path(found_doc, k, new_list)
            if '$unset' in update:
                for k in update['$unset']:
                    self._unset_path(found_doc, k)
            
            # Сохраняем изменения
            self._write_collection(collection_name, collection)
            
            # Возвращаем обновленный документ
            return_document = kwargs.get('return_document', False)
            if return_document:
                return {**found_doc, '_id': found_id}
            return found_doc

# Инициализация
db_instance = Database('data')

# Экспорт функций
find = db_instance.find
find_one = db_instance.find_one
insert_one = db_instance.insert_one
update_one = db_instance.update_one
delete_one = db_instance.delete_one
delete_many = db_instance.delete_many
find_one_and_update = db_instance.find_one_and_update