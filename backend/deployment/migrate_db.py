import sqlite3

db_path = './olimpiada.db'

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

columns_to_add = [
    ('avatar_url', 'TEXT'),
    ('bio', 'TEXT'),
    ('phone', 'TEXT'),
    ('telegram', 'TEXT'),
    ('vk', 'TEXT'),
    ('github', 'TEXT')
]

for column_name, column_type in columns_to_add:
    try:
        cursor.execute(f'ALTER TABLE users ADD COLUMN {column_name} {column_type}')
        print(f'Добавлен столбец {column_name}')
    except sqlite3.OperationalError as e:
        if 'duplicate column name' in str(e):
            print(f'Столбец {column_name} уже существует')
        else:
            print(f'Ошибка при добавлении {column_name}: {e}')

conn.commit()
conn.close()
print('Миграция завершена')
