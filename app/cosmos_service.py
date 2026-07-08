import os
from azure.cosmos import CosmosClient, PartitionKey
from dotenv import load_dotenv

load_dotenv()

class CosmosDBService:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CosmosDBService, cls).__new__(cls)
            cls._instance.initialize()
        return cls._instance
        
    def initialize(self):
        connection_string = os.getenv("cosmosconnectionstring")
        if not connection_string:
            raise ValueError("cosmosconnectionstring is not set in the environment variables.")
            
        self.db_name = os.getenv("COSMOS_DB_NAME", "equityPulse")
        self.container_name = os.getenv("COSMOS_CONTAINER_NAME", "Stocks")
        self.users_container_name = "Users"
        
        # Initialize the Cosmos client
        self.client = CosmosClient.from_connection_string(connection_string)
        
        # Create database if not exists
        self.database = self.client.create_database_if_not_exists(id=self.db_name)
        
        # Create container if not exists
        # Using /Exchange as the partition key based on our implementation plan
        self.container = self.database.create_container_if_not_exists(
            id=self.container_name,
            partition_key=PartitionKey(path="/Exchange")
        )
        
        # Create Users container
        self.users_container = self.database.create_container_if_not_exists(
            id=self.users_container_name,
            partition_key=PartitionKey(path="/username")
        )
        
    def create_user(self, username: str, password: str):
        """Create a new user with plain text password."""
        user_item = {
            "id": username,
            "username": username,
            "password": password
        }
        self.users_container.upsert_item(body=user_item)
        return user_item

    def get_user(self, username: str):
        """Retrieve a user by username."""
        try:
            return self.users_container.read_item(item=username, partition_key=username)
        except Exception:
            return None

    def get_all_stocks(self, username: str):
        """Retrieve all stocks for a specific user."""
        query = "SELECT * FROM c WHERE c.username = @username"
        parameters = [{"name": "@username", "value": username}]
        items = list(self.container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        return items
        
    def upsert_stock(self, stock_item: dict, username: str):
        """Insert or update a stock item for a user."""
        stock_item['username'] = username
        
        if 'id' not in stock_item or '_' not in stock_item['id']:
            stock_code = stock_item.get("Stock Code", "").strip().upper()
            exchange = stock_item.get("Exchange", "").strip().upper()
            suffix = ".NS" if exchange == "NSE" else ".BO" if exchange == "BSE" else ""
            symbol = f"{stock_code}{suffix}"
            stock_item['id'] = f"{username}_{symbol}"
            
        self.container.upsert_item(body=stock_item)
        return stock_item
        
    def get_stock(self, symbol: str, exchange: str, username: str):
        """Retrieve a specific stock by its id (symbol) and partition key (exchange) for a user."""
        try:
            item_id = f"{username}_{symbol}"
            item = self.container.read_item(item=item_id, partition_key=exchange)
            return item
        except Exception:
            return None
            
    def delete_stock(self, symbol: str, exchange: str, username: str):
        """Delete a stock item for a user."""
        try:
            item_id = f"{username}_{symbol}"
            self.container.delete_item(item=item_id, partition_key=exchange)
            return True
        except Exception:
            return False

# Create a singleton instance
cosmos_service = CosmosDBService()
