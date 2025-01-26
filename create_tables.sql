-- Создание таблицы для отслеживания синхронизации
CREATE TABLE IF NOT EXISTS sync_history (
    service VARCHAR(50) PRIMARY KEY,
    last_sync TIMESTAMP WITH TIME ZONE
);

-- Создание таблицы для хранения треков
CREATE TABLE IF NOT EXISTS tracks (
    yandex_id VARCHAR(50),
    spotify_id VARCHAR(50),
    artist VARCHAR(255),
    title VARCHAR(255),
    PRIMARY KEY (yandex_id, spotify_id)
);

-- Создание таблицы для ненайденных треков
CREATE TABLE IF NOT EXISTS undiscovered_tracks (
    id SERIAL PRIMARY KEY,
    service VARCHAR(50),
    artist VARCHAR(255),
    title VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
); 