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
        
    def get_all_stocks(self):
        """Retrieve all stocks from the container."""
        query = "SELECT * FROM c"
        items = list(self.container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        return items
        
    def upsert_stock(self, stock_item: dict):
        """Insert or update a stock item."""
        # Ensure it has 'id' field, which CosmosDB requires
        if 'id' not in stock_item:
            # We'll use the formatted symbol as the unique ID for a stock
            stock_code = stock_item.get("Stock Code", "").strip().upper()
            exchange = stock_item.get("Exchange", "").strip().upper()
            suffix = ".NS" if exchange == "NSE" else ".BO" if exchange == "BSE" else ""
            stock_item['id'] = f"{stock_code}{suffix}"
            
        self.container.upsert_item(body=stock_item)
        return stock_item
        
    def get_stock(self, symbol: str, exchange: str):
        """Retrieve a specific stock by its id (symbol) and partition key (exchange)."""
        try:
            item = self.container.read_item(item=symbol, partition_key=exchange)
            return item
        except Exception:
            return None
            
    def delete_stock(self, symbol: str, exchange: str):
        """Delete a stock item."""
        try:
            self.container.delete_item(item=symbol, partition_key=exchange)
            return True
        except Exception:
            return False

# Create a singleton instance
cosmos_service = CosmosDBService()
