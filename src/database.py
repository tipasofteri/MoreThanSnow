from pymongo import MongoClient, ReturnDocument
from pymongo.errors import ConnectionFailure
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_database():
    try:
        # Get MongoDB connection string from environment variables
        mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
        
        # Connect to MongoDB
        client = MongoClient(mongo_uri)
        
        # Test the connection
        client.admin.command('ping')
        logger.info("Successfully connected to MongoDB")
        
        # Get or create the database
        db_name = os.getenv('MONGODB_DB_NAME', 'mafia_host_bot')
        db = client[db_name]
        
        # Ensure required collections exist
        collections = ['games', 'users', 'counters', 'requests']
        for collection in collections:
            if collection not in db.list_collection_names():
                db.create_collection(collection)
                logger.info(f"Created collection: {collection}")
        
        # Initialize counters if they don't exist
        for coll in ['games', 'users']:
            db.counters.update_one(
                {"_id": coll},
                {"$setOnInsert": {"next": 1}},
                upsert=True
            )
        
        return db
        
    except ConnectionFailure as e:
        logger.error(f"Could not connect to MongoDB: {e}")
        raise

# Initialize the database
try:
    database = get_database()
    logger.info("Database initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize database: {e}")
    # Don't raise here to allow the bot to start in read-only mode if needed
    database = None

def get_new_id(collection):
    if not database:
        raise RuntimeError("Database not initialized")
        
    counter = database.counters.find_one_and_update(
        {"_id": collection},
        {"$inc": {"next": 1}},
        return_document=ReturnDocument.AFTER,
        upsert=True
    )
    return counter["next"]
