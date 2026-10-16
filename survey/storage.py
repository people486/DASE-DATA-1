"""MongoDB 集合验证器及索引，幂等初始化。"""
import os
from pymongo import MongoClient, ASCENDING

def connect(name=None):
    client = MongoClient(os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27018/'), serverSelectionTimeoutMS=5000, tz_aware=True)
    client.admin.command('ping')
    return client[name or os.getenv('MONGO_DB', 'lab4_survey')]

def initialize(db):
    schemas = {
        'users': ({'username': {'bsonType': 'string'}, 'password_hash': {'bsonType': 'string'}, 'created_at': {'bsonType': 'date'}}, ['username', 'password_hash', 'created_at']),
        'sessions': ({'user_id': {'bsonType': 'string'}, 'expires_at': {'bsonType': 'date'}}, ['user_id', 'expires_at']),
        'surveys': ({'owner_id': {'bsonType': 'string'}, 'status': {'enum': ['draft', 'published', 'closed']}, 'questions': {'bsonType': 'array'}, 'schema_version': {'bsonType': 'int'}, 'revision': {'bsonType': 'int'}}, ['owner_id', 'status', 'questions', 'schema_version', 'revision']),
        'responses': ({'survey_id': {'bsonType': 'string'}, 'answers': {'bsonType': 'object'}, 'path': {'bsonType': 'array'}, 'submitted_at': {'bsonType': 'date'}, 'survey_revision': {'bsonType': 'int'}}, ['survey_id', 'answers', 'path', 'submitted_at', 'survey_revision']),
    }
    for name, (props, required) in schemas.items():
        validator = {'$jsonSchema': {'bsonType': 'object', 'required': required, 'properties': props}}
        if name not in db.list_collection_names():
            db.create_collection(name, validator=validator)
        else:
            db.command('collMod', name, validator=validator)
    db.users.create_index('username', unique=True)
    db.sessions.create_index('expires_at', expireAfterSeconds=0)
    db.surveys.create_index([('owner_id', ASCENDING), ('created_at', ASCENDING)])
    db.responses.create_index([('survey_id', ASCENDING), ('submitted_at', ASCENDING)])
    db.responses.create_index([('survey_id', ASCENDING), ('dedupe_key', ASCENDING)], unique=True, partialFilterExpression={'dedupe_key': {'$type': 'string'}})
    db.responses.create_index([('survey_id', ASCENDING), ('request_id', ASCENDING)], unique=True)
