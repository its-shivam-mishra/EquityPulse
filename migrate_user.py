from app.cosmos_service import cosmos_service

# Create shivam user
cosmos_service.create_user("shivam", "shivam12345")
print("Created user 'shivam'")

# Fetch all existing stocks by doing a raw query
query = "SELECT * FROM c"
items = list(cosmos_service.container.query_items(
    query=query,
    enable_cross_partition_query=True
))

changed = 0
for item in items:
    if 'username' not in item or not item['username']:
        old_id = item['id']
        old_ex = item.get('Exchange', 'NSE')
        print(f"Migrating stock {old_id} to shivam")
        
        # update fields
        item['username'] = "shivam"
        item['id'] = f"shivam_{old_id}"
        
        # insert new
        cosmos_service.container.upsert_item(body=item)
        # delete old
        cosmos_service.container.delete_item(item=old_id, partition_key=old_ex)
        changed += 1

print(f"Migrated {changed} stocks to user 'shivam'.")
