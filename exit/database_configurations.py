# config/database_config.py
DATABASE_CONFIG = {
    'mysql': {
        'host': 'localhost',
        'user': 'parking_user',
        'password': 'secure_password',
        'database': 'parking_system'
    },
    'redis': {
        'host': 'localhost',
        'port': 6379,
        'db': 0
    },
    'fallback_mode': True,  # Continue with Redis-only if MySQL fails
    'sync_interval': 300    # Background sync every 5 minutes
}