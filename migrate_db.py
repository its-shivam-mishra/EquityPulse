from app.cosmos_service import cosmos_service
from app.services import format_symbol

items = cosmos_service.get_all_stocks()
changed = 0

for item in items:
    formatted = format_symbol(item['id'])
    if formatted != item['id']:
        old_id = item['id']
        old_ex = item.get('Exchange', 'NSE')
        print(f"Migrating {old_id} -> {formatted}")
        
        item['id'] = formatted
        item['Stock Code'] = formatted.rsplit('.', 1)[0] if '.' in formatted else formatted
        
        cosmos_service.upsert_stock(item)
        cosmos_service.delete_stock(old_id, old_ex)
        changed += 1

print(f'Migrated {changed} items.')
